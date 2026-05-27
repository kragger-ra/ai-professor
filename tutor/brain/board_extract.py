"""Extract [BOARD-*] items from the professor's answer.

Strategy: the streaming TTS call runs with ``stop=["---BOARD---"]`` so the
spoken text never leaks the marker or any tags. After ``finish_generation``
the agent makes a short, focused secondary LLM call asking the model to
re-emit ONLY the board block for the answer it just produced; this runs on
the daemon ``generate`` thread, off the audio critical path.
"""
from __future__ import annotations

import re
from typing import List, Tuple

from tutor.brain.llm import stream_fast
from tutor.util import log

_COMPONENT = "board_ext"

_KNOWN_KINDS = ("FORMULA", "TERM", "FACT", "CODE", "MERMAID")
_BOARD_BLOCK_RE = re.compile(
    r"\[BOARD-(" + "|".join(_KNOWN_KINDS) + r")\](.*?)\[/BOARD-\1\]",
    re.IGNORECASE | re.DOTALL,
)

_EXTRACTION_SYSTEM = (
    "Ты — пост-процессор для интерактивной учебной доски. Тебе дают вопрос "
    "студента и устный ответ ИИ-профессора. Твоя задача — выделить из ответа "
    "формулы, ключевые термины с определением, важные факты и схемы, и "
    "вернуть ТОЛЬКО блок тегов для доски, БЕЗ устного текста и БЕЗ маркера "
    "`---BOARD---`. Используй ровно эти теги:\n"
    "  [BOARD-FORMULA]LaTeX без $[/BOARD-FORMULA]\n"
    "  [BOARD-TERM]имя: определение[/BOARD-TERM]\n"
    "  [BOARD-FACT]важный тезис[/BOARD-FACT]\n"
    "  [BOARD-CODE]сниппет[/BOARD-CODE]\n"
    "  [BOARD-MERMAID]Mermaid-код диаграммы[/BOARD-MERMAID]\n"
    "Каждый тег — на своей строке. Если в ответе нечего выносить на доску, "
    "верни пустой ответ. Не пересказывай вопрос, не объясняй своё решение, "
    "никаких рассуждений — только теги или пусто."
)


def extract_board_items(question: str, answer_text: str,
                        max_tokens: int = 400) -> List[Tuple[str, str]]:
    """Return [(kind, body), ...] parsed from a board-extraction LLM call.

    ``kind`` is lowercase (``"formula"``, ``"term"``, ``"fact"``, ``"code"``).
    Returns an empty list when the LLM produces no tags or the call fails —
    the caller should not raise.
    """
    if not answer_text.strip():
        return []
    user_msg = (
        f"Вопрос студента:\n{question.strip()}\n\n"
        f"Устный ответ профессора:\n{answer_text.strip()}\n\n"
        "Верни только теги для доски (или пустой ответ, если выносить нечего)."
    )
    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM},
        {"role": "user", "content": user_msg},
    ]
    # Use the raw token stream (stream_fast) — NOT stream_response_sentences,
    # whose _scrub() strips exactly the [BOARD-*] tags we are trying to parse.
    collected: List[str] = []
    try:
        for token in stream_fast(
            messages, temperature=0.2, max_tokens=max_tokens,
        ):
            collected.append(token)
    except Exception as exc:
        log(_COMPONENT, f"extraction call failed: {type(exc).__name__}: {exc}")
        return []

    raw = "".join(collected).strip()
    if not raw:
        return []
    return parse_board_block(raw)


def parse_board_block(text: str) -> List[Tuple[str, str]]:
    """Pure regex parse — exposed for unit testing."""
    items: List[Tuple[str, str]] = []
    for kind, body in _BOARD_BLOCK_RE.findall(text):
        body_clean = body.strip()
        if body_clean:
            items.append((kind.lower(), body_clean))
    return items
