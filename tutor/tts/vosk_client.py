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
import unicodedata
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
import requests
from scipy.io import wavfile


_LATIN_TO_CYR = {
    'a': 'а', 'b': 'б', 'c': 'к', 'd': 'д', 'e': 'э', 'f': 'ф',
    'g': 'г', 'h': 'х', 'i': 'и', 'j': 'дж', 'k': 'к', 'l': 'л',
    'm': 'м', 'n': 'н', 'o': 'о', 'p': 'п', 'q': 'кв', 'r': 'р',
    's': 'с', 't': 'т', 'u': 'у', 'v': 'в', 'w': 'в', 'x': 'кс',
    'y': 'й', 'z': 'з',
}


def _transliterate_latin_word(word: str) -> str:
    """Convert leftover latin word to phonetic cyrillic so Vosk doesn't
    spell it letter-by-letter (e.g. "database" -> "д-а-т-а-б-а-с-э")."""
    return ''.join(_LATIN_TO_CYR.get(c.lower(), c) for c in word)


_LATIN_WORD_RE = re.compile(r'[A-Za-z]{2,}')


def _sanitize_for_vosk(text: str) -> str:
    """Strip characters that make Vosk-TTS truncate synthesis mid-sentence,
    and transliterate any remaining latin words to phonetic cyrillic.

    Observed failures (simulation 2026-05-16):
      - Combining acute (U+0301) in pronunciation map (e.g. "По́стгрес") → 17 words → 0.5s WAV
      - Stray backticks → similar truncation
      - Slashes / underscores inside identifiers — same family of failure
      - Untranslated latin words ("natyan", "database") spelled letter-by-letter
    """
    if not text:
        return text
    # 1. Strip ONLY the combining marks that wreck Vosk synthesis
    #    (acute U+0301, grave U+0300, circumflex U+0302 — used as bogus
    #    stress markers). DO NOT touch other combining marks: ё decomposes
    #    to "е + COMBINING DIAERESIS (U+0308)" under NFD, and stripping
    #    *all* combining marks would silently demote ё to е, which Vosk
    #    then voices as a plain "е".
    text = unicodedata.normalize('NFD', text)
    text = text.replace('́', '').replace('̀', '').replace('̂', '')
    text = unicodedata.normalize('NFC', text)
    # 2. Drop any stray backticks (paired ones are already stripped upstream
    #    by core_agent._strip_markdown_for_tts; this catches the lone ones).
    text = text.replace('`', '')
    # 3. Replace path/identifier separators with spaces so Vosk reads them
    #    as word boundaries instead of choking.
    text = re.sub(r'[/\\]', ' ', text)
    text = re.sub(r'_', ' ', text)
    # 4. Transliterate any latin words that survived the pronunciation map.
    #    Course-specific terms (SQLite, LangChain, etc.) are already replaced
    #    earlier in `vosk_tts_emo`; this fallback catches generic identifiers
    #    like "natyan", "database", "tool", "system" that the LLM leaves in.
    text = _LATIN_WORD_RE.sub(lambda m: _transliterate_latin_word(m.group(0)), text)
    # 5. Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

log = logging.getLogger("vosk-tts-client")

VOSK_TTS_URL = os.getenv("VOSK_TTS_URL", "http://localhost:22232")
VOSK_SPEAKER_ID = int(os.getenv("VOSK_SPEAKER_ID", "3"))
VOSK_SPEECH_RATE = float(os.getenv("VOSK_SPEECH_RATE", "1.0"))
VOSK_SAMPLE_RATE = 22050

# Emotion → (speech_rate multiplier, pause_after multiplier).
# Server is non-emotional Vosk-TTS, so the only knob we have is rate; the pause
# multiplier is consumed by the queue handler when it inserts inter-sentence silence.
# Keys must match the labels emitted by core_agent's _parse_emotion (lowercase English).
EMOTION_PROSODY: dict[str, tuple[float, float]] = {
    "neutral":     (1.00, 1.00),
    "happy":       (1.05, 0.90),
    "encouraging": (1.03, 0.95),
    "thoughtful":  (0.92, 1.20),
    "sad":         (0.90, 1.20),
    "angry":       (1.08, 0.85),
    "scared":      (1.05, 1.10),
    "whispering":  (0.92, 1.05),
    "disgusted":   (0.95, 1.05),
    "sarcastic":   (0.95, 1.10),
}


def emotion_prosody(emotion: str | None) -> tuple[float, float]:
    if not emotion:
        return 1.0, 1.0
    return EMOTION_PROSODY.get(emotion.lower(), (1.0, 1.0))

# Phrase cache directory
_CACHE_DIR = Path(__file__).resolve().parents[2] / "resources" / "Audio" / "tts_cache"


