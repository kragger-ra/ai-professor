"""Voice-command router for the tutor AgentThread.

Phase 5 (active): manner-switch, course-load (short + long + bare),
list-courses.
Phase 6 (dormant - defined but not routed): session-summary.

Usage::

    from tutor.brain.commands import route

    # In AgentThread._handle():
    if route(agent, utterance):
        return   # handled; don't fall through to LLM

Agent attributes expected (must be wired in AgentThread before use):
    agent._tts_q           : queue.Queue  -- already exists
    agent._rag             : RagModel | None  -- already exists
    agent._personality     : str  -- already exists
    agent._history         : list[dict]  -- already exists
    agent._pool            : ThreadPoolExecutor  -- already exists
    agent._speak_line(text): method  -- already exists
    agent._manner          : str  -- NEW: "simpler" | "neutral" | "detailed"
"""
from __future__ import annotations

import difflib
import os
import re
import traceback
from typing import TYPE_CHECKING

from tutor.brain.llm import stream_response_sentences
from tutor.util import log

if TYPE_CHECKING:
    from tutor.brain.agent import AgentThread

_COMPONENT = "commands"

# ---------------------------------------------------------------------------
# MANNER SWITCH
# ---------------------------------------------------------------------------

_MANNER_SIMPLER_RE = re.compile(
    r"расскажи\s+проще"
    r"|попрощ[еауы]"
    r"|поп?рощ[еауы]"
    r"|короче"
    r"|простыми\s+словами"
    r"|объясни\s+проще",
    re.IGNORECASE,
)

_MANNER_DETAILED_RE = re.compile(
    r"\bподробне[ей]"                                  # подробнее / подробней
    r"|поподробн"                                      # поподробнее
    r"|более\s+подробн"                                # более подробно
    r"|(?:расскаж\w*|объясн\w*|говор\w*|рассказыва\w*)\s+подробн"
    r"|подробн\w*\s+(?:расскаж|объясн|говор)"
    r"|больше\s+(?:деталей|подробностей|примеров)"
    r"|детальн"
    r"|развёрнут|развернут"
    r"|строже"
    r"|поглубже|\bглубже"
    r"|академичн",
    re.IGNORECASE,
)

_MANNER_NEUTRAL_RE = re.compile(
    r"как\s+обычно"
    r"|нормально\s+говори"
    r"|нейтрально",
    re.IGNORECASE,
)

_MANNER_DISPATCH = (
    (_MANNER_SIMPLER_RE,  "simpler",  "professor_simpler",  "Хорошо, объясню проще."),
    (_MANNER_DETAILED_RE, "detailed", "professor_detailed", "Хорошо, развёрнуто."),
    (_MANNER_NEUTRAL_RE,  "neutral",  "professor_neutral",  "Хорошо, как обычно."),
)

# Combined manner regex for the route table — single source of truth so the
# routing test and the in-handler dispatch can never drift apart.
_MANNER_ANY_RE = re.compile(
    "|".join(f"(?:{rx.pattern})" for rx, *_ in _MANNER_DISPATCH),
    re.IGNORECASE,
)


def _handle_manner(agent: "AgentThread", utterance: str) -> None:
    """Switch agent._manner and agent._personality; confirm via TTS."""
    lower = utterance.lower()
    for pattern, manner_val, personality_val, confirmation in _MANNER_DISPATCH:
        if pattern.search(lower):
            agent._manner = manner_val
            agent._personality = personality_val
            log(_COMPONENT, f"manner -> {manner_val}")
            agent._speak_line(confirmation)
            return


# ---------------------------------------------------------------------------
# COURSE SEARCH DIRECTORIES
# ---------------------------------------------------------------------------

_COURSE_SEARCH_DIRS = ("courses", "samples", "data/courses")
_LOAD_VERBS = r"загрузи|подгрузи|добавь|открой|возьми|включи|начни"
_SUBJECT_NOUNS = r"предмет|курс|тему|дисциплину|модуль"

