"""Smoke test for tutor.audio.postfx.

Synthesizes a short test signal (chirp + sibilance burst), pushes it
through the DSP chain, prints latency and spectral fingerprint deltas
so we can sanity-check the chain is doing roughly what it claims.

Run: python -m tools.smoke_postfx
"""
from __future__ import annotations

import os
import time

import numpy as np

os.environ["TTS_POSTFX"] = "on"  # force-enable for this smoke

from tutor.audio.postfx import PostFX


def main() -> None:
    fx = PostFX()
    print(f"enabled: {fx.enabled}")
    if not fx.enabled:
        print("ABORT: PostFX did not initialize. Is pedalboard installed?")
        return

    sr = 24000
    duration_s = 1.0
    n = int(sr * duration_s)
    t = np.arange(n) / sr

    # 200 Hz sine (low honk band) + 3 kHz tone (presence) + 7 kHz tone
    # (sibilance region) — mimics rough TTS spectrum.
    audio = (
        0.4 * np.sin(2 * np.pi * 200 * t)
        + 0.3 * np.sin(2 * np.pi * 3000 * t)
        + 0.3 * np.sin(2 * np.pi * 7000 * t)
    ).astype(np.float32)

    # Latency: 5 passes, take median.
    latencies = []
    out = None
    for _ in range(5):
        t0 = time.perf_counter()
        out = fx(audio, sr)
        latencies.append((time.perf_counter() - t0) * 1000)
    median_ms = sorted(latencies)[len(latencies) // 2]
    print(f"latency: median {median_ms:.1f} ms per {duration_s*1000:.0f} ms chunk")
    print(f"latencies (ms): {[round(x, 1) for x in latencies]}")
    print(f"in  shape={audio.shape} dtype={audio.dtype}")
    print(f"out shape={out.shape} dtype={out.dtype}")
    print(f"in  peak={np.max(np.abs(audio)):.3f} rms={np.sqrt(np.mean(audio**2)):.3f}")
    print(f"out peak={np.max(np.abs(out)):.3f} rms={np.sqrt(np.mean(out**2)):.3f}")

    # Spectral fingerprint: power in 3 bands, in/out comparison.
    def band_power(x: np.ndarray, sr: int, lo: float, hi: float) -> float:
        f = np.fft.rfftfreq(len(x), 1 / sr)
        spec = np.abs(np.fft.rfft(x)) ** 2
        mask = (f >= lo) & (f < hi)
        return float(spec[mask].sum())

    bands = [(50, 400), (400, 2000), (2000, 5000), (5000, 9000), (9000, 12000)]
    print("band power in -> out (dB delta):")
    for lo, hi in bands:
        bin_in = band_power(audio, sr, lo, hi)
        bin_out = band_power(out, sr, lo, hi)
        if bin_in > 0 and bin_out > 0:
            db_delta = 10 * np.log10(bin_out / bin_in)
        else:
            db_delta = float("nan")
        print(f"  {lo:>5}-{hi:>5} Hz: {db_delta:+5.2f} dB")

    # Short clip — should bypass LUFS, no errors expected.
    short = audio[: sr // 10]  # 100 ms
    short_out = fx(short, sr)
    print(f"short clip 100ms: in shape={short.shape} -> out shape={short_out.shape}")

    print("OK")


if __name__ == "__main__":
    main()
