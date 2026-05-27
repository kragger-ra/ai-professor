"""A/B smoke for postfx using real Vosk TTS output.

Requires the Vosk TTS server to be running (start_tutor_v2.bat brings it
up before the agent). Outputs two WAV files in the repo root:
  postfx_dry.wav   — raw Vosk synthesis
  postfx_wet.wav   — same audio through the DSP chain

Listen, A/B, decide. To disable post-FX globally, leave TTS_POSTFX unset.

Run: python -m tools.smoke_postfx_vosk
"""
from __future__ import annotations

import os
import sys
import time

import numpy as np
import scipy.io.wavfile as wf

os.environ["TTS_POSTFX"] = "on"

SAMPLE_SENTENCES = [
    "Привет. Я профессор. Сейчас расскажу о работе с трансформерами.",
    "Шипящие звуки в речи: шёлк, щёчки, счастье, шумный шёпот.",
    "Математическая формула: Q умножить на K транспонированное, "
    "делённое на корень из d.",
]


def main() -> None:
    try:
        from tutor.audio.postfx import PostFX
        from tutor.tts.vosk_client import vosk_tts_sentence
    except Exception as exc:
        print(f"ABORT import: {type(exc).__name__}: {exc}")
        sys.exit(1)

    fx = PostFX()
    if not fx.enabled:
        print("ABORT: PostFX disabled (pedalboard missing?).")
        sys.exit(2)

    dry_chunks = []
    wet_chunks = []
    sr = None

    total_render_ms = 0.0
    total_fx_ms = 0.0
    for text in SAMPLE_SENTENCES:
        print(f"render: {text!r}")
        t0 = time.perf_counter()
        try:
            audio, sample_rate = vosk_tts_sentence(text, "neutral")
        except Exception as exc:
            print(f"  Vosk failed: {type(exc).__name__}: {exc}")
            print("  Is start_tutor_v2.bat running so the TTS server is up?")
            sys.exit(3)
        render_ms = (time.perf_counter() - t0) * 1000
        total_render_ms += render_ms
        if sr is None:
            sr = sample_rate
        elif sample_rate != sr:
            print(f"  mixed sample rates {sample_rate} vs {sr}, skipping")
            continue
        print(f"  vosk: {render_ms:5.0f} ms, "
              f"audio {len(audio)} samples ({len(audio)/sr:.2f}s)")
        t0 = time.perf_counter()
        processed = fx(audio, sr)
        fx_ms = (time.perf_counter() - t0) * 1000
        total_fx_ms += fx_ms
        print(f"  postfx: {fx_ms:5.1f} ms")
        # Small silence between sentences for clarity in the wav files.
        silence = np.zeros(int(sr * 0.3), dtype=audio.dtype)
        dry_chunks.append(audio)
        dry_chunks.append(silence)
        wet_chunks.append(processed.astype(audio.dtype, copy=False))
        wet_chunks.append(silence)

    print(f"\ntotal render: {total_render_ms:.0f} ms, "
          f"total post-fx: {total_fx_ms:.1f} ms "
          f"({100*total_fx_ms/max(total_render_ms,1):.1f}% of render)")

    dry = np.concatenate(dry_chunks)
    wet = np.concatenate(wet_chunks)
    wf.write("postfx_dry.wav", sr, dry)
    wf.write("postfx_wet.wav", sr, wet)
    print("wrote postfx_dry.wav and postfx_wet.wav at "
          f"{sr} Hz, {len(dry)/sr:.1f}s")
    print("Listen and compare. If wet is worse, simply do not set "
          "TTS_POSTFX in .env.")


if __name__ == "__main__":
    main()
