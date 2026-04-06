"""Vosk-TTS client with sentence streaming, phrase caching, and audio post-processing.

Drop-in replacement for fish_tts_emo / piper_tts_emo.
Also exposes streaming helpers for sentence-level playback.
"""
import io
import logging
import os
import re
import time
import hashlib
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import requests
from scipy.io import wavfile

log = logging.getLogger("vosk-tts-client")

VOSK_TTS_URL = os.getenv("VOSK_TTS_URL", "http://localhost:22232")
VOSK_SPEAKER_ID = int(os.getenv("VOSK_SPEAKER_ID", "3"))
VOSK_SPEECH_RATE = float(os.getenv("VOSK_SPEECH_RATE", "1.0"))
VOSK_SAMPLE_RATE = 22050

# Phrase cache directory
_CACHE_DIR = Path(__file__).resolve().parents[3] / "resources" / "Audio" / "tts_cache"


# =========================================================================
# Sentence splitting for streaming
# =========================================================================

_RE_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_SPLIT_CONJUNCTIONS = re.compile(
    r",\s+(?:и |но |а |или |что |который |которая |которое |которые "
    r"|потому что |поэтому |однако |хотя |если )",
    re.IGNORECASE,
)


def split_sentences(text: str) -> List[str]:
    """Split text into sentences suitable for streaming TTS (target: 4-10 words each).

    Rules:
    - Split on .!? immediately
    - Questions (?) always become separate sentences
    - Sentences >10 words get split at comma / conjunction
    - Sentences <3 words get merged with the next sentence
    """
    # First pass: split on sentence-ending punctuation
    raw = _RE_SENTENCE_END.split(text.strip())
    raw = [s.strip() for s in raw if s.strip()]

    # Second pass: split long sentences
    split = []
    for sent in raw:
        words = sent.split()
        if len(words) <= 10:
            split.append(sent)
            continue
        # Try splitting at conjunction
        m = _SPLIT_CONJUNCTIONS.search(sent)
        if m and m.start() > 10:
            part1 = sent[: m.start()].rstrip(",").strip()
            part2 = sent[m.end():].strip()
            if part1 and not part1[-1] in ".!?":
                part1 += "."
            if part2 and part2[0].islower():
                part2 = part2[0].upper() + part2[1:]
            split.append(part1)
            if part2:
                split.append(part2)
            continue
        # Try splitting at any comma
        comma_pos = -1
        wc = 0
        for i, ch in enumerate(sent):
            if ch == " ":
                wc += 1
            if ch == "," and 4 <= wc <= len(words) - 3:
                comma_pos = i
                if wc >= 7:
                    break
        if comma_pos > 0:
            part1 = sent[:comma_pos].strip()
            part2 = sent[comma_pos + 1:].strip()
            if part1 and not part1[-1] in ".!?":
                part1 += "."
            if part2 and part2[0].islower():
                part2 = part2[0].upper() + part2[1:]
            split.append(part1)
            if part2:
                split.append(part2)
        else:
            split.append(sent)

    # Third pass: merge very short fragments (<3 words) with next
    merged = []
    carry = ""
    for s in split:
        combined = (carry + " " + s).strip() if carry else s
        if len(combined.split()) < 3 and s != split[-1]:
            carry = combined
        else:
            merged.append(combined)
            carry = ""
    if carry:
        if merged:
            merged[-1] = merged[-1] + " " + carry
        else:
            merged.append(carry)

    return [s for s in merged if s.strip()]


# =========================================================================
# Phrase cache
# =========================================================================

# Common professor phrases: pre-synthesized for instant playback
CACHED_PHRASES = {
    "здравствуйте",
    "привет",
    "верно",
    "правильно",
    "нет не совсем",
    "не совсем",
    "отличный вопрос",
    "хороший вопрос",
    "давайте разберём",
    "давайте разберём подробнее",
    "молодец",
    "правильно молодец",
    "отлично",
    "так",
    "итак",
    "продолжим",
    "давайте продолжим",
    "интересный вопрос",
    "секунду",
    "одну секунду",
    "подождите",
    "хорошо",
    "понятно",
    "ладно",
    "смотрите",
    "послушайте",
    "обратите внимание",
    "это важно",
    "запомните",
    "повторю",
    "другими словами",
    "проще говоря",
    "например",
    "допустим",
    "представьте",
    "спасибо за вопрос",
    "спасибо",
    "до свидания",
    "до встречи",
    "на сегодня всё",
    "есть вопросы",
    "вопросы есть",
    "всё понятно",
    "идём дальше",
}


def _cache_key(phrase: str) -> str:
    """Normalized key for phrase cache lookup."""
    return phrase.lower().strip().rstrip(".,!?:;")


def _cache_path(phrase: str) -> Path:
    """Path to cached WAV file for a phrase."""
    key = _cache_key(phrase)
    h = hashlib.md5(key.encode()).hexdigest()[:12]
    return _CACHE_DIR / f"{h}.wav"