# Long form: "загрузи предмет X из папки Y"
_LOAD_SUBJECT_RE = re.compile(
    rf"(?P<verb>{_LOAD_VERBS})\s+"
    rf"(?:{_SUBJECT_NOUNS})\s+"
    r"(?P<name>.+?)\s+"
    r"из\s+(?:папки\s+)?(?P<path>.+?)\s*$",
    re.IGNORECASE,
)

# Short form: "загрузи курс X"
_LOAD_SUBJECT_SHORT_RE = re.compile(
    rf"(?P<verb>{_LOAD_VERBS})\s+"
    rf"(?:{_SUBJECT_NOUNS})\s+"
    r"(?P<name>.+?)\s*$",
    re.IGNORECASE,
)

# Bare form: "загрузи курс" (no name)
_LOAD_SUBJECT_BARE_RE = re.compile(
    rf"(?P<verb>{_LOAD_VERBS})\s+(?:{_SUBJECT_NOUNS})\s*[.!?,]?\s*$",
    re.IGNORECASE,
)


def _scan_known_courses() -> dict:
    """Scan _COURSE_SEARCH_DIRS for course packages.

    Returns {short_name_lower: abs_path}. A package is any subdir that
    contains course_config.yml; key is short_name (or name) from that YAML.
    Falls back to the directory name when YAML is missing or unreadable.
    """
    try:
        import yaml as _yaml  # type: ignore
    except ImportError:
        log(_COMPONENT, "PyYAML missing; cannot scan course directories")
        return {}

    found: dict = {}
    for base in _COURSE_SEARCH_DIRS:
        if not os.path.isdir(base):
            continue
        for entry in os.listdir(base):
            pkg_path = os.path.join(base, entry)
            if not os.path.isdir(pkg_path):
                continue
            cfg_path = os.path.join(pkg_path, "course_config.yml")
            if not os.path.isfile(cfg_path):
                # Accept dirs without config.yml if they contain .md/.txt
                has_docs = any(
                    f.endswith((".md", ".txt"))
                    for f in os.listdir(pkg_path)
                )
                if not has_docs:
                    continue
                dirkey = entry.strip().lower()
                if dirkey not in found:
                    found[dirkey] = os.path.abspath(pkg_path)
                continue
            try:
                with open(cfg_path, "r", encoding="utf-8") as f:
                    cfg = _yaml.safe_load(f) or {}
            except Exception as e:
                log(_COMPONENT, f"Failed to read {cfg_path}: {e}")
                continue
            course = cfg.get("course") or cfg
            short = (
                course.get("short_name") or course.get("name") or entry
            ).strip().lower()
            if short not in found:
                found[short] = os.path.abspath(pkg_path)
            # Also index by directory name for fallback
            dirkey = entry.strip().lower()
            if dirkey not in found:
                found[dirkey] = os.path.abspath(pkg_path)
    return found


def _resolve_course_by_name(name: str) -> str | None:
    """Find a known course matching the spoken name.

    Priority: exact -> substring -> fuzzy (difflib) -> word-by-word fuzzy.
    STT distortions like "вашим матом" -> "вышмат" are handled at step 4.
    """
    known = _scan_known_courses()
    if not known:
        return None
    target = name.strip().lower().rstrip(".!?,")
    # 1. Exact
    if target in known:
        return known[target]
    # 2. Substring either way
    for key, path in known.items():
        if target in key or key in target:
            return path
    # 3. Fuzzy whole-name
    close = difflib.get_close_matches(target, list(known.keys()), n=1, cutoff=0.55)
    if close:
        log(_COMPONENT, f"fuzzy course match: '{target}' -> '{close[0]}'")
        return known[close[0]]
    # 4. Word-by-word fuzzy
    for token in re.findall(r"\w+", target):
        if len(token) < 4:
            continue
        close = difflib.get_close_matches(
            token, list(known.keys()), n=1, cutoff=0.7
        )
        if close:
            log(_COMPONENT, f"fuzzy token match: '{token}' -> '{close[0]}'")
            return known[close[0]]
    return None


