"""Prompt constructor for professor agent response generation.

Creates the system prompt and message list for the LLM.
Depends only on: stdlib, pyyaml, and tutor.brain.course.
"""

import os
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from tutor.brain import course as _course

# Path to the professor personalities YAML — anchored at repo root.
_PERSONALITIES_PATH = (
    Path(__file__).resolve().parents[2] / "resources" / "Prompts" / "personalities_professor.yml"
)

# Cache for the loaded YAML so we don't re-read on every call.
_personalities_cache: Optional[dict] = None


def _load_personalities() -> dict:
    global _personalities_cache
    if _personalities_cache is None:
        with open(str(_PERSONALITIES_PATH), "r", encoding="utf-8") as f:
            _personalities_cache = yaml.safe_load(f) or {}
    return _personalities_cache


def _load_personality(personality_key: str) -> str:
    """Return the prompt string for the given personality key."""
    data = _load_personalities()
    return data.get(personality_key, "")


PROFESSOR_VOICE_RULES = (
    "Ты отвечаешь ГОЛОСОМ. Студент слушает, не читает. "
    "Варьируй длину ответов. Не заканчивай каждую реплику вопросом. "
    "Тег эмоции в конце — не произносить вслух."
)

_USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() in ("true", "1", "yes")
_TRIGGER_INSTRUCTION = (
    "\n\nОБЯЗАТЕЛЬНО: Начинай КАЖДЫЙ ответ со слова TRIGGER_START — без исключений.\n"
    "Всё до TRIGGER_START не будет показано студенту.\n"
    "Пример: TRIGGER_START Нейронная сеть — это вычислительная модель."
    if _USE_LOCAL_LLM else ""
)

# PROFESSOR_GOAL is built at import time (env vars are stable per process).
PROFESSOR_GOAL = (
    f"Ты — ИИ-профессор. МУЖЧИНА. Мужской род (сказал, объяснил, готов).\n"
    f"{PROFESSOR_VOICE_RULES}\n"
    "Русский язык. НЕ добавляй теги эмоций, эмодзи или слова-настроения — "
    "ни в скобках, ни в конце, нигде: TTS озвучит их буквально.\n"
    "Не повторяй слова студента. Не пересказывай вопрос. Сразу отвечай по сути.\n"
    "ЗАПРЕЩЕНО начинать ответ с \"Добрый день\", \"Привет\", \"Здравствуйте\" — "
    "если в чате уже было приветствие. Сразу к делу.\n"
    f"{_TRIGGER_INSTRUCTION}\n"
    "АДАПТАЦИЯ ПОД СТУДЕНТА: по умолчанию отвечай кратко и разговорно — "
    "3-4 коротких предложения, это устная речь. Сам следи за студентом по "
    "ходу диалога и подстраивайся: если он путается, просит объяснить проще, "
    "отвечает односложно или говорит бытовым языком — упрощай, дроби на шаги, "
    "без терминов, как новичку. Если просит подробнее, задаёт глубокие "
    "вопросы или сам свободно владеет терминологией — отвечай развёрнуто и "
    "профессионально. На явные просьбы о формате реагируй сразу.\n"
    "ИСТОЧНИКИ ЗНАНИЙ:\n"
    "- Материалы курса (RAG) — основной источник. Если информация найдена — используй.\n"
    "- Собственные знания — если в материалах курса нет. Предупреди: "
    "\"Этого нет в наших материалах, но из общих знаний...\"\n"
    "- Если вопрос совсем не по теме ИИ/программирования — коротко ответь и верни к курсу."
)


def construct_prompt(
    rag_context: Optional[str],
    personality_key: str,
    student_profile: str = "",
    meta_instruction: str = "",
    rag_score: float = 0.0,
    past_sessions: str = "",
) -> str:
    """Build system prompt from personality template + RAG + student context.

    Args:
        rag_context:      Retrieved course material text (may be empty/None).
        personality_key:  Key in personalities_professor.yml, e.g. "professor_simpler".
        student_profile:  Pre-formatted profile string from StudentProfileManager.
        meta_instruction: Short directive from the meta-agent.
        rag_score:        L2 distance from FAISS (lower = more relevant).
        past_sessions:    Thesis-level summary of earlier sessions (may be empty).
    """
    system_template = _load_personality(personality_key)
    # Substitute {COURSE_*} placeholders with the active course config.
    try:
        system_template = _course.get_current().render(system_template)
    except Exception:
        # Course config is best-effort; never block prompt construction on it.
        pass

    # Annotate RAG context based on confidence (L2 distance: lower = better).
    if rag_context:
        if rag_score < 0.8:
            rag_header = "## Контекст из материалов курса (высокая релевантность):"
        elif rag_score < 1.2:
            rag_header = "## Контекст из материалов курса (частичное совпадение — дополни из своих знаний):"
        else:
            rag_header = "## Контекст из материалов курса (низкая релевантность — опирайся на свои знания):"
        final_rag_context = f"\n\n{rag_header}\n{rag_context}"
    else:
        final_rag_context = ""

    student_section = (
        "\n\n## Профиль студента:\n" + student_profile if student_profile else ""
    )
    past_sessions_section = (
        "\n\n## Из прошлых занятий:\n" + past_sessions
        + "\n(Можешь ссылаться на это: «в прошлый раз мы разбирали...»)"
        if past_sessions else ""
    )
    meta_section = (
        "\n\n## Стиль текущего ответа:\n" + meta_instruction if meta_instruction else ""
    )
    return (system_template + final_rag_context + student_section
            + past_sessions_section + meta_section)


def create_chat_from_prompt(prompt: str, role: str = "system") -> List[Dict]:
    """Wrap a prompt string in a one-element OpenAI-format message list."""
    return [{"role": role, "content": prompt}]