def get_cached_audio(sentence: str) -> Optional[Tuple[np.ndarray, int]]:
    """Check if sentence matches a cached phrase. Returns (audio, sr) or None."""
    key = _cache_key(sentence)
    if key not in CACHED_PHRASES:
        return None
    path = _cache_path(sentence)
    if not path.exists():
        return None
    try:
        sr, audio = wavfile.read(str(path))
        if audio.dtype == np.int16:
            audio = audio.astype(np.float32) / 32768.0
        return audio, sr
    except Exception:
        return None


def generate_phrase_cache():
    """Pre-generate WAV files for all cached phrases. Run once at setup."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log.info(f"Generating phrase cache in {_CACHE_DIR} ({len(CACHED_PHRASES)} phrases)")
    for phrase in sorted(CACHED_PHRASES):
        path = _cache_path(phrase)
        if path.exists():
            continue
        try:
            response = requests.post(
                f"{VOSK_TTS_URL}/tts/sentence",
                json={"text": phrase + ".", "speaker_id": VOSK_SPEAKER_ID},
                timeout=30,
            )
            response.raise_for_status()
            path.write_bytes(response.content)
            log.info(f"  cached: '{phrase}' -> {path.name}")
        except Exception as e:
            log.warning(f"  FAILED: '{phrase}': {e}")
    log.info("Phrase cache generation complete.")


# =========================================================================
# Audio post-processing (lightweight)
# =========================================================================

try:
    from scipy.signal import sosfilt, butter

    # Pre-compute filter coefficients ONCE
    _SOS_HIGHPASS = butter(4, 80, btype="high", fs=VOSK_SAMPLE_RATE, output="sos")
    _SOS_LOWPASS = butter(2, 7000, btype="low", fs=VOSK_SAMPLE_RATE, output="sos")
    HAS_SCIPY_SIGNAL = True
except ImportError:
    HAS_SCIPY_SIGNAL = False


def postprocess_audio(audio: np.ndarray, apply_eq: bool = True) -> np.ndarray:
    """Light post-processing: compression, normalization, optional EQ.

    Total cost: ~5-15ms per fragment.
    """
    if len(audio) == 0:
        return audio

    # Dynamic range compression (soft-knee)
    threshold = 0.3
    ratio = 2.5
    above = np.abs(audio) > threshold
    if np.any(above):
        compressed = audio.copy()
        sign = np.sign(compressed[above])
        excess = np.abs(compressed[above]) - threshold
        compressed[above] = sign * (threshold + excess / ratio)
        audio = compressed

    # Peak normalization
    peak = np.max(np.abs(audio))
    if peak > 0:
        headroom = 0.9  # -1dB headroom
        audio = audio * (headroom / peak)

    # EQ: cut below 80Hz (rumble), cut above 7kHz (hiss)
    if apply_eq and HAS_SCIPY_SIGNAL:
        audio = sosfilt(_SOS_HIGHPASS, audio).astype(np.float32)
        audio = sosfilt(_SOS_LOWPASS, audio).astype(np.float32)

    return audio


# =========================================================================
# Silence generation for micro-pauses
# =========================================================================

def generate_silence(duration_sec: float = 0.2) -> Tuple[np.ndarray, int]:
    """Generate silent audio for micro-pauses between sentences."""
    n_samples = int(VOSK_SAMPLE_RATE * duration_sec)
    return np.zeros(n_samples, dtype=np.float32), VOSK_SAMPLE_RATE


# =========================================================================
# Core TTS function (drop-in replacement)
# =========================================================================

def vosk_tts_emo(inp: dict) -> Tuple[np.ndarray, int]:
    """Same interface as fish_tts_emo / piper_tts_emo.

    inp = {"text": "...", "emotion": "neutral"}
    Vosk-TTS ignores emotion. Returns (audio_float32, sample_rate).
    """
    text = inp.get("text", "")
    if not text.strip():
        return np.zeros(VOSK_SAMPLE_RATE // 2, dtype=np.float32), VOSK_SAMPLE_RATE

    # Check phrase cache first
    cached = get_cached_audio(text)
    if cached is not None:
        log.info(f"[TTS] cache hit: '{text[:40]}'")
        return cached

    t0 = time.perf_counter()
    try:
        response = requests.post(
            f"{VOSK_TTS_URL}/tts/sentence",
            json={
                "text": text,
                "speaker_id": VOSK_SPEAKER_ID,
                "speech_rate": VOSK_SPEECH_RATE,
            },
            timeout=30,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        log.error(f"[TTS] Server error: {e}")
        return np.zeros(VOSK_SAMPLE_RATE // 2, dtype=np.float32), VOSK_SAMPLE_RATE

    buf = io.BytesIO(response.content)
    sr, audio = wavfile.read(buf)

    # Normalize to float32 [-1, 1]
    if audio.dtype == np.int16:
        audio = audio.astype(np.float32) / 32768.0

    # Post-process
    audio = postprocess_audio(audio)

    elapsed = (time.perf_counter() - t0) * 1000
    log.info(f"[TTS] '{text[:50]}' | {elapsed:.0f}ms | {len(audio)/sr:.1f}s audio")
    return audio, sr


def vosk_tts_sentence(text: str) -> Tuple[np.ndarray, int]:
    """Synthesize a single sentence. Checks cache, calls server, post-processes."""
    return vosk_tts_emo({"text": text, "emotion": "neutral"})