def _do_load_subject(agent: "AgentThread", name: str, path: str, verb: str) -> None:
    """Perform the RAG reload and refresh STT vocabulary if possible."""
    mode = "append" if verb.lower() == "добавь" else "replace"
    log(_COMPONENT, f"load subject: name={name!r}, path={path!r}, mode={mode}")
    agent._speak_line(f"Загружаю предмет {name}, минуту.")
    if agent._rag is None:
        agent._speak_line("RAG не инициализирован, загрузка невозможна.")
        return
    try:
        n = agent._rag.reload_from_path(name, path, mode=mode)
    except FileNotFoundError:
        agent._speak_line(f"Папка не найдена: {path}.")
        return
    except ValueError as exc:
        log(_COMPONENT, f"reload_from_path ValueError: {exc}")
        agent._speak_line("В папке нет файлов для загрузки.")
        return
    except Exception as exc:
        err = str(exc)[:120]
        log(_COMPONENT, f"reload_from_path failed: {exc}")
        traceback.print_exc()
        agent._speak_line(f"Не получилось загрузить: {err}.")
        return

    # Refresh STT vocabulary if the STT handler is accessible via the agent.
    try:
        vocab = agent._rag.get_vocabulary()
        if hasattr(agent, "_stt") and agent._stt is not None and vocab:
            agent._stt.update_vocabulary(vocab)
            log(_COMPONENT, f"STT vocab refreshed: {len(vocab)} terms")
    except Exception as exc:
        log(_COMPONENT, f"STT vocab refresh failed (non-fatal): {exc}")

    agent._speak_line(
        f"Готово, загружено {n} фрагментов. Могу преподавать предмет {name}."
    )


# State flag: True after a bare "загрузи курс" — next utterance is treated as
# the course name.  Stored on the module (singleton) because AgentThread does
# not yet have a field for it.  Thread-safe within the single agent loop.
_awaiting_course_name: bool = False


def _handle_load_subject(agent: "AgentThread", utterance: str) -> None:
    """Handle all three forms of the load-course command."""
    global _awaiting_course_name
    stripped = utterance.strip()

    # --- Awaiting-name mode: previous turn was a bare "загрузи курс" ----------
    if _awaiting_course_name:
        _awaiting_course_name = False
        cleaned = stripped.rstrip(".!?,")
        resolved = _resolve_course_by_name(cleaned)
        if resolved is None:
            known = _scan_known_courses()
            if known:
                options = ", ".join(sorted(set(known.keys()))[:5])
                agent._speak_line(f"Не нашёл такой курс. Доступны: {options}.")
            else:
                agent._speak_line(
                    "У меня пока нет ни одного курса. "
                    "Положи папку курса в courses или samples."
                )
            log(_COMPONENT, f"awaiting-name: '{cleaned}' not resolved")
            return
        _do_load_subject(agent, cleaned, resolved, "загрузи")
        return

    # --- Long form: explicit path ---------------------------------------------
    m = _LOAD_SUBJECT_RE.search(stripped)
    if m:
        name = m.group("name").strip().rstrip(".!?,")
        path = m.group("path").strip().rstrip(".!?,")
        verb = m.group("verb").lower()
        _do_load_subject(agent, name, path, verb)
        return

    # --- Bare form: no name ---------------------------------------------------
    if _LOAD_SUBJECT_BARE_RE.search(stripped):
        known = _scan_known_courses()
        if not known:
            agent._speak_line(
                "У меня пока нет ни одного курса. "
                "Положи папку курса в courses или samples."
            )
            log(_COMPONENT, "bare load: no known courses")
            return
        options = ", ".join(sorted(set(known.keys()))[:5])
        agent._speak_line(f"Какой курс загрузить? Доступны: {options}.")
        _awaiting_course_name = True
        log(_COMPONENT, "bare load: asking for course name")
        return

    # --- Short form: "загрузи курс X" ----------------------------------------
    m = _LOAD_SUBJECT_SHORT_RE.search(stripped)
    if not m:
        return
    name = m.group("name").strip().rstrip(".!?,")
    verb = m.group("verb").lower()
    resolved = _resolve_course_by_name(name)
    if resolved is None:
        known = _scan_known_courses()
        if known:
            options = ", ".join(sorted(set(known.keys()))[:5])
            agent._speak_line(f"Не нашёл курс {name}. Доступны: {options}.")
        else:
            agent._speak_line(
                f"Не нашёл курс {name}. Положи папку курса в courses или samples."
            )
        log(_COMPONENT, f"short load: name='{name}' not resolved")
        return
    log(_COMPONENT, f"short load resolved: name='{name}' -> '{resolved}'")
    _do_load_subject(agent, name, resolved, verb)


