"""Comprehensive Russian text normalization for Vosk-TTS.

Pipeline: markup cleanup -> abbreviations -> foreign terms -> lists ->
          math symbols -> numbers-to-words -> split long sentences ->
          punctuation finalize -> yo-restore -> stress marks ->
          stress overrides -> Latin transliterate residuals.
"""
import re
from pathlib import Path
from typing import List

try:
    from num2words import num2words as _num2words

    HAS_NUM2WORDS = True
except ImportError:
    HAS_NUM2WORDS = False


# =========================================================================
# Latin -> Cyrillic fallback transliteration (for unknown Latin tokens)
# =========================================================================
_LAT2CYR = {
    "a": "а", "b": "б", "c": "к", "d": "д", "e": "е",
    "f": "ф", "g": "г", "h": "х", "i": "и", "j": "дж",
    "k": "к", "l": "л", "m": "м", "n": "н", "o": "о",
    "p": "п", "q": "к", "r": "р", "s": "с", "t": "т",
    "u": "у", "v": "в", "w": "в", "x": "кс", "y": "й",
    "z": "з",
}


# =========================================================================
# Abbreviations (sorted longest-first to avoid partial matches)
# =========================================================================
ABBREVIATIONS = {
    "т.е.": "то есть",
    "т.д.": "так далее",
    "т.п.": "тому подобное",
    "т.к.": "так как",
    "т.н.": "так называемый",
    "напр.": "например",
    "руб.": "рублей",
    "гг.": "годы",
    "др.": "другие",
    "пр.": "прочее",
    "см.": "смотри",
    "ср.": "сравни",
    "м/с": "метров в секунду",
    "млрд": "миллиардов",
    "млн": "миллионов",
    "кг": "килограмм",
    "км": "километров",
}

# Build regex: sort by length desc so longer abbreviations match first
_ABBR_RE = re.compile(
    "|".join(re.escape(k) for k in sorted(ABBREVIATIONS, key=len, reverse=True)),
    re.IGNORECASE,
)


# =========================================================================
# Foreign terms -> Russian phonetic transcription
# =========================================================================
FOREIGN_TERMS = {
    # Programming languages & frameworks
    "python": "пайтон",
    "javascript": "джаваскрипт",
    "typescript": "тайпскрипт",
    "pytorch": "пайторч",
    "tensorflow": "тензорфлоу",
    "fastapi": "фаст эй пи ай",
    "gradio": "грэдио",
    "numpy": "нампай",
    "pandas": "пандас",
    "docker": "докер",
    "kubernetes": "кубернетис",
    "github": "гитхаб",
    "gitlab": "гитлаб",
    "vscode": "ви эс код",
    "linux": "линукс",
    "windows": "виндовс",
    "macOS": "мак о эс",
    "ubuntu": "убунту",
    # AI/ML terms
    "machine learning": "машин лёрнинг",
    "deep learning": "дип лёрнинг",
    "reinforcement learning": "рейнфорсмент лёрнинг",
    "transformer": "трансформер",
    "attention": "аттеншн",
    "embedding": "эмбеддинг",
    "fine-tuning": "файнтюнинг",
    "finetuning": "файнтюнинг",
    "finetune": "файнтюн",
    "dataset": "датасет",
    "benchmark": "бенчмарк",
    "pipeline": "пайплайн",
    "backend": "бэкенд",
    "frontend": "фронтенд",
    "framework": "фреймворк",
    "runtime": "рантайм",
    "middleware": "мидлвэр",
    "webhook": "вебхук",
    "endpoint": "эндпоинт",
    "chatbot": "чатбот",
    "prompt": "промпт",
    "token": "токен",
    "tokens": "токенов",
    "streaming": "стриминг",
    "stream": "стрим",
    "professor": "профессор",
    "prefetch": "префетч",
    "interrupt": "интеррапт",
    "timeout": "таймаут",
    # Acronyms
    "llm": "эл эл эм",
    "rag": "рэг",
    "gpt": "джи пи ти",
    "api": "эй пи ай",
    "cpu": "цэ пэ у",
    "gpu": "джи пи ю",
    "ram": "рам",
    "ssd": "эс эс ди",
    "html": "эйч ти эм эл",
    "css": "цэ эс эс",
    "http": "эйч ти ти пи",
    "https": "эйч ти ти пи эс",
    "url": "ю ар эл",
    "sql": "эс кью эл",
    "json": "джейсон",
    "yaml": "ямл",
    "xml": "икс эм эл",
    "pdf": "пи ди эф",
    "wav": "вав",
    "onnx": "о эн эн икс",
    "cuda": "куда",
    "vram": "ви рам",
    "tts": "ти ти эс",
    "stt": "эс ти ти",
    "nlp": "эн эл пи",
    "ocr": "о си ар",
    "ide": "ай ди и",
    "cli": "си эл ай",
    "gui": "гуи",
    "ip": "ай пи",
    "ai": "эй ай",
    "ml": "эм эл",
    "dl": "ди эл",
    "cv": "си ви",
    # Math/science variable names (single letters, standalone only)
    "x": "икс",
    "y": "игрек",
    "z": "зет",
    # Products & services
    "zoom": "зум",
    "slack": "слэк",
    "discord": "дискорд",
    "telegram": "телеграм",
    "google": "гугл",
    "openai": "опен ай ай",
    "anthropic": "антропик",
    "mistral": "мистраль",
    "claude": "клод",
    # Education-specific
    "PersonaLab": "персона лаб",
    "personalab": "персона лаб",
    "workshop": "воркшоп",
    "tutorial": "туториал",
    "homework": "хоумворк",
    "deadline": "дедлайн",
    "feedback": "фидбэк",
    "review": "ревью",
    "sprint": "спринт",
    "standup": "стендап",
    "backlog": "бэклог",
}

