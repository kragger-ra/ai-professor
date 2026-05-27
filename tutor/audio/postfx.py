"""TTS post-processing — DSP chain to make Vosk output sound less synthetic.

Vosk-TTS uses a HiFiGAN-style vocoder; the artefacts that read as
"synthetic" to listeners are: sibilant harshness on /с/ /ш/ /щ/ around
6-9kHz, a slight midrange honk around 200-400Hz, dry sound with no room
ambience, and uneven loudness between sentences.

This chain applies a light Pedalboard graph (Spotify's MIT-licensed audio
plugin host) plus pyloudnorm normalization. All five effects are deliberately
mild — heavy reverb/compression would sound worse than the raw Vosk output.

Enable with env ``TTS_POSTFX=on``. Disabled by default — the chain is the
first new audio path we ship; A/B by toggling the flag.
"""
from __future__ import annotations

import os
from typing import Optional

import numpy as np

from tutor.util import log

try:
    from pedalboard import (
        Compressor,
        HighShelfFilter,
        LowShelfFilter,
        Pedalboard,
        PeakFilter,
        Reverb,
    )
    _PEDALBOARD_AVAILABLE = True
except ImportError:
    _PEDALBOARD_AVAILABLE = False

try:
    import pyloudnorm as pyln
    _PYLOUDNORM_AVAILABLE = True
except ImportError:
    _PYLOUDNORM_AVAILABLE = False


def _build_default_board() -> "Pedalboard":
    """Standard chain — mild EQ + de-essing peak + comp + small room reverb.

    Numbers chosen to sit just under perception: each effect alone is hard
    to spot, but together they de-harsh sibilants, fatten the mid, even
    the level, and seat the voice in a small room.
    """
    return Pedalboard([
        # Tame the slight 250 Hz honk that HiFiGAN-class vocoders show on
        # Russian male/neutral voices.
        LowShelfFilter(cutoff_frequency_hz=250, gain_db=-2.5, q=0.7),
        # De-esser surrogate: narrow peak cut where Vosk's sibilance lives.
        # A true sidechain de-esser would be ideal but Pedalboard has no
        # dynamic EQ plugin — a static cut at -4dB is the simple choice and
        # matches what production speech-EQ presets do.
        PeakFilter(cutoff_frequency_hz=7000, gain_db=-4.0, q=2.5),
        # Roll off the synthetic top end past 9 kHz without dulling speech.
        HighShelfFilter(cutoff_frequency_hz=9000, gain_db=-2.0, q=0.7),
        # Glue + level the dynamics. 2:1 below -18dBFS — gentle, no pumping.
        Compressor(threshold_db=-18.0, ratio=2.0, attack_ms=5.0, release_ms=50.0),
        # Small room. ~8% wet is the threshold where a dry voice starts to
        # feel "in the same room as the listener" without sounding reverb-y.
        Reverb(
            room_size=0.25, damping=0.5,
            wet_level=0.08, dry_level=0.92, width=0.6, freeze_mode=0.0,
        ),
    ])


class PostFX:
    """Pedalboard-based DSP chain + LUFS normalization.

    Construct one per AudioProcessor; call ``__call__(audio, sr)`` per
    chunk. Falls back to identity passthrough if Pedalboard is missing
    or audio is too short for LUFS measurement.
    """

    def __init__(self, target_lufs: float = -16.0) -> None:
        self._target_lufs = target_lufs
        self._board: Optional[Pedalboard] = None
        self._meter: Optional[pyln.Meter] = None
        self._meter_sr: int = 0
        if not _PEDALBOARD_AVAILABLE:
            log("postfx", "pedalboard not installed — DSP chain disabled")
            return
        try:
            self._board = _build_default_board()
            log("postfx", "DSP chain ready: LowShelf -> PeakCut(7k) -> "
                          "HighShelf -> Comp -> Reverb -> LUFS")
        except Exception as exc:
            log("postfx", f"chain build failed: {type(exc).__name__}: {exc}")
            self._board = None

    @property
    def enabled(self) -> bool:
        return self._board is not None

    def __call__(self, audio: np.ndarray, sr: int) -> np.ndarray:
        if self._board is None:
            return audio
        # Pedalboard wants float32 in [-1, 1]; Vosk usually returns int16
        # PCM or float32 already. Normalize to float32 either way.
        original_dtype = audio.dtype
        if np.issubdtype(original_dtype, np.integer):
            iinfo = np.iinfo(original_dtype)
            scale = max(abs(iinfo.min), iinfo.max)
            buf = (audio.astype(np.float32) / scale)
        else:
            buf = audio.astype(np.float32, copy=False)
        if buf.ndim == 1:
            mono = buf
        else:
            # Mono input is expected from Vosk; if stereo arrives, average
            # to mono before processing, then return mono — playback up-
            # mixes itself if needed.
            mono = buf.mean(axis=1)
        try:
            fx = self._board(mono, sample_rate=sr)
        except Exception as exc:
            log("postfx", f"process failed ({type(exc).__name__}: {exc}) — "
                          f"passthrough this chunk")
            return audio
        # LUFS normalization — only for chunks long enough to measure (>400ms).
        # Short fillers ("Так...") skip normalization; their level matches Vosk
        # native output, which is what we want anyway.
        if _PYLOUDNORM_AVAILABLE and len(fx) / sr >= 0.5:
            if self._meter is None or self._meter_sr != sr:
                self._meter = pyln.Meter(sr)
                self._meter_sr = sr
            try:
                loudness = self._meter.integrated_loudness(fx)
                if loudness > -70.0:  # pyloudnorm returns -inf-ish for silence
                    fx = pyln.normalize.loudness(fx, loudness, self._target_lufs)
            except Exception as exc:
                log("postfx", f"LUFS skip ({type(exc).__name__}: {exc})")
        # Clip-guard: peak normalize if the chain pushed past full-scale.
        peak = float(np.max(np.abs(fx)))
        if peak > 0.99:
            fx = fx * (0.99 / peak)
        # Cast back to source dtype so downstream resample / playback paths
        # see the same shape they used to. Int dtype gets scaled back up.
        if np.issubdtype(original_dtype, np.integer):
            iinfo = np.iinfo(original_dtype)
            scale = max(abs(iinfo.min), iinfo.max)
            return (fx * scale).astype(original_dtype, copy=False)
        return fx.astype(original_dtype, copy=False)


def make_postfx_from_env() -> Optional[PostFX]:
    """Build a PostFX instance iff TTS_POSTFX=on, else return None."""
    if os.getenv("TTS_POSTFX", "off").strip().lower() not in ("on", "1", "true", "yes"):
        return None
    fx = PostFX()
    if not fx.enabled:
        return None
    return fx
