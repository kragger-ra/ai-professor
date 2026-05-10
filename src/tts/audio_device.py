# -*- coding: utf-8 -*-

import asyncio
import glob
import io
import os
import sys
import threading
import time
import traceback
from typing import Optional, Tuple

import librosa
import numpy as np
import pygame
import scipy.io.wavfile as wf
import sounddevice as sd
import soundcard as sc

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from data_schema.structure_templates import (
    FX_AUDIO_DIR,
    FX_MANIFEST,
    REPO_RESOURCE_PATH,
)
from utils.prompt_helper import yaml_load

# TODO add in env (if not in env chose this default)
SOUND_DEVICE_IN = os.getenv("SOUND_DEVICE_IN", "CABLE Input (VB-Audio Virtual Cable)")
SOUND_DEVICE_OUT = os.getenv(
    "SOUND_DEVICE_OUT", "CABLE Output (VB-Audio Virtual Cable)"
)
FX_SOUND_DEVICE_IN = os.getenv(
    "FX_SOUND_DEVICE_IN", "CABLE Input (VB-Audio Virtual Cable)"
)
FX_SOUND_DEVICE_OUT = os.getenv(
    "FX_SOUND_DEVICE_OUT", "CABLE Output (VB-Audio Virtual Cable)"
)
SOUND_DEVICE_SR = int(os.getenv("SOUND_DEVICE_SR", "48000"))


def get_fx_sound_list():
    return yaml_load(FX_MANIFEST)


# TODO move in audio utils
def save_audio_to_buffer(data, sr):
    bytes_wav = bytes()
    byte_io = io.BytesIO(bytes_wav)
    wf.write(byte_io, sr, data)
    return byte_io


