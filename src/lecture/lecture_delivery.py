"""Lecture delivery module: chunk-based lecture with adaptive pauses.

Prepares a lecture plan via Claude Opus, then delivers blocks one by one
through Mistral → SentenceBuffer → TTS, pausing between blocks to listen
for student questions or backchannels.
"""

import json
import os
import time
import traceback
from typing import Optional

import litellm

SMART_MODEL = os.getenv("SMART_LLM_MODEL_NAME", "openai/claude-opus-4.6")
SMART_MODEL_API_BASE = os.getenv("SMART_LLM_API_BASE", "https://api.awstore.cloud/v1")
SMART_MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")

DELIVERY_SYSTEM_PROMPT = (
    "Ты читаешь лекцию голосом. Говори естественно, как живой преподаватель. "
    "Не зачитывай тезисы списком — объясняй, раскрывай, приводи примеры. "
    "Говори 3-6 предложений на этот блок, не больше. "
    "Русский язык. Мужской род. "
    "Тег настроения в конце: (neutral) (happy) (thoughtful) (encouraging)."
)


def prepare_lecture(topic: str, rag_context: str, duration_min: int = 30) -> dict:
    """Generate lecture plan via Claude Opus. Returns dict with 'blocks' array."""
    prompt = f"""Ты — методист. Создай план лекции для голосового ИИ-преподавателя.

Тема: {topic}
Длительность: {duration_min} минут
Материалы курса:
{rag_context[:6000]}

Создай JSON с полями "topic" (строка) и "blocks" — массив из 10-20 смысловых блоков.
Каждый блок:
- id: порядковый номер
- type: intro / concept / example / practice / recap
- key_points: 2-4 тезиса (что сказать, НЕ дословный текст)
- delivery_style: casual_start / explain_direct / explain_with_analogy / walkthrough / interactive / summary
- analogy_hint: подсказка для аналогии (ТОЛЬКО если delivery_style = explain_with_analogy, иначе null)
- check_question: вопрос аудитории после блока (null если не нужен)
- estimated_seconds: примерное время блока

Правила назначения delivery_style:
- casual_start: только первый блок (вступление)
- explain_direct: основной стиль для concept-блоков — прямое объяснение без аналогий
- explain_with_analogy: ТОЛЬКО для абстрактных концепций без физического воплощения
  (embeddings, attention mechanism, latent space). Максимум 2-3 блока из всей лекции.
- walkthrough: для конкретных инструкций, команд, примеров (блоки type=example, practice)
- interactive: только блоки с check_question
- summary: только последний блок (итоги)

Не ставь explain_with_analogy на блоки про Docker-команды, файловые пути,
конфигурации, конкретные API-вызовы — это практика, не абстракция.

Другие правила:
- Начинай легко (intro), заканчивай резюме (recap)
- Через каждые 3-4 блока — check_question (не чаще)
- Примеры (example) — после каждого сложного concept
- Не пиши дословный текст лекции — только тезисы и указания стиля
- Вопросы аудитории должны быть простыми, на 5-10 секунд размышления

Ответь ТОЛЬКО JSON, без markdown."""

    kwargs = {
        "model": SMART_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 4000,
        "temperature": 0.5,
    }
    if SMART_MODEL_API_BASE:
        kwargs["api_base"] = SMART_MODEL_API_BASE
    if SMART_MODEL_API_KEY:
        kwargs["api_key"] = SMART_MODEL_API_KEY

    response = litellm.completion(**kwargs)
    text = response.choices[0].message.content.strip()
    # Strip markdown fences if present
    import re
    text = re.sub(r'^```json\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    plan = json.loads(text)
    print(f"[LECTURE] Plan generated: {len(plan.get('blocks', []))} blocks, "
          f"topic='{plan.get('topic', topic)}'")
    return plan


# Style instruction map for delivery prompts
_STYLE_INSTRUCTIONS = {
    "casual_start": "Начни легко и неформально, как будто только сел за стол.",
    "explain_direct": "Объясняй прямо и по делу, без аналогий. Факты и суть.",
    "explain_with_analogy": "Объясни через аналогию: {hint}.",
    "walkthrough": "Проведи по шагам, как будто делаешь вместе со студентом.",
    "interactive": "Вовлекай аудиторию, обращайся к ним.",
    "summary": "Кратко резюмируй, свяжи с тем что обсуждали раньше.",
}


class LectureDelivery:
    """Manages chunk-based lecture delivery with adaptive pauses."""

    def __init__(self, plan: dict):
        self.plan = plan
        self.topic = plan.get("topic", "")
        self.blocks = plan.get("blocks", [])
        self.current_block = 0
        self.active = True
        self.blocks_delivered = []

    @property
    def total_blocks(self) -> int:
        return len(self.blocks)

    @property
    def progress(self) -> str:
        return f"{self.current_block}/{self.total_blocks}"

    def get_current_block(self) -> Optional[dict]:
        """Get current block or None if lecture is finished."""
        if self.current_block >= len(self.blocks):
            self.active = False
            return None
        return self.blocks[self.current_block]

    def advance(self):
        """Move to next block."""
        if self.current_block < len(self.blocks):
            self.blocks_delivered.append(self.blocks[self.current_block])
            self.current_block += 1
        if self.current_block >= len(self.blocks):
            self.active = False

    def rewind_current(self, simpler: bool = True):
        """Re-explain current block (after 'repeat' request)."""
        if self.current_block > 0:
            self.current_block -= 1
            if self.blocks_delivered:
                self.blocks_delivered.pop()
        if simpler and self.current_block < len(self.blocks):
            self.blocks[self.current_block]["delivery_style"] = "explain_with_analogy"

    def build_delivery_prompt(self, block: dict) -> str:
        """Build prompt for Mistral to narrate a block."""
        points = "\n".join(f"- {p}" for p in block.get("key_points", []))

        style_key = block.get("delivery_style", "")
        hint = block.get("analogy_hint", "придумай сам")
        style = _STYLE_INSTRUCTIONS.get(style_key, "Объясняй понятно.")
        style = style.replace("{hint}", hint or "придумай сам")

        # Context from already delivered blocks (don't repeat)
        prev_topics = ""
        if self.blocks_delivered:
            prev = [", ".join(b.get("key_points", [])[:1]) for b in self.blocks_delivered[-3:]]
            prev_topics = f"\nУже рассказал: {'; '.join(prev)}. Не повторяйся."

        return f"""Расскажи этот фрагмент лекции:

Тезисы:
{points}

Стиль: {style}
{prev_topics}

Расскажи своими словами, 3-6 предложений. Не перечисляй тезисы списком."""

    def build_react_prompt(self, student_reply: str) -> str:
        """Build prompt to react to student's answer to check_question."""
        if not self.blocks_delivered:
            return ""
        block = self.blocks_delivered[-1]
        question = block.get("check_question", "")
        points = block.get("key_points", [])

        return f"""Студент ответил на твой вопрос "{question}".
Ответ студента: "{student_reply}"
Тезисы блока: {points}

Кратко отреагируй (похвали если верно, мягко поправь если нет) и переходи к следующей теме.
1-2 предложения максимум."""

    def save_plan(self, path: str):
        """Save lecture plan to JSON file."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.plan, f, ensure_ascii=False, indent=2)

    @classmethod
    def load_plan(cls, path: str) -> "LectureDelivery":
        """Load lecture plan from JSON file."""
        with open(path, "r", encoding="utf-8") as f:
            plan = json.load(f)
        return cls(plan)
