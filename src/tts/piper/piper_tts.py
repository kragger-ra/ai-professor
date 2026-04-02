import os
import re
import sys

import numpy as np

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )

from data_schema.structure_templates import REPO_ROOT_PATH

PIPER_MODELS_DIR = os.path.join(REPO_ROOT_PATH, "data", "piper_models")
PIPER_MODEL_NAME = os.getenv("PIPER_MODEL_NAME", "ru_RU-denis-medium")
PIPER_LENGTH_SCALE = float(os.getenv("PIPER_LENGTH_SCALE", "1.3"))
PIPER_NOISE_SCALE = float(os.getenv("PIPER_NOISE_SCALE", "0.3"))
PIPER_NOISE_W_SCALE = float(os.getenv("PIPER_NOISE_W_SCALE", "0.1"))
PIPER_SENTENCE_PAUSE = float(os.getenv("PIPER_SENTENCE_PAUSE", "0.45"))
PIPER_CROSSFADE_MS = float(os.getenv("PIPER_CROSSFADE_MS", "80"))
PIPER_SILENCE_THRESHOLD = float(os.getenv("PIPER_SILENCE_THRESHOLD", "0.02"))
PIPER_MAX_SILENCE_MS = int(os.getenv("PIPER_MAX_SILENCE_MS", "30"))
PIPER_MODEL_PATH = os.path.join(PIPER_MODELS_DIR, PIPER_MODEL_NAME + ".onnx")

_voice = None
_syn_config = None


def _get_voice():
    global _voice, _syn_config
    if _voice is None:
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        config_path = PIPER_MODEL_PATH + ".json"
        print(f"[PIPER TTS] Loading model: {PIPER_MODEL_PATH}")
        _voice = PiperVoice.load(PIPER_MODEL_PATH, config_path=config_path, use_cuda=False)
        _syn_config = SynthesisConfig(
            length_scale=PIPER_LENGTH_SCALE,
            noise_scale=PIPER_NOISE_SCALE,
            noise_w_scale=PIPER_NOISE_W_SCALE,
        )
        print(f"[PIPER TTS] Model loaded, sr={_voice.config.sample_rate}, "
              f"length={PIPER_LENGTH_SCALE}, noise={PIPER_NOISE_SCALE}, noise_w={PIPER_NOISE_W_SCALE}")
    return _voice, _syn_config


def _compress_silence(audio: np.ndarray, sr: int) -> np.ndarray:
    """Compress silence gaps within a sentence to max_silence_ms."""
    max_silence_samples = int(sr * PIPER_MAX_SILENCE_MS / 1000)
    threshold = PIPER_SILENCE_THRESHOLD

    is_silent = np.abs(audio) < threshold
    result = []
    silence_count = 0

    for i, sample in enumerate(audio):
        if is_silent[i]:
            silence_count += 1
            if silence_count <= max_silence_samples:
                result.append(sample)
        else:
            silence_count = 0
            result.append(sample)

    return np.array(result, dtype=np.float32)


def _synthesize_sentence(voice, syn_config, text: str) -> np.ndarray:
    chunks = []
    for chunk in voice.synthesize(text, syn_config=syn_config):
        chunks.append(chunk.audio_float_array)
    if not chunks:
        return np.array([], dtype=np.float32)
    audio = np.concatenate(chunks).astype(np.float32)
    audio = _compress_silence(audio, voice.config.sample_rate)
    return audio


def _crossfade_join(segments: list[np.ndarray], sr: int) -> np.ndarray:
    if not segments:
        return np.zeros(sr, dtype=np.float32)
    if len(segments) == 1:
        return segments[0]

    fade_samples = int(sr * PIPER_CROSSFADE_MS / 1000)
    pause_samples = int(sr * PIPER_SENTENCE_PAUSE)

    result = segments[0].copy()
    for i in range(1, len(segments)):
        if len(result) >= fade_samples:
            fade_out = np.linspace(1.0, 0.0, fade_samples)
            result[-fade_samples:] *= fade_out
        result = np.concatenate([result, np.zeros(pause_samples, dtype=np.float32)])
        next_audio = segments[i].copy()
        if len(next_audio) >= fade_samples:
            fade_in = np.linspace(0.0, 1.0, fade_samples)
            next_audio[:fade_samples] *= fade_in
        result = np.concatenate([result, next_audio])
    return result


def piper_tts(text: str, **kwargs) -> tuple[np.ndarray, int]:
    """Generate speech from text using Piper TTS.
    Returns (audio_float32_array, sample_rate)
    """
    voice, syn_config = _get_voice()
    sr = voice.config.sample_rate

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if not sentences:
        return np.zeros(sr, dtype=np.float32), sr

    segments = []
    for sentence in sentences:
        audio = _synthesize_sentence(voice, syn_config, sentence)
        if len(audio) > 0:
            segments.append(audio)

    if not segments:
        return np.zeros(sr, dtype=np.float32), sr

    audio = _crossfade_join(segments, sr)

    peak = np.max(np.abs(audio))
    if peak > 0:
        audio = audio / peak

    return audio, sr


def piper_tts_emo(inp: dict) -> tuple[np.ndarray, int]:
    """Same interface as fish_tts_emo.
    inp = {"text": "...", "emotion": "neutral"}
    Piper does not support emotions — emotion is ignored.
    """
    text = inp["text"]
    if text and len(text) > 1000:
        text = text[:950] + ". Текст сокращён."
        print("[PIPER TTS] TEXT TRUNCATED to " + str(len(text)) + " chars")
    return piper_tts(text)


if __name__ == "__main__":
    import time

    test_text = "Приветствую вас, дорогие друзья! Как ваши дела?"
    print(f"[TEST] Synthesizing: {test_text}")

    start = time.perf_counter()
    audio, sample_rate = piper_tts_emo({"text": test_text, "emotion": "neutral"})
    elapsed = time.perf_counter() - start

    print(f"[TEST] Done in {elapsed:.3f}s")
    print(f"[TEST] Audio: {len(audio)} samples, sr={sample_rate}, duration={len(audio)/sample_rate:.2f}s")
    print(f"[TEST] dtype={audio.dtype}, min={audio.min():.3f}, max={audio.max():.3f}")

    try:
        import sounddevice as sd

        print("[TEST] Playing audio...")
        sd.play(audio, sample_rate, blocking=True)
        print("[TEST] Playback done.")
    except Exception as e:
        print(f"[TEST] Cannot play audio: {e}")
        print("[TEST] Saving to data/piper_test.wav instead...")
        from scipy.io import wavfile

        audio_int16 = (audio * 32767).astype(np.int16)
        wavfile.write(os.path.join(REPO_ROOT_PATH, "data", "piper_test.wav"), sample_rate, audio_int16)
        print("[TEST] Saved.")
