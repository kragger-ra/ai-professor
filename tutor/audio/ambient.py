"""Quiet ambient background sound — optional.

PHASE 6 — a soft room-tone loop under the conversation plus a short
cat-purr burst when the tutor comes online. Both intentionally quiet.

Entirely optional and fail-safe: set AMBIENT_SOUND=off to mute it, and ANY
failure (missing file, decode error, device busy, no third stream slot)
silently disables ambient — the tutor itself is never affected.

The OS mixes these streams under the professor's TTS, which plays from
playback.py on its own output stream.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Optional

import numpy as np
import sounddevice as sd

from tutor.util import log

_COMPONENT = "ambient"

# tutor/audio/ambient.py -> parents[0]=audio, [1]=tutor, [2]=repo_root
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_AUDIO_DIR: Path = _REPO_ROOT / "resources" / "Audio"
_ROOM_FILE: Path = _AUDIO_DIR / "ambient_room.mp3"
_CAT_FILE: Path = _AUDIO_DIR / "ambient_cat_purr.mp3"

_PLAYBACK_SR = 48000          # device sample rate (matches playback.py)
_ROOM_GAIN = 0.13             # very quiet — a background room tone
_CAT_GAIN = 0.16              # quiet — a short calming purr
_CAT_SECONDS = 4.0            # length of one purr burst (3-5s)
_CHUNK = 4800                 # ~100 ms write chunks


def _enabled() -> bool:
    return os.getenv("AMBIENT_SOUND", "on").strip().lower() not in (
        "off", "false", "0", "no",
    )


def _load(path: Path, gain: float) -> Optional[np.ndarray]:
    """Decode an audio file to a gained mono float32 column at _PLAYBACK_SR.
    Returns None on any failure (ambient is optional)."""
    try:
        import librosa
        y, _ = librosa.load(str(path), sr=_PLAYBACK_SR, mono=True)
        return (y.astype(np.float32) * gain).reshape(-1, 1)
    except Exception as exc:
        log(_COMPONENT,
            f"could not load {path.name}: {type(exc).__name__}: {exc}")
        return None


class AmbientPlayer:
    """Plays a quiet room-tone loop and short cat-purr bursts, mixed by the
    OS under the professor's voice. Optional and fail-safe."""

    def __init__(self, device_name: str = "") -> None:
        self._device: Optional[int] = None
        self._room: Optional[np.ndarray] = None
        self._cat: Optional[np.ndarray] = None
        self._stop = threading.Event()
        self._room_thread: Optional[threading.Thread] = None
        self.active = False

        if not _enabled():
            log(_COMPONENT, "ambient sound disabled (AMBIENT_SOUND=off)")
            return
        # Resolve the same output device the professor speaks through, so the
        # ambient mixes under the voice rather than landing on another device.
        try:
            from tutor.audio.playback import AudioProcessor
            self._device = AudioProcessor._find_sd_output_index(device_name)
        except Exception:
            self._device = None
        self._room = _load(_ROOM_FILE, _ROOM_GAIN)
        cat = _load(_CAT_FILE, _CAT_GAIN)
        if cat is not None:
            self._cat = cat[: int(_CAT_SECONDS * _PLAYBACK_SR)]
        self.active = self._room is not None or self._cat is not None
        if self.active:
            log(_COMPONENT, "ambient ready")

    # ------------------------------------------------------------------
    # Room tone — a continuous quiet loop
    # ------------------------------------------------------------------

    def start_room_loop(self) -> None:
        """Begin looping the room tone on a daemon thread."""
        if self._room is None or self._room_thread is not None:
            return
        self._room_thread = threading.Thread(
            target=self._loop_room, daemon=True, name="ambient-room",
        )
        self._room_thread.start()

    def _loop_room(self) -> None:
        data = self._room
        try:
            with sd.OutputStream(samplerate=_PLAYBACK_SR, channels=1,
                                 device=self._device, dtype="float32") as stream:
                log(_COMPONENT, "room tone loop started")
                while not self._stop.is_set():
                    for i in range(0, len(data), _CHUNK):
                        if self._stop.is_set():
                            break
                        stream.write(data[i:i + _CHUNK])
        except Exception as exc:
            log(_COMPONENT,
                f"room loop stopped: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # Cat purr — one short quiet burst
    # ------------------------------------------------------------------

    def play_cat_purr(self) -> None:
        """Play one short quiet purr burst (non-blocking, fail-safe)."""
        if self._cat is None or self._stop.is_set():
            return
        threading.Thread(target=self._play_cat, daemon=True,
                         name="ambient-cat").start()

    def _play_cat(self) -> None:
        try:
            with sd.OutputStream(samplerate=_PLAYBACK_SR, channels=1,
                                 device=self._device, dtype="float32") as stream:
                stream.write(self._cat)
        except Exception as exc:
            log(_COMPONENT,
                f"cat purr skipped: {type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Stop the room loop (called on shutdown)."""
        self._stop.set()