# Build regex: sort by length desc, word boundaries, case-insensitive
_FOREIGN_RE = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in sorted(FOREIGN_TERMS, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)


# =========================================================================
# Math symbols and superscripts
# =========================================================================
_MATH_SYMBOLS = {
    "²": " в квадрате",
    "³": " в кубе",
    "√": "корень из ",
    "∫": "интеграл ",
    "∑": "сумма ",
    "Δ": "дельта ",
    "δ": "дельта ",
    "π": "пи",
    "α": "альфа",
    "β": "бета",
    "γ": "гамма",
    "σ": "сигма",
    "μ": "мю",
    "λ": "лямбда",
    "θ": "тета",
    "ε": "эпсилон",
    "∞": "бесконечность",
    "≈": " приблизительно равно ",
    "≠": " не равно ",
    "≥": " больше или равно ",
    "≤": " меньше или равно ",
    "±": " плюс минус ",
    "×": " умножить на ",
    "÷": " разделить на ",
}

# Operators handled via regex for context sensitivity
_RE_PERCENT = re.compile(r"(\d+)\s*%")
_RE_POWER = re.compile(r"\^(\d+)")
_RE_EQUALS = re.compile(r"\s*=\s*")
_RE_PLUS = re.compile(r"(?<=\d)\s*\+\s*(?=\d)")
_RE_MINUS = re.compile(r"(?<=\d)\s*-\s*(?=\d)")
_RE_GT = re.compile(r"(?<=\d)\s*>\s*(?=\d)")
_RE_LT = re.compile(r"(?<=\d)\s*<\s*(?=\d)")


# =========================================================================
# List/enumeration patterns
# =========================================================================
_ORDINAL_MAP = {
    "1": "Первое", "2": "Второе", "3": "Третье", "4": "Четвёртое",
    "5": "Пятое", "6": "Шестое", "7": "Седьмое", "8": "Восьмое",
    "9": "Девятое", "10": "Десятое",
}

# Match list items: at line start, after newline, or after ". " (inline lists from LLM)
_RE_LIST_ITEM = re.compile(r"(?:(?:^|(?<=\.\s)|(?<=\n))\s*)(\d{1,2})[.)]\s+")


# =========================================================================
# Sentence splitting conjunctions
# =========================================================================
_SPLIT_CONJUNCTIONS = re.compile(
    r",\s+((?:и |но |а |или |что |который |которая |которое |которые "
    r"|потому что |поэтому |однако |причём |хотя |если ))",
    re.IGNORECASE,
)
# Fallback: split at bare conjunctions (no comma required) for very long sentences
_SPLIT_BARE_CONJUNCTIONS = re.compile(
    r"\s+(?:и |но |а |или |потому что |поэтому |однако |хотя )",
    re.IGNORECASE,
)