# =========================================================================
# Sentence splitting for streaming
# =========================================================================

# Split on .!? only when next non-space char starts a new sentence (capital/digit/quote).
# Prevents splitting paths/identifiers like `data/natyan_database.sqlite`.
_RE_SENTENCE_END = re.compile(
    r"(?:(?<=[.!?])\s+(?=[А-ЯA-ZЁ0-9«\"'(]))"
)
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

    # Second pass: split very long sentences (>18 words) at conjunction only.
    # Lower thresholds + arbitrary comma-split historically chopped normal
    # Russian sentences (~10-14 words) at commas, producing audible cuts mid-
    # phrase. We now only intervene on truly long runs and only at conjunctions
    # — never on arbitrary commas.
    split = []
    for sent in raw:
        words = sent.split()
        if len(words) <= 18:
            split.append(sent)
            continue
        # Try splitting at conjunction (но / что / если / однако …)
        m = _SPLIT_CONJUNCTIONS.search(sent)
        if m and m.start() > 15:
            part1_raw = sent[: m.start()].rstrip(",").strip()
            part2 = sent[m.end():].strip()
            # Guard: part1 must be a complete clause, not a noun-phrase
            # tail like "Формулировка о том" + ", что ..." → wrong split.
            # Require >=5 words and avoid idiomatic anchors (о том / тем /
            # тому / тех / так), which always continue the same clause.
            part1_words = part1_raw.split()
            _IDIOMATIC_TAILS = {"том", "тем", "тому", "тех", "так", "то"}
            tail_word = part1_words[-1].lower().rstrip(",.!?:;") if part1_words else ""
            if len(part1_words) < 5 or tail_word in _IDIOMATIC_TAILS:
                # Keep the whole long sentence — don't fragment.
                split.append(sent)
                continue
            part1 = part1_raw
            if part1 and not part1[-1] in ".!?":
                part1 += "."
            if part2 and part2[0].islower():
                part2 = part2[0].upper() + part2[1:]
            split.append(part1)
            if part2:
                split.append(part2)
            continue
        # No good split point — keep whole sentence. Better one long audio
        # chunk than chopping mid-clause and losing a fragment to Vosk.
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


# Variable pause durations keyed off the sentence's last meaningful character.
# Tuned for dialog pacing (faster than narration).
_PAUSE_ELLIPSIS = 0.45
_PAUSE_QUESTION = 0.30
_PAUSE_SENTENCE = 0.22  # . !
_PAUSE_CLAUSE = 0.18    # , ; :
_PAUSE_DEFAULT = 0.18

# Sentences containing one of these lexical-emphasis markers get a longer
# trailing pause so the signalled content has time to land before the next
# sentence starts. Compensates for Vosk's lack of prosodic emphasis.
_PAUSE_SIGNAL = 0.55
_SIGNAL_PHRASES = (
    "главное здесь",
    "запомни одно",
    "запомни это",
    "запомни —",
    "запомни-",
    "если запомнишь",
    "ключевая мысль",
    "это всё про",
    "проверю, понял",
    "подведём итог",
)


def pause_for_sentence(sentence: str) -> float:
    """Pick a pause length based on lexical signal markers OR end punctuation.

    Signal markers take priority: if the sentence introduces / closes a
    pedagogical block, we want a noticeable pause AFTER it, regardless of
    what punctuation it ended with.
    """
    s = sentence.rstrip()
    if not s:
        return _PAUSE_DEFAULT
    s_lower = s.lower()
    if any(phrase in s_lower for phrase in _SIGNAL_PHRASES):
        return _PAUSE_SIGNAL
    last = s[-1]
    if last == "…" or s.endswith("..."):
        return _PAUSE_ELLIPSIS
    if last == "?":
        return _PAUSE_QUESTION
    if last in ".!":
        return _PAUSE_SENTENCE
    if last in ",;:":
        return _PAUSE_CLAUSE
    return _PAUSE_DEFAULT


# =========================================================================
# Core TTS function (drop-in replacement)
# =========================================================================

