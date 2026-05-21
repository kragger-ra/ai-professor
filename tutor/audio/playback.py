"""Vosk TTS playback with sentence-level prefetch and interrupt support.

Ported from:
  - src/tts/simple_tts_handler.py  (queue-drain + prefetch + watcher)
  - src/tts/audio_device.py        (slimmed AudioProcessor — main output only,
                                    no pygame / FX / music / lipsync)

Thread contract:
  * consumes sentence strings from tts_q (queue.Queue)
  * voices them via Vosk TTS server through sounddevice
  * stops within ~50 ms when interrupt is set; drains tts_q on stop
"""
from __future__ import annotations

import concurrent.futures
import io
import os
import queue
import threading
import time
import traceback
from typing import Optional, Tuple

import numpy as np
import soundcard as sc
import sounddevice as sd

from tutor.tts.vosk_client import (
    emotion_prosody,
    generate_silence,
    pause_for_sentence,
    split_sentences,
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

MAX_AUDIO_ALLOWED_TIME = 60      # seconds per TTS utterance; longer = dropped
INTER_ITEM_PAUSE_S = 0.35        # silence between consecutive queue items
QUEUE_OVERFLOW_LIMIT = 60        # sentences before overflow protection kicks in
QUEUE_OVERFLOW_KEEP = 50


# ---------------------------------------------------------------------------
# Slimmed AudioProcessor — main output + sounddevice index ONLY
# No pygame, no FX, no music, no lipsync.
# ---------------------------------------------------------------------------

class AudioProcessor:
    """Owns the main speaker and plays PCM audio via sounddevice (shared mode)."""

    def __init__(self) -> None:
        self.device_sr = SOUND_DEVICE_SR
        self._last_interrupt_time: float = 0.0
        self._setup_main_audio_devices()

    # ------------------------------------------------------------------
    # Device setup
    # ------------------------------------------------------------------

    def _find_speaker_by_name(self, target_name: str):
        speakers = sc.all_speakers()
        for s in speakers:
            if s.name == target_name:
                return s
        for s in speakers:
            if target_name in s.name:
                return s
        return None

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
        self.main_speaker = self._find_speaker_by_name(SOUND_DEVICE_OUT)
        if self.main_speaker is None:
            self.main_speaker = sc.default_speaker()
            log(
                "playback",
                f"main device '{SOUND_DEVICE_OUT}' not found, "
                f"using default: {self.main_speaker.name}",
            )
        else:
            log("playback", f"main device found: {self.main_speaker.name}")

        self._main_sd_index = self._find_sd_output_index(SOUND_DEVICE_OUT)
        if self._main_sd_index is None:
            log("playback", f"sounddevice fallback to system default for '{SOUND_DEVICE_OUT}'")
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

        target_sr = self.device_sr
        fixed_audio = librosa.resample(audio, orig_sr=sample_rate, target_sr=target_sr)

        if blocking:
            self._play_safe(self.main_speaker, fixed_audio, target_sr)
        else:
            threading.Thread(
                target=self._play_safe,
                args=(self.main_speaker, fixed_audio, target_sr),
                daemon=True,
            ).start()

    def _play_safe(self, speaker, audio: np.ndarray, sr: int) -> None:
        """Play audio to the main output via sounddevice in chunked shared mode.

        Checks _last_interrupt_time on every chunk (~100 ms) so an interrupt
        cuts playback within one chunk period.
        """
        start_time = time.time()
        try:
            device_idx = self._main_sd_index
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
                    stream.write(data[i: i + chunk_sz])
        except Exception as exc:
            log("playback", f"playback error: {exc}")

    def interrupt_main_device(self) -> None:
        """Signal _play_safe to break out of its chunk loop on next iteration."""
        self._last_interrupt_time = time.time()


# ---------------------------------------------------------------------------
# PlaybackThread
# ---------------------------------------------------------------------------

class PlaybackThread(threading.Thread):
    """Consumes answer sentences from tts_q and voices them via Vosk TTS.

    The interrupt Event (shared with CaptureThread) triggers two responses:
      1. A watcher thread calls audio_processor.interrupt_main_device() so
         _play_safe breaks within ~100 ms.
      2. The main drain loop detects interrupt.is_set() between sentences and
         drains the queue without voicing remaining items.
    """

    def __init__(self, tts_q: queue.Queue, interrupt: threading.Event) -> None:
        super().__init__(name="playback", daemon=True)
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._running = True
        self._speaking = False   # True while a sentence is being voiced
        self._audio_processor: Optional[AudioProcessor] = None

    def stop(self) -> None:
        self._running = False

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._audio_processor = AudioProcessor()

        while self._running:
            # Wait for a sentence; poll so we can honour stop() promptly.
            try:
                sentence = self._tts_q.get(timeout=0.3)
            except queue.Empty:
                continue

            if self._interrupt.is_set():
                self._drain()
                continue

            self._handle_vosk_queue_stream(sentence)

    # ------------------------------------------------------------------
    # Vosk streaming: sentence-by-sentence synthesis + prefetch
    # ------------------------------------------------------------------

    def _handle_vosk_queue_stream(self, first_sentence: str) -> None:
        """Drain tts_q with prefetch; stop within ~100 ms when interrupt fires.

        A watcher thread monitors the interrupt Event during playback; it calls
        interrupt_main_device() so _play_safe exits its chunk loop quickly.
        The main loop also checks the interrupt between sentences.
        """
        ap = self._audio_processor
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        prefetch_future: Optional[concurrent.futures.Future] = None
        interrupt_event = threading.Event()
        watcher_stop = threading.Event()
        played = 0
        total_t0 = time.perf_counter()

        self._speaking = True

        def _interrupt_watcher() -> None:
            while not watcher_stop.is_set():
                if self._interrupt.is_set():
                    ap.interrupt_main_device()
                    interrupt_event.set()
                    log("playback", "interrupt watcher fired")
                    return
                time.sleep(0.03)

        watcher = threading.Thread(target=_interrupt_watcher, daemon=True)
        watcher.start()

        # Re-assemble a temporary in-memory list starting with first_sentence,
        # then pull more from the queue up to QUEUE_OVERFLOW_LIMIT.
        # We use a local list so we can apply overflow trimming without touching
        # the real queue.
        pending = [{"text": first_sentence, "emotion": "neutral"}]

        # Drain as many items as are immediately available (non-blocking)
        while True:
            try:
                item = self._tts_q.get_nowait()
                pending.append(item if isinstance(item, dict) else {"text": item, "emotion": "neutral"})
            except queue.Empty:
                break

        # Overflow protection
        if len(pending) > QUEUE_OVERFLOW_LIMIT:
            overflow = len(pending) - QUEUE_OVERFLOW_KEEP
            pending = pending[overflow:]
            log("playback", f"queue overflow — dropped {overflow} items")

        try:
            for tts_item in pending:
                if interrupt_event.is_set():
                    break

                # tts_q items may be plain str or dict
                if isinstance(tts_item, str):
                    text = tts_item.strip()
                    emotion = "neutral"
                else:
                    text = tts_item.get("text", "").strip()
                    emotion = tts_item.get("emotion", "neutral") or "neutral"

                if not text:
                    continue

                _, pause_mul = emotion_prosody(emotion)
                sentences = split_sentences(text)

                for si, sentence in enumerate(sentences):
                    if interrupt_event.is_set():
                        ap.interrupt_main_device()
                        break

                    # Get synthesized audio: from prefetch or synthesize now
                    if prefetch_future is not None:
                        try:
                            audio, sr = prefetch_future.result()
                        except Exception as exc:
                            log("playback", f"prefetch error: {exc}")
                            audio, sr = vosk_tts_sentence(sentence, emotion)
                        prefetch_future = None
                    else:
                        audio, sr = vosk_tts_sentence(sentence, emotion)

                    if interrupt_event.is_set():
                        break

                    if len(audio) == 0:
                        log("playback", f"vosk returned empty WAV for: '{sentence[:80]}'")
                        continue

                    audio_dur = len(audio) / sr
                    if audio_dur > MAX_AUDIO_ALLOWED_TIME:
                        log("playback", f"drop: {audio_dur:.1f}s > {MAX_AUDIO_ALLOWED_TIME}s")
                        continue

                    _wc = max(1, len(sentence.split()))
                    if audio_dur / _wc < 0.10:
                        log(
                            "playback",
                            f"anomaly-short: {audio_dur:.1f}s for {_wc} words "
                            f"({audio_dur / _wc:.2f}s/word): '{sentence[:80]}'",
                        )

                    # Prefetch next sentence while this one plays
                    next_sentence = None
                    next_emotion = emotion
                    if si + 1 < len(sentences):
                        next_sentence = sentences[si + 1]
                    elif pending:
                        # Peek at the next pending item (already in local list)
                        next_idx = pending.index(tts_item) + 1 if tts_item in pending else None
                        if next_idx is not None and next_idx < len(pending):
                            nxt = pending[next_idx]
                            nxt_text = (nxt if isinstance(nxt, str) else nxt.get("text", "")).strip()
                            nxt_emotion = "neutral" if isinstance(nxt, str) else (nxt.get("emotion") or "neutral")
                            if nxt_text:
                                nxt_sents = split_sentences(nxt_text)
                                if nxt_sents:
                                    next_sentence = nxt_sents[0]
                                    next_emotion = nxt_emotion

                    if next_sentence and prefetch_future is None and not interrupt_event.is_set():
                        prefetch_future = executor.submit(
                            vosk_tts_sentence, next_sentence, next_emotion
                        )

                    # Blocking play — watcher will fire interrupt_main_device()
                    # mid-playback if the interrupt Event is set.
                    ap.play_sound(audio, sr, blocking=True)
                    played += 1

                    if interrupt_event.is_set():
                        break

                    # Inter-sentence pause
                    if si + 1 < len(sentences):
                        base_pause = pause_for_sentence(sentence)
                        pause_audio, pause_sr = generate_silence(base_pause * pause_mul)
                        ap.play_sound(pause_audio, pause_sr, blocking=True)
                    elif pending.index(tts_item) + 1 < len(pending):
                        pause_audio, pause_sr = generate_silence(
                            INTER_ITEM_PAUSE_S * pause_mul
                        )
                        ap.play_sound(pause_audio, pause_sr, blocking=True)

                if interrupt_event.is_set():
                    break

        except Exception as exc:
            log("playback", f"stream error: {exc}")
            traceback.print_exc()
        finally:
            watcher_stop.set()
            if prefetch_future is not None:
                prefetch_future.cancel()
            self._speaking = False
            executor.shutdown(wait=False)
            elapsed_ms = (time.perf_counter() - total_t0) * 1000
            log(
                "playback",
                f"drained: {played} sentences, {elapsed_ms:.0f}ms"
                + (" [INTERRUPTED]" if interrupt_event.is_set() else ""),
            )

    # ------------------------------------------------------------------
    # Queue drain on interrupt
    # ------------------------------------------------------------------

    def _drain(self) -> None:
        """Drop all queued sentences after an interrupt."""
        dropped = 0
        while True:
            try:
                self._tts_q.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            log("playback", f"dropped {dropped} queued sentence(s)")