# =========================================================================
# Pipeline functions
# =========================================================================

# =========================================================================
# LaTeX cleanup — the LLM is asked to verbalise formulas, but it sometimes
# leaks raw LaTeX (\frac{...}, x_{i}, \sqrt{...}). Vosk's G2P CRASHES on a
# bare backslash or curly brace (→ HTTP 500), so we must neutralise them here.
# Known commands map to spoken Russian; unknown \commands are dropped.
# =========================================================================
_LATEX_WORDS = {
    "frac": "дробь", "dfrac": "дробь", "tfrac": "дробь",
    "sqrt": "корень из", "cdot": "умножить на", "times": "умножить на",
    "div": "разделить на", "pm": "плюс минус", "mp": "минус плюс",
    "leq": "меньше или равно", "le": "меньше или равно",
    "geq": "больше или равно", "ge": "больше или равно",
    "neq": "не равно", "ne": "не равно", "approx": "приблизительно равно",
    "equiv": "тождественно равно", "infty": "бесконечность",
    "sum": "сумма", "prod": "произведение", "int": "интеграл",
    "alpha": "альфа", "beta": "бета", "gamma": "гамма", "delta": "дельта",
    "epsilon": "эпсилон", "theta": "тета", "lambda": "лямбда", "mu": "мю",
    "pi": "пи", "sigma": "сигма", "phi": "фи", "omega": "омега",
    "partial": "частная производная", "in": "принадлежит",
    "forall": "для всех", "exists": "существует", "rightarrow": "стрелка",
}
_RE_LATEX_CMD = re.compile(r"\\([a-zA-Z]+)")


def strip_latex(text: str) -> str:
    """Neutralise LaTeX artifacts so leaked formula markup never reaches the
    Vosk G2P (which crashes on bare '\\', '{', '}')."""
    # Math-mode delimiters: $$..$$, $..$, \(..\), \[..\]
    text = re.sub(r"\$\$?", " ", text)
    text = text.replace(r"\(", " ").replace(r"\)", " ")
    text = text.replace(r"\[", " ").replace(r"\]", " ")
    # \command -> spoken word (or dropped if unknown)
    text = _RE_LATEX_CMD.sub(lambda m: " " + _LATEX_WORDS.get(m.group(1).lower(), "") + " ", text)
    # Subscript/superscript braces and any stray braces
    text = text.replace("{", " ").replace("}", " ")
    # Any remaining lone backslashes (\\ line breaks, \, thin spaces, etc.)
    text = text.replace("\\", " ")
    return text


def clean_markup(text: str) -> str:
    """Remove markdown, HTML tags, and other non-speech artifacts."""
    # Neutralise LaTeX first (bare \ and {} crash the Vosk G2P)
    text = strip_latex(text)
    # Remove code blocks
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Remove markdown headers
    text = re.sub(r"#{1,6}\s*", "", text)
    # Remove bold/italic markers
    text = re.sub(r"\*{1,3}(.*?)\*{1,3}", r"\1", text)
    text = re.sub(r"_{1,3}(.*?)_{1,3}", r"\1", text)
    # Remove markdown links [text](url) -> text
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Remove bracketed metadata like [источник], [ссылка]
    text = re.sub(r"\[[^\]]{1,30}\]", " ", text)
    # Separate digits from adjacent Latin letters: 2x -> 2 x, 15y -> 15 y
    text = re.sub(r"(\d)([a-zA-Z])", r"\1 \2", text)
    text = re.sub(r"([a-zA-Z])(\d)", r"\1 \2", text)
    # Newlines to spaces
    text = text.replace("\n", " ")
    # Collapse multiple spaces
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def expand_abbreviations(text: str) -> str:
    """Replace abbreviations with full forms."""
    def _repl(m):
        key = m.group(0).lower()
        # Try exact match first
        for orig, expanded in ABBREVIATIONS.items():
            if orig.lower() == key:
                return expanded
        return m.group(0)
    return _ABBR_RE.sub(_repl, text)


