"""Vosk TTS playback — voices Answer objects, resumable.

Ported from:
  - src/tts/simple_tts_handler.py  (queue-drain + prefetch + watcher)
  - src/tts/audio_device.py        (slimmed AudioProcessor — main output only,
                                    no pygame / FX / music / lipsync)

PHASE 3: the queue carries `Answer` objects, not loose strings. Playback
voices `answer.sentences[answer.voiced_index:]`, advancing `voiced_index`
only after a sentence is voiced IN FULL. An interrupt stops mid-sentence
without advancing — so a later resume re-voices that sentence for context
and continues, with no LLM call.
"""
from __future__ import annotations

import concurrent.futures
import io
import os
import queue
import threading
import time
import traceback
from typing import Optional

import numpy as np
import sounddevice as sd

from tutor.audio.fillers import FillerCue
from tutor.audio.postfx import make_postfx_from_env
from tutor.tts.vosk_client import (
    generate_silence,
    pause_for_sentence,
    vosk_tts_sentence,
)
from tutor.util import log

# ---------------------------------------------------------------------------
# Playback constants
# ---------------------------------------------------------------------------
SOUND_DEVICE_OUT = os.getenv(
    "SOUND_DEVICE_OUT", "CABLE Output (VB-Audio Virtual Cable)"
)
SOUND_DEVICE_SR = int(os.getenv("SOUND_DEVICE_SR", "48000"))


# ---------------------------------------------------------------------------
# Slimmed AudioProcessor — main output + sounddevice index ONLY
# No pygame, no FX, no music, no lipsync.
# ---------------------------------------------------------------------------

class AudioProcessor:
    """Owns the main speaker and plays PCM audio via sounddevice (shared mode)."""

    def __init__(self, device_name: Optional[str] = None) -> None:
        self.device_sr = SOUND_DEVICE_SR
        self._last_interrupt_time: float = 0.0
        # Output device — explicit name takes priority over env default. The
        # mode toggle in the board UI feeds the name in via PlaybackThread.
        self._device_name = (
            device_name if device_name is not None else SOUND_DEVICE_OUT
        )
        # Optional DSP post-processing chain (Pedalboard + pyloudnorm).
        # None unless env TTS_POSTFX=on AND pedalboard is importable.
        self._postfx = make_postfx_from_env()
        if self._postfx is not None:
            log("playback", "TTS post-FX enabled (TTS_POSTFX=on)")
        self._setup_main_audio_devices()

    # ------------------------------------------------------------------
    # Device setup
    # ------------------------------------------------------------------

    @staticmethod
    def _find_sd_output_index(name: str) -> Optional[int]:
        """Find a sounddevice output index matching name (substring, case-insensitive).

        Prefers MME (hostapi 0) and DirectSound (hostapi 1) over WASAPI to
        avoid exclusive-mode capture that would block other apps.
        """
        if not name:
            return None
        lower = name.lower()
        try:
            devices = sd.query_devices()
        except Exception:
            return None
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

    def _setup_main_audio_devices(self) -> None:
        # Playback goes entirely through sounddevice (PortAudio) — it manages
        # its own COM init, so it works inside a worker thread. The soundcard
        # library is intentionally NOT used (its COM enumeration crashes in a
        # bare thread with CO_E_NOTINITIALIZED).
        self._main_sd_index = self._find_sd_output_index(self._device_name)
        if self._main_sd_index is None:
            log("playback", f"sounddevice fallback to system default for '{self._device_name}'")
        else:
            try:
                info = sd.query_devices(self._main_sd_index)
                api = sd.query_hostapis(info["hostapi"])["name"]
                log(
                    "playback",
                    f"sounddevice main idx={self._main_sd_index} "
                    f"name='{info['name']}' api={api}",
                )
            except Exception as exc:
                log("playback", f"sounddevice info read failed: {exc}")

    # ------------------------------------------------------------------
    # Playback
    # ------------------------------------------------------------------

    @staticmethod
    def save_audio_to_buffer(data: np.ndarray, sr: int) -> io.BytesIO:
        """Write PCM array to an in-memory WAV buffer."""
        import scipy.io.wavfile as wf
        byte_io = io.BytesIO()
        wf.write(byte_io, sr, data)
        return byte_io

    def play_sound(
        self,
        audio: np.ndarray,
        sample_rate: int = 48000,
        blocking: bool = False,
    ) -> None:
        """Resample to device SR, then play via sounddevice (shared mode)."""
        import librosa

        # Apply DSP post-processing at the source sample rate — the EQ /
        # de-esser need the original treble content, which gets blurred by
        # an up-resample. PostFX is a no-op when TTS_POSTFX is not enabled.
        if self._postfx is not None:
            audio = self._postfx(audio, sample_rate)

        target_sr = self.device_sr
        fixed_audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_sr)

        if blocking:
            self._play_safe(fixed_audio, target_sr)
        else:
            threading.Thread(
                target=self._play_safe,
                args=(fixed_audio, target_sr),
                daemon=True,
            ).start()

    def _play_safe(self, audio: np.ndarray, sr: int) -> None:
        """Play audio to the main output via sounddevice in chunked shared mode.

        Checks _last_interrupt_time on every chunk (~100 ms) so an interrupt
        cuts playback within one chunk period.
        """
        start_time = time.time()
        try:
            device_idx = self._main_sd_index
            if device_idx is None:
                device_idx = self._find_sd_output_index(self._device_name)
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
                    stream.write(data[i: i + chunk_sz])
        except Exception as exc:
            log("playback", f"playback error: {exc}")

    def interrupt_main_device(self) -> None:
        """Signal _play_safe to break out of its chunk loop on next iteration."""
        self._last_interrupt_time = time.time()

    def swap_output(self, device_name: str) -> None:
        """Hot-swap the playback output device. Takes effect from the NEXT
        ``_play_safe`` call — the currently-voicing chunk finishes on the
        old device. Safe to call from any thread."""
        self._device_name = device_name
        self._main_sd_index = self._find_sd_output_index(device_name)
        log("playback",
            f"output -> '{device_name}' (idx={self._main_sd_index})")