def vosk_tts_emo(inp: dict) -> Tuple[np.ndarray, int]:
    """Same interface as fish_tts_emo / piper_tts_emo.

    inp = {"text": "...", "emotion": "neutral"}
    The server is non-emotional, but we map the emotion to a speech_rate
    multiplier so the prosody at least responds to the LLM's tag.
    Returns (audio_float32, sample_rate).
    """
    text = inp.get("text", "")
    emotion = inp.get("emotion", "")
    if not text.strip():
        return np.zeros(VOSK_SAMPLE_RATE // 2, dtype=np.float32), VOSK_SAMPLE_RATE

    # Pronunciation fixes for Vosk TTS
    import re as _re
    _TTS_PRONUNCIATION = [
        # Generic acronyms
        (_re.compile(r'\bAI\b'), 'Эй Ай'),
        (_re.compile(r'\bAPI\b'), 'Эй Пи Ай'),
        (_re.compile(r'\bLLM\b'), 'Эл Эл Эм'),
        (_re.compile(r'\bRAG\b'), 'РАГ'),
        (_re.compile(r'\bSTT\b'), 'Эс Ти Ти'),
        (_re.compile(r'\bTTS\b'), 'Ти Ти Эс'),
        (_re.compile(r'\bFAISS\b'), 'ФАЙСС'),
        (_re.compile(r'\bGPT\b'), 'Джи Пи Ти'),
        (_re.compile(r'\bVLA\b'), 'Ви Эл Эй'),
        (_re.compile(r'\bVLM\b'), 'Ви Эл Эм'),
        (_re.compile(r'\bVPT\b'), 'Ви Пи Ти'),
        (_re.compile(r'\bCLI\b'), 'Си Эл Ай'),
        (_re.compile(r'\bMCP\b'), 'Эм Си Пи'),
        # Databases / tools (course-specific terms for апробация).
        # NO U+0301 stress marks — Vosk G2P crashes on them. Use `+` before
        # vowel if explicit stress is needed (StressRNN preprocessor handles
        # most cases automatically).
        (_re.compile(r'\bSQLite\b', _re.IGNORECASE), 'Эс Ку Эль Лайт'),
        (_re.compile(r'\bPostgreSQL\b', _re.IGNORECASE), 'Постгрескьюэль'),
        (_re.compile(r'\bPostgres\b', _re.IGNORECASE), 'Постгрес'),
        (_re.compile(r'\bJSON\b'), 'Джейсон'),
        (_re.compile(r'\bYAML\b'), 'Ямл'),
        (_re.compile(r'\bRedis\b'), 'Редис'),
        (_re.compile(r'\bMongoDB\b'), 'Монго ди би'),
        (_re.compile(r'\bChromaDB\b'), 'Хрома ди би'),
        (_re.compile(r'\bGGUF\b'), 'Джи Джи Ю Эф'),
        (_re.compile(r'\bLoRA\b'), 'Лора'),
        (_re.compile(r'\bDocker\b'), 'Докер'),
        # LLM frameworks
        (_re.compile(r'\bLangChain\b'), 'Лэнг Чейн'),
        (_re.compile(r'\bLangGraph\b'), 'Лэнг Граф'),
        (_re.compile(r'\bSmolAgents\b'), 'Смол Эйджентс'),
        (_re.compile(r'\bLiteLLM\b'), 'Лайт Эл Эл Эм'),
        (_re.compile(r'\bLM Studio\b'), 'Эл Эм Студио'),
        # Course-specific identifiers
        (_re.compile(r'\bSaveUserInfoTool\b'), 'Сейв Юзер Инфо Тул'),
        (_re.compile(r'\bToolConfig\b'), 'Тул Конфиг'),
        (_re.compile(r'\bUserInfo\b'), 'Юзер Инфо'),
        (_re.compile(r'\bMindBridge\b'), 'Майнд Бридж'),
        (_re.compile(r'\bMainBridge\b'), 'Мейн Бридж'),
        (_re.compile(r'\bKTX Swarm\b'), 'Ка Ти Икс Сворм'),
        (_re.compile(r'\bKTX Chat\b'), 'Ка Ти Икс Чат'),
        (_re.compile(r'\bEventBase\b'), 'Ивент Бейс'),
        (_re.compile(r'\bDataCollector\b'), 'Дата Коллектор'),
        (_re.compile(r'\bResponseParser\b'), 'Респонс Парсер'),
        (_re.compile(r'\bToolExecutor\b'), 'Тул Экзекьютор'),
        (_re.compile(r'\bPrompt Constructor\b'), 'Промпт Констрактор'),
        (_re.compile(r'\btool_status\b'), 'тул статус'),
        (_re.compile(r'\bdocstring\b', _re.IGNORECASE), 'докстринг'),
        (_re.compile(r'\bprefill\b', _re.IGNORECASE), 'префилл'),
        # Common course-specific English nouns. Order matters: longer/plural
        # forms FIRST so the singular regex doesn't eat the plural's tail.
        (_re.compile(r'\bdatabase\b', _re.IGNORECASE), 'датабейс'),
        (_re.compile(r'\bnatyan\b', _re.IGNORECASE), 'натьян'),
        (_re.compile(r'\bdata\b', _re.IGNORECASE), 'дата'),
        (_re.compile(r'\btools\b', _re.IGNORECASE), 'тулс'),
        (_re.compile(r'\btool\b', _re.IGNORECASE), 'тул'),
        (_re.compile(r'\bsystem\b', _re.IGNORECASE), 'систем'),
        (_re.compile(r'\busers\b', _re.IGNORECASE), 'юзерс'),
        (_re.compile(r'\buser\b', _re.IGNORECASE), 'юзер'),
        (_re.compile(r'\bagents\b', _re.IGNORECASE), 'эйджентс'),
        (_re.compile(r'\bagent\b', _re.IGNORECASE), 'эйджент'),
        (_re.compile(r'\bprompt\b', _re.IGNORECASE), 'промпт'),
        (_re.compile(r'\bfile\b', _re.IGNORECASE), 'файл'),
        (_re.compile(r'\bchat\b', _re.IGNORECASE), 'чат'),
        (_re.compile(r'\bconfig\b', _re.IGNORECASE), 'конфиг'),
        (_re.compile(r'\bsummary\b', _re.IGNORECASE), 'саммари'),
        (_re.compile(r'\brank\b', _re.IGNORECASE), 'ранк'),
        (_re.compile(r'\blike\b', _re.IGNORECASE), 'лайк'),
        (_re.compile(r'\bsave\b', _re.IGNORECASE), 'сейв'),
        (_re.compile(r'\bspeak\b', _re.IGNORECASE), 'спик'),
        (_re.compile(r'\bfocus\b', _re.IGNORECASE), 'фокус'),
        (_re.compile(r'\bemotion\b', _re.IGNORECASE), 'эмоушн'),
        (_re.compile(r'\bsession\b', _re.IGNORECASE), 'сэшн'),
        (_re.compile(r'\bquery\b', _re.IGNORECASE), 'квери'),
        (_re.compile(r'\btable\b', _re.IGNORECASE), 'тейбл'),
        (_re.compile(r'\bPython\b', _re.IGNORECASE), 'пайтон'),
        (_re.compile(r'\bJava\b', _re.IGNORECASE), 'джава'),
        (_re.compile(r'\bMinecraft\b', _re.IGNORECASE), 'майнкрафт'),
        # Models / agents
        (_re.compile(r'\bGemma\b'), 'Гэмма'),
        (_re.compile(r'\bQwen\b', _re.IGNORECASE), 'Квэн'),
        (_re.compile(r'\bMistral\b'), 'Мистраль'),
        (_re.compile(r'\bNeMo\b'), 'Немо'),
        (_re.compile(r'\bSaiga\b'), 'Сайга'),
        (_re.compile(r'\bWhisper\b'), 'Виспер'),
        (_re.compile(r'\bVosk\b'), 'Воск'),
        (_re.compile(r'\bOptimus\b'), 'Оптимус'),
        (_re.compile(r'\bMineflayer\b'), 'Майн Флэер'),
        # Stress fix for ambiguous Russian word — `+` syntax forces stress on
        # the vowel that follows. Vosk G2P bypasses the dictionary when `+`
        # is present. U+0301 combining mark would crash G2P — DO NOT use it.
        (_re.compile(r'\bассистент', _re.IGNORECASE), 'ассист+энт'),
        # Orthoepy: 'чт' → 'шт' in functional words (что, чтобы, ничто, нечто).
        # Standard Russian pronunciation; helps Vosk avoid stutter on /tʃ/+/t/.
        (_re.compile(r'\bчто\b', _re.IGNORECASE), 'што'),
        (_re.compile(r'\bчтобы\b', _re.IGNORECASE), 'штобы'),
        (_re.compile(r'\bничто\b', _re.IGNORECASE), 'ништо'),
        (_re.compile(r'\bнечто\b', _re.IGNORECASE), 'нешто'),
    ]
    for pattern, replacement in _TTS_PRONUNCIATION:
        text = pattern.sub(replacement, text)

    # Check phrase cache first
    cached = get_cached_audio(text)
    if cached is not None:
        log.info(f"[TTS] cache hit: '{text[:40]}'")
        return cached

    rate_mul, _ = emotion_prosody(emotion)
    effective_rate = VOSK_SPEECH_RATE * rate_mul

    text = _sanitize_for_vosk(text)
    if not text:
        return np.zeros(VOSK_SAMPLE_RATE // 2, dtype=np.float32), VOSK_SAMPLE_RATE
    t0 = time.perf_counter()
    print(f"[VOSK-SEND] '{text[:200]}'", flush=True)
    try:
        response = requests.post(
            f"{VOSK_TTS_URL}/tts/sentence",
            json={
                "text": text,
                "speaker_id": VOSK_SPEAKER_ID,
                "speech_rate": effective_rate,
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


def vosk_tts_sentence(text: str, emotion: str = "neutral") -> Tuple[np.ndarray, int]:
    """Synthesize a single sentence. Checks cache, calls server, post-processes."""
    return vosk_tts_emo({"text": text, "emotion": emotion})