def handle_foreign_terms(text: str) -> str:
    """Replace known foreign terms with Russian phonetic equivalents."""
    def _repl(m):
        key = m.group(0).lower()
        for orig, phonetic in FOREIGN_TERMS.items():
            if orig.lower() == key:
                return phonetic
        return m.group(0)
    return _FOREIGN_RE.sub(_repl, text)


def handle_lists(text: str) -> str:
    """Convert numbered lists: '1. First' -> 'Первое. First'."""
    def _repl(m):
        num = m.group(1)
        prefix = m.group(0)
        ordinal = _ORDINAL_MAP.get(num)
        if ordinal:
            # Preserve leading newline if present
            leading = "\n" if prefix.startswith("\n") else ""
            return f"{leading}{ordinal}. "
        return prefix
    return _RE_LIST_ITEM.sub(_repl, text)


def handle_math(text: str) -> str:
    """Convert math symbols and expressions to spoken Russian."""
    # Superscripts and special symbols
    for sym, spoken in _MATH_SYMBOLS.items():
        text = text.replace(sym, spoken)

    # Powers: ^2 -> в квадрате, ^3 -> в кубе, ^N -> в степени N
    def _power_repl(m):
        n = m.group(1)
        if n == "2":
            return " в квадрате"
        elif n == "3":
            return " в кубе"
        else:
            return f" в степени {n}"
    text = _RE_POWER.sub(_power_repl, text)

    # Percent: 15% -> 15 процентов (number conversion happens later)
    text = _RE_PERCENT.sub(r"\1 процентов", text)

    # Math operators between digits
    text = _RE_PLUS.sub(" плюс ", text)
    text = _RE_MINUS.sub(" минус ", text)
    text = _RE_GT.sub(" больше ", text)
    text = _RE_LT.sub(" меньше ", text)
    # Equals (not between digits — more general)
    text = _RE_EQUALS.sub(" равно ", text)

    return text


def numbers_to_words(text: str) -> str:
    """Convert numbers to Russian words."""
    if not HAS_NUM2WORDS:
        return text

    # Decimal numbers: 3.14 -> три целых четырнадцать сотых
    def _decimal_repl(m):
        try:
            return _num2words(float(m.group(0)), lang="ru")
        except Exception:
            return m.group(0)
    text = re.sub(r"\b\d+\.\d+\b", _decimal_repl, text)

    # Years in context: в 1941 году -> в тысяча девятьсот сорок первом году
    def _year_repl(m):
        try:
            year = int(m.group(1))
            if 1000 <= year <= 2100:
                return f"в {_num2words(year, lang='ru', to='year')} году"
        except Exception:
            pass
        return m.group(0)
    text = re.sub(r"в\s+(\d{4})\s+год[уе]?", _year_repl, text)

    # Ordinal context: "в 3 главе" -> "в третьей главе"
    def _ordinal_context_repl(m):
        try:
            num = int(m.group(1))
            word = _num2words(num, lang="ru", to="ordinal")
            return f"{m.group(0).split()[0]} {word} {m.group(2)}"
        except Exception:
            return m.group(0)
    text = re.sub(
        r"(?:в|на|из|по|к|за|от)\s+(\d+)\s+(глав[еу]|части|разделе?|уроке?|лекции|неделе?|этапе?|шаге?|пункте?)",
        _ordinal_context_repl,
        text,
        flags=re.IGNORECASE,
    )

    # Plain integers: 42 -> сорок два
    def _int_repl(m):
        try:
            num = int(m.group(0))
            return _num2words(num, lang="ru")
        except Exception:
            return m.group(0)
    text = re.sub(r"\b\d+\b", _int_repl, text)

    return text


