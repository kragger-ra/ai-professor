"""Per-process continuous WAV recorder for volunteer sessions.

When SESSION_RECORD=true, every subprocess (mic STT, TTS) appends raw PCM
into its own file inside ``data/sessions/{timestamp}/``:

    mic.wav  — 16 kHz mono int16 stream from the microphone
    tts.wav  — variable-rate stream as Vosk TTS played it back

These artefacts are the source of truth for post-session grounding analysis
and dispute resolution. Disabled by default — no I/O when the env var is off.

Usage (per process):

    rec = get_recorder("mic")
    rec.write(pcm_int16_chunk, sample_rate=16000)
    rec.close()                                   # on shutdown

The first write fixes the sample rate; later writes with a different rate
get resampled? No — they just open a *new* file (``tts_22050.wav``) so the
raw stream stays lossless and we keep one file per (channel, rate) pair.
"""

from __future__ import annotations

import os
import threading
import wave
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional

import numpy as np


_ENABLED = os.getenv("SESSION_RECORD", "false").lower() in ("true", "1", "yes")


def _session_dir() -> Optional[Path]:
    """Return the active session directory, creating it on first call.

    Lives in env ``SESSION_DIR`` so all subprocesses share it. If unset and
    recording is enabled, a fresh ``data/sessions/{timestamp}/`` is created
    and the env var populated for child processes spawned afterwards.
    """
    if not _ENABLED:
        return None
    existing = os.getenv("SESSION_DIR")
    if existing:
        p = Path(existing)
        p.mkdir(parents=True, exist_ok=True)
        return p
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    p = Path("data") / "sessions" / stamp
    p.mkdir(parents=True, exist_ok=True)
    os.environ["SESSION_DIR"] = str(p)
    return p


class _Recorder:
    """A tiny per-channel WAV appender.

    Files are opened lazily on the first write so a process that never
    receives audio leaves no empty file behind.
    """

    def __init__(self, channel: str):
        self.channel = channel
        self._lock = threading.Lock()
        # Multiple files keyed by sample_rate so we never resample on hot path
        self._files: Dict[int, wave.Wave_write] = {}
        # Sample-rates we already tried and failed to open — skip silently next time
        self._failed_rates: set[int] = set()

    def write(self, pcm: np.ndarray, sample_rate: int) -> None:
        """Append a chunk of int16 PCM. Float arrays are clipped + cast."""
        if not _ENABLED:
            return
        if pcm is None or len(pcm) == 0:
            return
        if pcm.dtype != np.int16:
            # Common case: synthesised audio comes as float32 in [-1, 1].
            pcm = np.clip(pcm, -1.0, 1.0)
            pcm = (pcm * 32767.0).astype(np.int16)
        with self._lock:
            if sample_rate in self._failed_rates:
                return
            wf = self._files.get(sample_rate)
            if wf is None:
                wf = self._open_file(sample_rate)
                if wf is None:
                    # Mark this rate as failed so we don't retry every 100 ms
                    self._failed_rates.add(sample_rate)
                    return
                self._files[sample_rate] = wf
            try:
                wf.writeframes(pcm.tobytes())
            except Exception as e:
                print(f"[SESSION-REC] write failed ({self.channel}@{sample_rate}): {e}")

    def _open_file(self, sample_rate: int) -> Optional[wave.Wave_write]:
        d = _session_dir()
        if d is None:
            return None
        suffix = "" if sample_rate == 16000 and self.channel == "mic" else f"_{sample_rate}"
        path = d / f"{self.channel}{suffix}.wav"
        try:
            wf = wave.open(str(path), "wb")
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(sample_rate)
            print(f"[SESSION-REC] writing -> {path}")
            return wf
        except Exception as e:
            print(f"[SESSION-REC] open failed for {path}: {e}")
            return None

    def close(self) -> None:
        with self._lock:
            for wf in self._files.values():
                try:
                    wf.close()
                except Exception:
                    pass
            self._files.clear()


_RECORDERS: Dict[str, _Recorder] = {}
_RECORDERS_LOCK = threading.Lock()


def get_recorder(channel: str) -> _Recorder:
    """Return (or create) the per-process recorder for the given channel."""
    with _RECORDERS_LOCK:
        rec = _RECORDERS.get(channel)
        if rec is None:
            rec = _Recorder(channel)
            _RECORDERS[channel] = rec
        return rec


def is_enabled() -> bool:
    return _ENABLED