# ---------------------------------------------------------------------------
# PlaybackThread
# ---------------------------------------------------------------------------

class PlaybackThread(threading.Thread):
    """Voices `Answer` objects from tts_q — sentence by sentence, resumable.

    A watcher thread calls AudioProcessor.interrupt_main_device() the instant
    the shared interrupt Event is set, so playback stops within ~100 ms. The
    cut sentence is NOT marked voiced, so a resume re-voices it for context.
    """

    def __init__(self, tts_q: queue.Queue, interrupt: threading.Event,
                 output_device: Optional[str] = None) -> None:
        super().__init__(name="playback", daemon=True)
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._running = True
        self._output_device = output_device
        # Set while a sentence is being voiced — CaptureThread reads this as
        # its anti-echo gate (raise the VAD threshold while the tutor talks).
        self.speaking = threading.Event()
        # Toggled by the board sidecar via commands.jsonl: while set, drop
        # any Answer pulled off tts_q without voicing it.
        self.muted = threading.Event()
        self._audio_processor: Optional[AudioProcessor] = None

    def stop(self) -> None:
        self._running = False

    def swap_output(self, device_name: str) -> None:
        """Forward a hot-swap request to the AudioProcessor once it exists.
        Before the playback thread has started its run() loop the request is
        cached and applied at AudioProcessor construction."""
        self._output_device = device_name
        if self._audio_processor is not None:
            self._audio_processor.swap_output(device_name)

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._audio_processor = AudioProcessor(device_name=self._output_device)
        while self._running:
            try:
                answer = self._tts_q.get(timeout=0.3)
            except queue.Empty:
                continue
            # A stale answer queued before an interrupt — a fresh turn has
            # already superseded it; drop it.
            if self._interrupt.is_set():
                continue
            if self.muted.is_set():
                # TTS muted from the board UI — mark the answer fully voiced
                # so resume logic does not later try to read it aloud, then
                # silently drop it. Filler cues are dropped silently — no
                # voiced_index to advance.
                if isinstance(answer, FillerCue):
                    continue
                try:
                    answer.mark_voiced(len(answer.sentences))
                except Exception:
                    pass
                continue
            if isinstance(answer, FillerCue):
                self._play_filler(answer)
                continue
            self._voice_answer(answer)

    # ------------------------------------------------------------------
    # Voicing a filler cue
    # ------------------------------------------------------------------

    def _play_filler(self, cue: FillerCue) -> None:
        """Play a short pre-rendered cue. Interruptible like any TTS chunk."""
        ap = self._audio_processor
        self.speaking.set()
        try:
            log("playback", f"filler: {cue.text}")
            ap.play_sound(cue.audio, cue.sr, blocking=True)
        except Exception as exc:
            log("playback", f"filler skipped ({type(exc).__name__}: {exc})")
        finally:
            self.speaking.clear()

    # ------------------------------------------------------------------
    # Voicing one Answer
    # ------------------------------------------------------------------

    def _voice_answer(self, answer) -> None:
        """Voice answer.sentences[voiced_index:] with next-sentence prefetch."""
        ap = self._audio_processor
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        prefetch: Optional[concurrent.futures.Future] = None
        prefetch_idx = -1
        watcher_stop = threading.Event()
        voiced = 0
        t0 = time.perf_counter()
        self.speaking.set()

        def _watch() -> None:
            while not watcher_stop.is_set():
                if self._interrupt.is_set():
                    ap.interrupt_main_device()
                    return
                time.sleep(0.03)

        watcher = threading.Thread(target=_watch, daemon=True)
        watcher.start()

        try:
            while self._running and not self._interrupt.is_set():
                idx = answer.voiced_index
                if idx < len(answer.sentences):
                    sentence = answer.sentences[idx]
                    # Synthesize + play one sentence. A failure here (Vosk
                    # down, device busy, ...) must NOT stick the whole answer:
                    # log it, skip the sentence, and still advance voiced_index
                    # so the answer can complete and downstream state stays sane.
                    try:
                        if prefetch is not None and prefetch_idx == idx:
                            audio, sr = prefetch.result()
                        else:
                            audio, sr = vosk_tts_sentence(sentence, "neutral")
                        prefetch = None
                        if self._interrupt.is_set():
                            break
                        # Prefetch the next sentence while this one plays.
                        if idx + 1 < len(answer.sentences):
                            prefetch_idx = idx + 1
                            prefetch = executor.submit(
                                vosk_tts_sentence,
                                answer.sentences[idx + 1], "neutral",
                            )
                        if len(audio) > 0:
                            log("playback", f"> {sentence[:70]}")
                            ap.play_sound(audio, sr, blocking=True)
                    except Exception as exc:
                        log("playback",
                            f"sentence skipped ({type(exc).__name__}: {exc})")
                        prefetch = None
                    if self._interrupt.is_set():
                        break          # cut mid-sentence — do NOT advance
                    answer.mark_voiced(1)
                    voiced += 1
                    # Short pause before the next sentence.
                    if answer.voiced_index < len(answer.sentences) or answer.generating:
                        try:
                            ps, psr = generate_silence(pause_for_sentence(sentence))
                            ap.play_sound(ps, psr, blocking=True)
                        except Exception:
                            pass
                elif answer.generating:
                    time.sleep(0.05)    # caught up — wait for the generator
                else:
                    break               # fully voiced
        except Exception as exc:
            log("playback", f"voice error: {exc}")
            traceback.print_exc()
        finally:
            watcher_stop.set()
            if prefetch is not None:
                prefetch.cancel()
            self.speaking.clear()
            executor.shutdown(wait=False)
            tag = " [INTERRUPTED]" if self._interrupt.is_set() else ""
            log("playback",
                f"voiced {voiced} sentence(s), "
                f"{(time.perf_counter() - t0) * 1000:.0f}ms{tag}")