def split_long_sentences(text: str) -> str:
    """Break sentences longer than 25 words at natural break points."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    result = []
    for sent in sentences:
        words = sent.split()
        if len(words) <= 25:
            result.append(sent)
            continue
        # Try to split at conjunction after comma
        m = _SPLIT_CONJUNCTIONS.search(sent)
        if m and m.start() > 10:  # Don't split too early
            part1 = sent[: m.start()].rstrip(",").strip()
            conjunction = m.group(1)  # preserve "что ", "который ", etc.
            part2 = (conjunction + sent[m.end():]).strip()
            # Ensure both parts end/start properly
            if not part1[-1:] in ".!?":
                part1 += "."
            if part2 and part2[0].islower():
                part2 = part2[0].upper() + part2[1:]
            result.append(part1)
            result.append(part2)
            continue
        # Try to split at comma
        comma_pos = -1
        word_count = 0
        for i, ch in enumerate(sent):
            if ch == " ":
                word_count += 1
            if ch == "," and 5 <= word_count <= len(words) - 3:
                comma_pos = i
                if word_count >= 8:
                    break  # Good enough split point
        if comma_pos > 0:
            part1 = sent[:comma_pos].strip()
            part2 = sent[comma_pos + 1:].strip()
            if not part1[-1:] in ".!?":
                part1 += "."
            if part2 and part2[0].islower():
                part2 = part2[0].upper() + part2[1:]
            result.append(part1)
            result.append(part2)
            continue
        # Last resort: split at bare conjunction (no comma)
        m2 = _SPLIT_BARE_CONJUNCTIONS.search(sent)
        if m2:
            # Find a split point closest to the middle
            best = m2
            for m2 in _SPLIT_BARE_CONJUNCTIONS.finditer(sent):
                words_before = len(sent[:m2.start()].split())
                if 5 <= words_before <= len(words) - 3:
                    best = m2
                    if words_before >= 7:
                        break
            part1 = sent[: best.start()].strip()
            part2 = sent[best.end():].strip()
            if part1 and not part1[-1:] in ".!?":
                part1 += "."
            if part2 and part2[0].islower():
                part2 = part2[0].upper() + part2[1:]
            result.append(part1)
            if part2:
                result.append(part2)
        else:
            # Can't split gracefully — keep as is
            result.append(sent)
    return " ".join(result)


def finalize_punctuation(text: str) -> str:
    """Clean up punctuation for better TTS intonation."""
    # Em-dash to comma-pause
    text = text.replace(" — ", ", ")
    text = text.replace("—", ", ")
    # Ellipsis to period
    text = re.sub(r"\.{2,}", ".", text)
    text = text.replace("…", ".")
    # Remove stray special chars (fancy quotes, guillemets)
    text = re.sub(r'[\u201c\u201d\u00ab\u00bb\u201e\u201f]', "", text)
    text = re.sub(r"[()]", ", ", text)
    # Double commas/spaces
    text = re.sub(r",\s*,", ",", text)
    text = re.sub(r"\s+", " ", text)
    # Ensure final punctuation
    text = text.strip()
    if text and text[-1] not in ".!?":
        text += "."
    return text


# =========================================================================
# Yo-restoration (е → ё) using pymorphy2-derived dictionary
# =========================================================================
_YO_DICT_PATH = Path(__file__).parent / "yo_dict.txt"
_yo_map: dict[str, str] | None = None
_RE_CYR_WORD = re.compile(r"[а-яёА-ЯЁ]+")


def _load_yo_map() -> dict[str, str]:
    global _yo_map
    if _yo_map is not None:
        return _yo_map
    m: dict[str, str] = {}
    if _YO_DICT_PATH.exists():
        for line in _YO_DICT_PATH.read_text(encoding="utf-8").splitlines():
            w = line.strip()
            if w:
                m[w.replace("ё", "е")] = w
    _yo_map = m
    return m


def restore_yo(text: str) -> str:
    """Replace е with ё in known unambiguous word forms."""
    yo_map = _load_yo_map()
    if not yo_map:
        return text

    def _repl(match: re.Match) -> str:
        w = match.group(0)
        yo = yo_map.get(w.lower())
        if yo is None:
            return w
        if w.isupper():
            return yo.upper()
        if w[0].isupper():
            return yo[0].upper() + yo[1:]
        return yo

    return _RE_CYR_WORD.sub(_repl, text)


def transliterate_latin(text: str) -> str:
    """Replace remaining Latin characters with Cyrillic equivalents."""
    result = []
    for ch in text:
        low = ch.lower()
        if low in _LAT2CYR:
            cyr = _LAT2CYR[low]
            if ch.isupper():
                cyr = cyr[0].upper() + cyr[1:]
            result.append(cyr)
        else:
            result.append(ch)
    return "".join(result)


# =========================================================================
# Stress marks (StressRNN → Vosk g2p convention)
# =========================================================================
_stress_model = None


def _stress_after_to_before(text: str) -> str:
    """Convert StressRNN convention (V+) to Vosk convention (+V).

    StressRNN: за+мок, му+ка   (+ AFTER stressed vowel)
    Vosk g2p:  з+амок, м+ука   (+ BEFORE stressed vowel)
    """
    return re.sub(r"([аеёиоуыэюяАЕЁИОУЫЭЮЯ])\+", r"+\1", text)


def add_stress_marks(text: str) -> str:
    """Add stress marks for Vosk TTS using StressRNN.

    Lazy-loads the model on first call (~0.5s). Subsequent calls are fast.
    Words already containing + are left unchanged (manual override).
    """
    global _stress_model
    if _stress_model is None:
        try:
            from stressrnn import StressRNN
            _stress_model = StressRNN()
        except Exception as e:
            print(f"[text_utils] StressRNN not available: {e}")
            return text

    try:
        # StressRNN processes full text, returns V+ convention
        stressed = _stress_model.put_stress(text, stress_symbol="+", accuracy_threshold=0.75)
        # Convert V+ → +V for Vosk g2p
        return _stress_after_to_before(stressed)
    except Exception:
        return text


# =========================================================================
# Stress overrides — manual fixes that win against StressRNN
# =========================================================================
_OVERRIDES_PATH = Path(__file__).parent / "stress_overrides.txt"
_overrides: dict[str, str] | None = None
_RE_STRESS_TOKEN = re.compile(r"[а-яёА-ЯЁ+]+")


def _load_overrides() -> dict[str, str]:
    global _overrides
    if _overrides is not None:
        return _overrides
    m: dict[str, str] = {}
    if _OVERRIDES_PATH.exists():
        for raw in _OVERRIDES_PATH.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            if "=>" in raw:
                lhs, rhs = raw.split("=>", 1)
                key = lhs.strip().replace("+", "").lower()
                value = rhs.strip()
            else:
                value = raw
                key = value.replace("+", "").lower()
            if key:
                m[key] = value
    _overrides = m
    return m


def apply_stress_overrides(text: str) -> str:
    """Override stress/spelling for listed words. Wins against StressRNN."""
    ov_map = _load_overrides()
    if not ov_map:
        return text

    def _repl(match: re.Match) -> str:
        w = match.group(0)
        if not any(c.isalpha() for c in w):
            return w
        key = w.replace("+", "").lower()
        ov = ov_map.get(key)
        if ov is None:
            return w
        first_alpha = next((c for c in w if c.isalpha()), "")
        if first_alpha.isupper():
            return ov[0].upper() + ov[1:]
        return ov

    return _RE_STRESS_TOKEN.sub(_repl, text)


# =========================================================================
# Final whitelist — the Vosk g2p phoneme_id_map has only ~63 keys and raises
# KeyError on ANY character it doesn't know (e.g. '@', '\\', '{', '}', '=').
# After all conversions (Latin→Cyrillic, numbers→words, math→words) the text
# must contain only speakable chars: Cyrillic, whitespace, the '+' stress
# marker, and a small punctuation set. Drop anything else so leaked symbols
# never crash synthesis.
# =========================================================================
_RE_UNSPEAKABLE = re.compile(r"[^а-яёА-ЯЁ\s+.,!?:;\-'()]")


def drop_unspeakable(text: str) -> str:
    text = _RE_UNSPEAKABLE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def preprocess_tts(text: str) -> str:
    """Full normalization pipeline for Vosk-TTS."""
    text = clean_markup(text)
    text = expand_abbreviations(text)
    text = handle_foreign_terms(text)
    text = handle_lists(text)
    text = handle_math(text)
    text = numbers_to_words(text)
    text = split_long_sentences(text)
    text = finalize_punctuation(text)
    # Restore ё before stress: LLMs often write е for ё, which misleads StressRNN
    text = restore_yo(text)
    # Add stress marks BEFORE transliteration (+ must be next to Cyrillic vowels)
    text = add_stress_marks(text)
    # User-controlled overrides take precedence over StressRNN predictions
    text = apply_stress_overrides(text)
    # Transliterate any remaining Latin characters
    text = transliterate_latin(text)
    # Final safety net: strip anything the g2p phoneme map can't handle
    text = drop_unspeakable(text)
    return text.strip()