class AudioProcessor:
    def __init__(self):
        # Lets init pygame mixer to provide it devices list
        # looks like this should be the first!
        self.setup_fx_device_pygame()

        # Main audio device setup
        self.device_sr = SOUND_DEVICE_SR  # for vb cable A
        self.fx_device_sr = SOUND_DEVICE_SR  # for vb cable B
        self._setup_main_audio_devices()
        self._setup_fx_audio_devices()
        self.playqueue = asyncio.Queue()  # Replace standard Queue
        self.playlist = []
        self.playlist_loop = 0
        self.playing_music = False
        self.playlist_fade = 500
        self.music_task = None
        self._loop = None  # Store event loop reference
        self._running_loop = False
        self.music_thread = None
        self._is_async_context = False
        self._last_interrupt_time = 0
        # Set default sounddevice output
        print(f"[Audio] Final output audio devices names i/o {self.main_speaker.name}")
        print(f"[Audio] FX audio device names i/o {self.fx_speaker.name}")

    @property
    def loop(self):
        """Get or create event loop for both sync/async contexts"""
        if self._loop is None:
            try:
                self._loop = asyncio.get_running_loop()
                self._is_async_context = True
            except RuntimeError:
                self._loop = asyncio.new_event_loop()
                self._is_async_context = False
        return self._loop

    def setup_fx_device_pygame(self):
        """Initialize pygame mixer for FX sounds. Non-fatal if it fails — main
        TTS uses soundcard (separate library) and does not depend on pygame."""
        if pygame.mixer.get_init():
            print("[Audio] Pygame mixer already initialized.")
            return
        try:
            kwargs = {
                "frequency": SOUND_DEVICE_SR,
                "size": -16,
                "channels": 2,
                "devicename": FX_SOUND_DEVICE_OUT,
                "buffer": 7168,
            }
            pygame.mixer.pre_init(**kwargs)
            pygame.mixer.init(**kwargs)
            pygame.mixer.music.set_volume(0.5)
            return
        except Exception as e:
            print(f"[Audio] FX device {FX_SOUND_DEVICE_OUT!r} init failed: {e}; trying default")
        try:
            pygame.mixer.pre_init()
            pygame.mixer.init()
            pygame.mixer.music.set_volume(0.5)
        except Exception as e:
            print(f"[Audio] Pygame default init failed: {e}; FX sounds DISABLED, main TTS unaffected")

    def _find_speaker_by_name(self, target_name: str):
        """Helper method to find speaker by name."""
        speakers = sc.all_speakers()
        for s in speakers:
            if s.name == target_name:
                return s
        # Fuzzy match fallback
        for s in speakers:
            if target_name in s.name:
                return s
        return None

    def _setup_main_audio_devices(self):
        """Setup main TTS output speaker."""
        self.main_speaker = self._find_speaker_by_name(SOUND_DEVICE_OUT)

        # Fallback to defaults if not found
        if self.main_speaker is None:
            self.main_speaker = sc.default_speaker()
            print(
                f"[Audio] Main device '{SOUND_DEVICE_OUT}' not found, using default: {self.main_speaker.name}"
            )
        else:
            print(f"[Audio] Main device found: {self.main_speaker.name}")

        # Resolve a sounddevice output index for shared-mode playback (MME/DSound
        # before WASAPI). Avoids exclusive capture that blocks other apps.
        self._main_sd_index = self._find_sd_output_index(SOUND_DEVICE_OUT)
        if self._main_sd_index is None:
            print(
                f"[Audio] sounddevice fallback to system default for '{SOUND_DEVICE_OUT}'"
            )
        else:
            try:
                info = sd.query_devices(self._main_sd_index)
                api = sd.query_hostapis(info["hostapi"])["name"]
                print(
                    f"[Audio] sounddevice main idx={self._main_sd_index} "
                    f"name='{info['name']}' api={api}"
                )
            except Exception as e:
                print(f"[Audio] sounddevice info read failed: {e}")

    def _setup_fx_audio_devices(self):
        """Setup secondary (FX) audio output speaker."""
        self.fx_speaker = self._find_speaker_by_name(FX_SOUND_DEVICE_OUT)

        # Fallback to defaults if not found
        if self.fx_speaker is None:
            print(
                f'[AUDIO] FX device "{FX_SOUND_DEVICE_OUT}" not found, using main device'
            )
            self.fx_speaker = self.main_speaker
        else:
            print(f"[Audio] FX device found: {self.fx_speaker.name}")

    def print_devices(self):
        print("=== DEBUG Listing available audio devices (via SoundCard library) ===")
        print("Speakers:")
        for i, s in enumerate(sc.all_speakers()):
            print(f" {i} - '{s.name}' (id: {s.id})")
        print("Microphones:")
        for i, m in enumerate(sc.all_microphones()):
            print(f" {i} - '{m.name}' (id: {m.id})")
        print("\n=== End of audio devices list ===")

    def play_sound(
        self,
        audio: np.ndarray,
        sample_rate: int = 48000,
        fx_device=False,
        device: Optional[str] = None,
        blocking=False,
    ) -> None:
        # vb cable STRICT sr 48k
        target_sr = self.device_sr if not fx_device else self.fx_device_sr
        fixed_audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_sr)

        speaker = self.main_speaker
        if fx_device:
            speaker = self.fx_speaker

        if device is not None:
            if isinstance(device, str):
                found = self._find_speaker_by_name(device)
                if found:
                    speaker = found
                else:
                    print(
                        f"[Audio] Device '{device}' not found, using default/current: {speaker.name}"
                    )

        if device is None and fx_device:
            if not pygame.mixer.get_init():
                # FX sounds disabled (pygame init failed); silently skip.
                return
            byte_io = save_audio_to_buffer(fixed_audio, target_sr)
            sound = pygame.mixer.Sound(byte_io)
            sound.play()
            if blocking:
                while pygame.mixer.get_busy():
                    try:
                        asyncio.get_running_loop().run_until_complete(
                            asyncio.sleep(0.1)
                        )
                    except RuntimeError:
                        asyncio.new_event_loop().run_until_complete(asyncio.sleep(0.1))
            # sd.play(fixed_audio, target_sr, device=self.fx_in_device_index)
        else:
            if blocking:
                self._play_safe(speaker, fixed_audio, target_sr)
            else:
                threading.Thread(
                    target=self._play_safe,
                    args=(speaker, fixed_audio, target_sr),
                    daemon=True,
                ).start()

    @staticmethod
    def _find_sd_output_index(name: str) -> Optional[int]:
        """Find a sounddevice output index matching `name` (substring, case-insensitive).

        Prefers MME (hostapi 0) and DirectSound (hostapi 1) over WASAPI to avoid
        exclusive-mode capture and let other apps mix audio on the same device.
        """
        if not name:
            return None
        lower = name.lower()
        try:
            devices = sd.query_devices()
        except Exception:
            return None
        # Order: MME, DirectSound, then anything else.
        priority = []
        for i, d in enumerate(devices):
            if d.get("max_output_channels", 0) <= 0:
                continue
            if lower not in d["name"].lower():
                continue
            api = d.get("hostapi", -1)
            score = 0 if api == 0 else (1 if api == 1 else 2)
            priority.append((score, i))
        priority.sort()
        return priority[0][1] if priority else None

    def _play_safe(self, speaker, audio, sr):
        """Play `audio` to the main output via sounddevice (shared mode)."""
        start_time = time.time()
        try:
            device_idx = getattr(self, "_main_sd_index", None)
            if device_idx is None:
                device_idx = self._find_sd_output_index(SOUND_DEVICE_OUT)
                self._main_sd_index = device_idx
            data = audio.astype(np.float32, copy=False)
            if data.ndim == 1:
                data = data.reshape(-1, 1)
            chunk_sz = 4800
            with sd.OutputStream(
                samplerate=sr,
                channels=data.shape[1],
                device=device_idx,
                dtype="float32",
            ) as stream:
                for i in range(0, len(data), chunk_sz):
                    if self._last_interrupt_time > start_time:
                        break
                    stream.write(data[i : i + chunk_sz])
        except Exception as e:
            print(f"[Audio] Playback error: {e}")

    def interrupt_main_device(self):
        self._last_interrupt_time = time.time()

    def play_fx(self, fx_name, blocking=False):
        fx_rel_path = get_fx_sound_list().get(fx_name, "")
        if fx_rel_path:
            if isinstance(fx_rel_path, list):  # complex sound with fx

                def play_fx_inner_schelude():
                    for fx in fx_rel_path:
                        if isinstance(fx, dict):
                            print("[FX PLAYER DEBUG DICT]", fx)
                            wait_time = fx.get("delay", 0.15)
                            blocking = fx.get("wait", False)
                            if fx.get("sequence"):
                                self.play_fx(fx["sequence"], blocking=blocking)
                            time.sleep(wait_time)
                        else:
                            fx_rel_snd = get_fx_sound_list().get(fx, "")
                            if fx_rel_snd:
                                if isinstance(fx_rel_snd, str):
                                    self.play_fx_inner(fx_rel_snd, True)
                                    time.sleep(0.15)

                if blocking:
                    play_fx_inner_schelude()
                else:
                    threading.Thread(target=play_fx_inner_schelude, daemon=True).start()
            else:
                self.play_fx_inner(fx_rel_path, True, blocking=True)

    def play_fx_inner(self, fx_name, path=False, blocking=False, fx_device=True):
        if path:
            fx_rel_path = fx_name
        else:
            fx_rel_path = get_fx_sound_list().get(fx_name, "")
        if fx_rel_path:
            sound_path = os.path.join(FX_AUDIO_DIR, fx_rel_path)
            if os.path.exists(sound_path):
                audio, sr = load_audiofile(sound_path)
                self.play_sound(audio, sr, fx_device=fx_device, blocking=blocking)

    async def music_loop(self):
        """Main music playback loop"""
        while self.playing_music:
            try:
                if self.playqueue.empty():
                    self.playlist_loop += 1
                    max_playlist_loop = 2  # -1 for forever
                    if (
                        max_playlist_loop != -1
                        and self.playlist_loop >= max_playlist_loop
                    ):
                        print(
                            f"[MUSIC] Playlist looped {self.playlist_loop} times, stopping"
                        )
                        self.stop_music()
                        break
                    await self.setup_music_playlist_async()
                    continue

                if not pygame.mixer.music.get_busy():
                    audiopath = await self.playqueue.get()
                    pygame.mixer.music.load(audiopath)
                    pygame.mixer.music.play(fade_ms=self.playlist_fade)
                    print(f"[MUSIC] Now playing: {audiopath}")
                    await asyncio.sleep(0.1)
                else:
                    if False:  # debug skip music
                        await asyncio.sleep(1)
                        self.skip_music()
                        await asyncio.sleep(1)
                    await asyncio.sleep(0.1)

            except Exception as e:
                print(f"[MUSIC] Error in music loop: {e}")
                traceback.print_exc()
                await asyncio.sleep(1)

    async def setup_music_playlist_async(self):
        """Setup playlist and fill queue"""
        filenames = glob.glob(os.path.join(REPO_RESOURCE_PATH, "music", "*.mp3"))
        self.playlist = list(filenames)
        for audiopath in self.playlist:
            await self.playqueue.put(audiopath)

    def setup_music_playlist(self):
        """Sync wrapper for playlist setup"""

        async def _setup():
            await self.setup_music_playlist_async()

        self.loop.run_until_complete(_setup())

    def _run_music_thread(self):
        """Run music loop in a separate thread for sync context"""
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self.setup_music_playlist_async())
        self.loop.run_until_complete(self.music_loop())

    async def music_cycle_start_async(self):
        """Async version of music start"""
        self.playing_music = True
        if self.music_task and not self.music_task.done():
            self.music_task.cancel()

        if self.playqueue.empty():
            await self.setup_music_playlist_async()

        self.music_task = self.loop.create_task(self.music_loop())

    def music_cycle_start(self):
        """Universal music start that works in both contexts"""
        self.playing_music = True

        if self._is_async_context:
            # We're in async context, return coroutine
            return self.music_cycle_start_async()

        # We're in sync context, use threading
        if self.music_thread and self.music_thread.is_alive():
            self.stop_music()
            self.music_thread.join()

        self.music_thread = threading.Thread(target=self._run_music_thread, daemon=True)
        self.music_thread.start()

    def stop_music(self):
        """Stop music and cleanup"""
        print("[MUSIC] Playlist stopped")
        self.playing_music = False
        self.skip_music()

        # Only join thread if we're not in it
        if self.music_thread and self.music_thread.is_alive():
            current_thread = threading.current_thread()
            if current_thread != self.music_thread:
                self.music_thread.join(timeout=1)

        if self.music_task:
            self.music_task.cancel()

    def skip_music(self):
        if pygame.mixer.music.get_busy():
            print("[MUSIC] Skipping music...")
            pygame.mixer.music.fadeout(self.playlist_fade)
            # time.sleep(0.4)
            # pygame.mixer.music.set_pos(10000)  # activates skip to next music.queue

    async def debug_skip_music_cycle_queue(self):
        await asyncio.sleep(5)
        pygame.mixer.music.set_pos(1000)
        pygame.mixer.music.set_endevent()
        await asyncio.sleep(5)
        pygame.mixer.music.set_pos(1000)
        await asyncio.sleep(5)

    async def play_with_lipsync(
        self,
        audio: np.ndarray,
        sample_rate: int = 48000,
        chunk_size: int = 2048,
    ) -> None:
        """Play audio while synchronizing lip movements."""
        if audio is None:
            return
        try:
            print("[PLAY] Starting audio with lip sync...")
            self.play_sound(audio, sample_rate)
            for i in range(0, len(audio), chunk_size):
                await asyncio.sleep(chunk_size / sample_rate)

            # sd.stop()

        except Exception as e:
            print(f"[PLAY ERR] Failed to play audio with lip sync: {e}")
            traceback.print_exc()
            # sd.stop()


