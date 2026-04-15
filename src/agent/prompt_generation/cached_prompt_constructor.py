"""Cached prompt constructor for LM Studio with Prompt Caching.

Splits the prompt into a stable prefix (cached by LM Studio's KV cache)
and a dynamic suffix that changes per request. The key principle:
everything that does NOT change between requests goes at the beginning;
everything that changes goes strictly at the end.

LM Studio (llama.cpp) caches computed key-value pairs by token prefix matching.
If request B starts with the same tokens as request A, those tokens are
not reprocessed — giving ~6-20x TTFT speedup.
"""

import time
from typing import Dict, List, Optional, Tuple

from config_schema.general import get_name, get_secret
from data_flow.ctx_handler import CtxHandler
from utils.format_helper import format_events_for_rag, format_events_with_roles
from utils.prompt_helper import prompt_load

SELF_NAME = get_name()

PROFESSOR_VOICE_RULES = (
    "Ты отвечаешь ГОЛОСОМ. Студент слушает, не читает. "
    "Варьируй длину ответов. Не заканчивай каждую реплику вопросом. "
    "Тег эмоции в конце — не произносить вслух."
)

RESPONSE_TRIGGER = "TRIGGER_START"

PROFESSOR_GOAL_CACHED = f"""Ты — {SELF_NAME}. МУЖЧИНА. Мужской род (сказал, объяснил, готов).
{PROFESSOR_VOICE_RULES}
Русский язык. Тег настроения в конце реплики: (neutral) (happy) (thoughtful) (encouraging).
Не повторяй слова студента. Не пересказывай вопрос. Сразу отвечай по сути.
ЗАПРЕЩЕНО начинать ответ с "Добрый день", "Привет", "Здравствуйте" — если в чате уже было приветствие. Сразу к делу.

ОБЯЗАТЕЛЬНО: Начинай КАЖДЫЙ ответ со слова {RESPONSE_TRIGGER} — без исключений.
Всё до {RESPONSE_TRIGGER} не будет показано студенту.
Пример: {RESPONSE_TRIGGER} Нейронная сеть — это вычислительная модель. (thoughtful)

ИСТОЧНИКИ ЗНАНИЙ:
- Материалы курса (RAG) — основной источник. Если информация найдена — используй.
- Собственные знания — если в материалах курса нет. Предупреди: "Этого нет в наших материалах, но из общих знаний..."
- Если вопрос совсем не по теме ИИ/программирования — коротко ответь и верни к курсу."""


class CachedPromptConstructor:
    """Prompt constructor optimized for LM Studio KV cache.

    Architecture (matches NetTyan's proven approach):

        [CACHED PREFIX — stable between requests]
          system: personality + voice rules + goal (~2000 tokens)
          system: course description / base materials (~1000 tokens)
          system: student profile (~200 tokens, updates rarely)

        [DYNAMIC SUFFIX — appended fresh each request]
          user: RAG context for current query (~1000 tokens)
          user/assistant: last few chat messages (~500 tokens)
          user: current student question

    The prefix is built once and only rebuilt when personality or
    student profile changes. LM Studio auto-caches the matching prefix.
    """

    def __init__(self, ctx_handler: CtxHandler):
        self.ctx_handler = ctx_handler
        self._cached_prefix: Optional[List[Dict]] = None
        self._prefix_version: int = 0
        self._last_student_profile: str = ""
        self._last_personality_key: str = ""

    def _build_system_prompt(self, ctx_swarm: dict) -> str:
        """Build the static system prompt (personality + rules)."""
        personality_key = ctx_swarm["states"].get("personality", "professor_default")
        personality_file = (
            "personalities_professor" if "professor" in personality_key
            else "personalities"
        )
        system_template = prompt_load(personality_file, personality_key)
        return system_template

    def build_cached_prefix(
        self,
        ctx_swarm: dict,
        student_profile: str = "",
    ) -> List[Dict]:
        """Build the stable (cacheable) part of the prompt.

        Only rebuild if personality or student profile changed.
        Returns list of OpenAI-format messages.
        """
        personality_key = ctx_swarm["states"].get("personality", "professor_default")

        # Check if rebuild needed
        if (
            self._cached_prefix is not None
            and self._last_personality_key == personality_key
            and self._last_student_profile == student_profile
        ):
            return self._cached_prefix

        system_prompt = self._build_system_prompt(ctx_swarm)
        goal_section = f"\n\n# === Инструкция ===\n{PROFESSOR_GOAL_CACHED}"

        prefix = [
            {"role": "system", "content": system_prompt + goal_section},
        ]

        # Student profile as a separate system message (stable between requests)
        if student_profile:
            prefix.append({
                "role": "system",
                "content": f"## Профиль студента:\n{student_profile}",
            })

        self._cached_prefix = prefix
        self._last_personality_key = personality_key
        self._last_student_profile = student_profile
        self._prefix_version += 1

        return self._cached_prefix

    def build_dynamic_suffix(
        self,
        rag_context: str = "",
        rag_score: float = float("inf"),
        chat_messages: Optional[List[Dict]] = None,
        meta_instruction: str = "",
    ) -> List[Dict]:
        """Build the dynamic (non-cached) part of the prompt.

        This goes at the END so the cached prefix stays intact.
        Returns list of OpenAI-format messages.
        """
        suffix = []

        # RAG context with confidence annotation
        if rag_context:
            if rag_score < 0.8:
                rag_header = "Контекст из материалов курса (высокая релевантность):"
            elif rag_score < 1.2:
                rag_header = "Контекст из материалов курса (частичное совпадение — дополни из своих знаний):"
            else:
                rag_header = "Контекст из материалов курса (низкая релевантность — опирайся на свои знания):"
            suffix.append({
                "role": "user",
                "content": f"## {rag_header}\n{rag_context}",
            })

        # Meta-instruction (style hint from meta-agent)
        if meta_instruction:
            suffix.append({
                "role": "system",
                "content": f"## Стиль текущего ответа:\n{meta_instruction}",
            })

        # Recent chat messages (the actual conversation)
        if chat_messages:
            for msg in chat_messages:
                suffix.append(msg)

        return suffix

    def build_full_prompt(
        self,
        ctx_swarm: dict,
        rag_context: str = "",
        rag_score: float = float("inf"),
        student_profile: str = "",
        meta_instruction: str = "",
        chat_history_limit: int = 10,
    ) -> List[Dict]:
        """Build complete prompt: cached prefix + dynamic suffix.

        Returns list of OpenAI-format messages ready for LM Studio.
        """
        # 1. Cached prefix (only rebuilt when personality/profile changes)
        prefix = self.build_cached_prefix(ctx_swarm, student_profile)

        # 2. Chat history from ctx_handler
        chat_dicts = self.ctx_handler.get_ctx_chat(
            validate=True, dict_format=True, limit=chat_history_limit
        )
        chat_messages, _ = format_events_with_roles(
            chat_dicts,
            trigger_event_id=-1,
            return_mentioned_users=True,
        )

        # 3. Dynamic suffix
        suffix = self.build_dynamic_suffix(
            rag_context=rag_context,
            rag_score=rag_score,
            chat_messages=chat_messages,
            meta_instruction=meta_instruction,
        )

        # 4. Combine: prefix + suffix
        return list(prefix) + suffix

    def invalidate_cache(self):
        """Force rebuild of cached prefix on next call."""
        self._cached_prefix = None
        self._prefix_version += 1

    def update_student_profile(self, new_profile: str):
        """Update student profile — triggers prefix rebuild on next call."""
        if new_profile != self._last_student_profile:
            self._last_student_profile = new_profile
            self._cached_prefix = None  # force rebuild