# Bare "загрузи <name>" — a load verb directly followed by a course name,
# without a "курс"/"предмет" noun. Routed ONLY when the name resolves to a
# known course, so unrelated phrases ("включи свет") fall through to the LLM.
_LOAD_BARE_RE = re.compile(
    rf"^\s*(?P<verb>{_LOAD_VERBS})\s+(?P<name>\S.*?)\s*[.!?]*\s*$",
    re.IGNORECASE,
)


def _bare_load_guard(utterance: str) -> bool:
    m = _LOAD_BARE_RE.match(utterance.strip())
    if not m:
        return False
    return _resolve_course_by_name(m.group("name")) is not None


def _handle_load_bare(agent: "AgentThread", utterance: str) -> None:
    """Load a course named right after the verb ('загрузи вайб-кодинг')."""
    m = _LOAD_BARE_RE.match(utterance.strip())
    if not m:
        return
    name = m.group("name").strip().rstrip(".!?,")
    resolved = _resolve_course_by_name(name)
    if resolved is None:
        return
    log(_COMPONENT, f"bare load resolved: name={name!r} -> {resolved!r}")
    _do_load_subject(agent, name, resolved, m.group("verb").lower())


# ---------------------------------------------------------------------------
# LIST COURSES
# ---------------------------------------------------------------------------

_LIST_COURSES_RE = re.compile(
    r"(?:"
    r"какие(?:\s+\w+){0,3}\s+курс\w*"
    r"|(?:покажи|перечисли|список)\s+(?:доступн\w+\s+)?курс\w*"
    r"|что\s+(?:у\s+тебя\s+)?(?:есть|загружено)"
    r"|что\s+(?:ты\s+)?(?:умеешь|можешь\s+преподавать)"
    r")",
    re.IGNORECASE,
)


def _handle_list_courses(agent: "AgentThread", utterance: str) -> None:
    """Speak the names of all known course packages (bypasses LLM)."""
    known = _scan_known_courses()
    if not known:
        agent._speak_line(
            "У меня пока нет ни одного курса. "
            "Положи папку курса в courses или samples."
        )
        log(_COMPONENT, "list courses: empty")
        return
    names = sorted(set(known.keys()))
    listing = ", ".join(names[:8])
    more = "" if len(names) <= 8 else f" и ещё {len(names) - 8}"
    agent._speak_line(f"Доступные курсы: {listing}{more}.")
    log(_COMPONENT, f"list courses: {names}")


# ---------------------------------------------------------------------------
# SESSION SUMMARY
# ---------------------------------------------------------------------------

_SESSION_SUMMARY_RE = re.compile(
    r"(?:"
    r"давай(?:те)?\s+(?:резюмируем|подведём|подведем|итог|итожим)"
    r"|подведи\s+(?:итог|итоги)"
    r"|резюм(?:е|ируй)"
    r"|сделай\s+(?:итог|резюме|выводы)"
    r"|что\s+мы\s+(?:разобрали|изучили|прошли|обсудили)"
    r"|итог(?:и)?\s+(?:занят|сессии|урока)"
    r"|подытожь"
    r")",
    re.IGNORECASE,
)