def load_audiofile(path: str) -> Tuple[np.ndarray, int]:
    """Load audio from file."""
    audio, sr = librosa.load(path, sr=SOUND_DEVICE_SR)
    return audio, sr


def test_all_ap():
    ap = AudioProcessor()
    print("Your sound devices")
    ap.print_devices()
    print("[TEST] Playing test FX sounds...")
    # ap.play_fx_inner("warning")
    # ap.play_fx("starting")  # "internet")
    print("Blocking=true tests")
    ap.play_fx_inner("busy", fx_device=False, blocking=True)
    ap.play_fx_inner("busy", fx_device=False, blocking=True)
    print("FX device=true blocking tests")
    ap.play_fx_inner("busy", fx_device=True, blocking=True)
    ap.play_fx_inner("busy", fx_device=True, blocking=True)
    time.sleep(1)
    print("Blocking=false tests for fx dev then main dev")
    ap.play_fx_inner("busy", fx_device=True, blocking=False)
    time.sleep(0.05)
    ap.play_fx_inner("busy", fx_device=False, blocking=False)
    # interrupt test
    time.sleep(1)
    print("Interrupt test MAIN device. Playing sound")
    ap.play_fx_inner("busy", fx_device=False, blocking=False)
    time.sleep(0.1)
    print("Interrupting main device...")
    ap.interrupt_main_device()
    print("waiting 1 sec")
    time.sleep(1)
    print("Sequental FX test (LOUD!!!)")
    ap.play_fx("wiped_state")
    print("Test complete, waiting before exit... Use ctrl+c to stop earlier")
    time.sleep(100)


if __name__ == "__main__":
    # Standart test
    # test_all_ap()
    # MULTIPROCESSING TEST
    import multiprocessing as mp

    mp.set_start_method("spawn")
    print("[main process] Starting multiprocessing audio test")
    p = mp.Process(target=test_all_ap)
    p.start()
    # ap.play_fx("errored")
    # ap.music_cycle_start()
    print("[main process] Waiting")
    time.sleep(1000)
