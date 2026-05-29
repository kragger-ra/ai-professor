"""Vosk-TTS HTTP server for AI Professor integration.

Endpoints:
  POST /tts          — synthesize full text (single WAV)
  POST /tts/sentence — synthesize one short sentence (optimized for streaming)
  GET  /speakers     — list available speakers
  GET  /health       — health check
"""
import io
import logging
import time

import numpy as np
from scipy.io import wavfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from vosk_tts import Model, Synth
from text_utils import preprocess_tts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("vosk-tts")

SAMPLE_RATE = 22050
SPEAKERS = {
    0: {"id": 0, "name": "female_0", "gender": "female"},
    1: {"id": 1, "name": "female_1", "gender": "female"},
    2: {"id": 2, "name": "female_2", "gender": "female"},
    3: {"id": 3, "name": "male_0", "gender": "male"},
    4: {"id": 4, "name": "male_1", "gender": "male"},
}

log.info("Loading Vosk-TTS model (vosk-model-tts-ru-0.9-multi)...")
model = Model(model_name="vosk-model-tts-ru-0.9-multi")
synth = Synth(model)
log.info("Model loaded. Ready to serve.")

app = FastAPI(title="Vosk-TTS Server", version="1.0")


class TTSRequest(BaseModel):
    text: str
    speaker_id: int = 3  # male_0 by default (professor voice)
    speech_rate: float = 1.0
    skip_normalize: bool = False  # skip normalization if client already did it


def _deess(audio: np.ndarray, threshold_db: float = -20) -> np.ndarray:
    """De-esser: compress harsh high frequencies above 4kHz.

    Splits audio into low (<4kHz) and high (>4kHz) bands, then soft-compresses
    the high band when it exceeds the threshold. Removes buzzy/harsh artifacts
    from VITS synthesis without muffling the voice.
    """
    from scipy.signal import butter, sosfilt
    af = audio.astype(np.float32)
    sos_low = butter(4, 4000, btype='low', fs=SAMPLE_RATE, output='sos')
    sos_high = butter(4, 4000, btype='high', fs=SAMPLE_RATE, output='sos')
    low = sosfilt(sos_low, af)
    high = sosfilt(sos_high, af)
    threshold = 10 ** (threshold_db / 20) * 32767
    mask = np.abs(high) > threshold
    high[mask] *= 0.4
    return np.clip(low + high, -32767, 32767).astype(np.int16)


def _synthesize(text: str, speaker_id: int, speech_rate: float, skip_normalize: bool):
    """Core synthesis with timing."""
    word_count = len(text.split())

    t0 = time.perf_counter()
    if not skip_normalize:
        text = preprocess_tts(text)
    t_norm = time.perf_counter()

    # Normalisation can reduce input to nothing (pure symbols/punctuation);
    # the G2P crashes on empty input, so degrade to a short silence instead.
    if not text.strip():
        log.warning("[TTS] empty text after normalize — returning silence")
        return np.zeros(int(SAMPLE_RATE * 0.3), dtype=np.int16)

    try:
        audio = synth.synth_audio(text, speaker_id=speaker_id, speech_rate=speech_rate)
    except Exception as e:
        # A single un-synthesizable sentence must not 500 the whole pipeline.
        log.error(f"[TTS] synth failed on {text[:120]!r}: {type(e).__name__}: {e}")
        return np.zeros(int(SAMPLE_RATE * 0.3), dtype=np.int16)
    audio = _deess(audio)
    t_synth = time.perf_counter()

    audio_duration = len(audio) / SAMPLE_RATE
    norm_ms = (t_norm - t0) * 1000
    synth_ms = (t_synth - t_norm) * 1000
    total_ms = (t_synth - t0) * 1000
    rtf = (t_synth - t_norm) / audio_duration if audio_duration > 0 else 0

    log.info(
        f"[TTS] normalize: {norm_ms:.1f}ms | synth: {synth_ms:.0f}ms | "
        f"total: {total_ms:.0f}ms | words: {word_count} | "
        f"audio: {audio_duration:.1f}s | RTF: {rtf:.2f}"
    )
    return audio


def _audio_to_wav_bytes(audio: np.ndarray) -> io.BytesIO:
    buf = io.BytesIO()
    wavfile.write(buf, SAMPLE_RATE, audio)
    buf.seek(0)
    return buf


@app.post("/tts")
async def synthesize(req: TTSRequest):
    """Synthesize speech from text. Returns WAV audio."""
    if not req.text.strip():
        raise HTTPException(400, "Empty text")
    if req.speaker_id not in SPEAKERS:
        raise HTTPException(400, f"Invalid speaker_id={req.speaker_id}. Valid: 0-4")

    audio = _synthesize(req.text, req.speaker_id, req.speech_rate, req.skip_normalize)
    return StreamingResponse(_audio_to_wav_bytes(audio), media_type="audio/wav")


@app.post("/tts/sentence")
async def synthesize_sentence(req: TTSRequest):
    """Synthesize a single short sentence. Same as /tts but named for clarity."""
    if not req.text.strip():
        raise HTTPException(400, "Empty text")
    if req.speaker_id not in SPEAKERS:
        raise HTTPException(400, f"Invalid speaker_id={req.speaker_id}. Valid: 0-4")

    audio = _synthesize(req.text, req.speaker_id, req.speech_rate, req.skip_normalize)
    return StreamingResponse(_audio_to_wav_bytes(audio), media_type="audio/wav")


@app.get("/speakers")
async def list_speakers():
    """List available speaker IDs."""
    return {"speakers": list(SPEAKERS.values())}


@app.get("/health")
async def health():
    return {"status": "ok", "model": "vosk-tts-ru-0.9-multi", "sample_rate": SAMPLE_RATE}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=22232)