def _handle_session_summary(agent: "AgentThread", utterance: str) -> None:
    """Summarise the session history via one LLM call and speak the result."""
    history = getattr(agent, "_history", [])
    current_student = getattr(agent, "_current_student", None)

    # Gather recent messages as plain "role: text" lines
    recent: list[dict] = history[-30:] if len(history) > 30 else list(history)

    # Build transcript from history dicts (same format as AgentThread._history)
    student_name = current_student or "студент"
    lines = []
    for h in recent:
        role = h.get("role", "user")
        if role == "assistant":
            ans = h.get("answer")
            text = (" ".join(ans.sentences).strip() if ans else h.get("content", ""))
        else:
            text = h.get("content", "")
        text = (text or "").strip()
        if not text:
            continue
        label = "Преподаватель" if role == "assistant" else student_name
        lines.append(f"{label}: {text[:300]}")

    if len(lines) < 4:
        agent._speak_line(
            "Пока мало успели обсудить — нечего резюмировать. Спрашивай дальше."
        )
        return

    transcript = "\n".join(lines[-30:])
    prompt = (
        "Подведи итог занятия. Ровно 3-4 коротких предложения. Опирайся "
        "только на текст диалога ниже.\n\n"
        "Структура:\n"
        "1) Что разобрали — перечисли темы кратко.\n"
        "2) Где студент уверенно отвечал — одна фраза.\n"
        "3) Что стоит повторить — одна фраза.\n"
        "Не вставляй маркеры, говори текстом для голоса. "
        "Не повторяй сам диалог.\n\n"
        f"=== Диалог ===\n{transcript}\n=== Конец ===\n"
    )

    messages = [{"role": "user", "content": prompt}]
    log(_COMPONENT, "session summary: calling LLM")
    try:
        sentences = []
        for sentence in stream_response_sentences(messages, max_tokens=350):
            sentences.append(sentence)
            agent._speak_line(sentence)
        if not sentences:
            raise RuntimeError("LLM returned empty summary")
    except Exception as exc:
        log(_COMPONENT, f"summary LLM call failed: {exc}")
        traceback.print_exc()
        agent._speak_line(
            "Сегодня прошлись по нескольким темам по курсу. "
            "Хочешь — продолжим разбирать конкретное, или закончим занятие."
        )


# ---------------------------------------------------------------------------
# ROUTE TABLE  (ordered: first match wins)
# ---------------------------------------------------------------------------
# Each entry is (compiled_regex_or_None, guard_fn, handler_fn).
# guard_fn(utterance) -> bool is checked when regex is not None and matched,
# or when regex is None (handler decides from utterance).
# We use a flat (regex, handler) table with a unified dispatch loop below.

_ROUTE_TABLE = (
    # Phase 5 (active) - first match wins.

    # 1. Manner switch - utterance length guard applied alongside the regex.
    (_MANNER_ANY_RE, lambda u: len(u) < 120, _handle_manner),
    # 2. Course load - long / short / bare-with-noun forms.
    (
        re.compile(
            rf"(?:{_LOAD_VERBS})\s+(?:{_SUBJECT_NOUNS})",
            re.IGNORECASE,
        ),
        lambda u: True,
        _handle_load_subject,
    ),
    # 3. List courses
    (
        _LIST_COURSES_RE,
        lambda u: True,
        _handle_list_courses,
    ),
    # 4. Bare course load - "загрузи <name>" with no noun; the guard confirms
    #    the spoken name resolves to a real course before routing.
    (_LOAD_BARE_RE, _bare_load_guard, _handle_load_bare),

    # Phase 6 (dormant) - _handle_session_summary is defined above but
    # intentionally NOT routed yet: it overlaps with the cross-session
    # memory summary.
)


def route(agent: "AgentThread", utterance: str) -> bool:
    """Check an ordered table of (regex, guard, handler) pairs.

    On the first match whose guard also passes, calls handler(agent, utterance)
    and returns True.  Returns False when nothing matched (caller should treat
    utterance as a normal question).

    Also handles the _awaiting_course_name state: if the agent is waiting for
    a course name after a bare "загрузи курс", the entire utterance is routed
    to the load handler regardless of regex matching.
    """
    global _awaiting_course_name

    # Awaiting-name state bypasses the table — any utterance is treated as a
    # course name until _handle_load_subject clears the flag.
    if _awaiting_course_name:
        _handle_load_subject(agent, utterance)
        return True

    stripped = utterance.strip()
    for pattern, guard, handler in _ROUTE_TABLE:
        if pattern.search(stripped) and guard(stripped):
            log(_COMPONENT, f"routed to {handler.__name__!r}: {stripped[:60]!r}")
            handler(agent, utterance)
            return True
    return False
