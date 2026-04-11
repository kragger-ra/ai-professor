"""
Humor Engine — British deadpan humor for AI Professor.
Generates jokes via separate LLM call with few-shot examples.
"""

import os
import re
import random
import litellm
from typing import Optional

HUMOR_MODEL = os.getenv("CORE_LLM_MODEL_NAME", "mistral/mistral-large-latest")

# Parameters
HUMOR_PROBABILITY = 0.07       # 7% chance per response
HUMOR_COOLDOWN = 8             # minimum 8 responses between jokes
HUMOR_MAX_WORDS = 25           # max words in a joke
HUMOR_TEMPERATURE = 0.9        # high for variety

# Cooldown counter (module level)
_responses_since_last_humor = 0
_last_humor_type = None

# 9 humor types with weights
HUMOR_TYPES = {
    "understatement":           0.18,
    "confession":               0.18,
    "wholesome_absurd":         0.12,
    "pedantic":                 0.12,
    "non_sequitur":             0.08,
    "affectionate_tech":        0.10,
    "rhetorical_disappointment": 0.08,
    "backhanded":               0.06,
    "philosophical":            0.08,
}

HUMOR_TYPE_DESCRIPTIONS = {
    "understatement": (
        "POLITE UNDERSTATEMENT — преуменьши через вежливость. "
        "Чем хуже ситуация — тем мягче формулировка. "
        "Используй многоточие перед ключевым словом."
    ),
    "confession": (
        "LESSON-TO-CONFESSION — начни как авторитет, уверенно. "
        "Потом съедь в личное признание, подрывающее авторитет. "
        "Вернись к теме фразой типа 'но теория безупречная' или 'но вы — делайте'."
    ),
    "wholesome_absurd": (
        "WHOLESOME → ABSURD — тёплое ободряющее начало, "
        "потом поворот в неожиданно честное или абсурдное. "
        "Тон НЕ меняется. Без dark — только absurd."
    ),
    "pedantic": (
        "PEDANTIC PRECISION — строгий академический язык "
        "применённый к бытовой или абсурдной ситуации. "
        "Несоразмерность инструмента и объекта."
    ),
    "non_sequitur": (
        "GENTLEMANLY NON SEQUITUR — абсолютно не связанное замечание "
        "вставленное между двумя серьёзными мыслями. "
        "Без маркеров перехода. Без возвращения к вставке."
    ),
    "affectionate_tech": (
        "AFFECTIONATE SARCASM — сарказм направлен на ТЕХНОЛОГИИ и ситуации, "
        "НИКОГДА на студента. Docker, pip, git — объекты сарказма. "
        "Интонация тёплая, слова колкие."
    ),
    "rhetorical_disappointment": (
        "RHETORICAL DISAPPOINTMENT — наигранное разочарование в технологиях, "
        "документации, инструментах. НЕ в студенте. "
        "Театральное, обе стороны понимают что наигранно."
    ),
    "backhanded": (
        "BACKHANDED ENCOURAGEMENT — комплимент с подвохом. "
        "Похвалили или поддели? И то и другое. "
        "Используй ТОЛЬКО для знакомых студентов."
    ),
    "philosophical": (
        "PHILOSOPHICAL DRIFT — простой вопрос запускает "
        "неожиданно глубокое философское отступление. "
        "Уходишь слишком далеко, осознаёшь, возвращаешься к теме."
    ),
}

try:
    from agent.humor_examples import HUMOR_EXAMPLES
except ImportError:
    print("[HUMOR] humor_examples.py not found, humor disabled")
    HUMOR_EXAMPLES = {}


def should_inject_humor(
    meta_result: dict,
    student_msg: str,
    student_interactions: int = 0,
    response_length: int = 0,
) -> bool:
    """Check if humor should be injected. Double gate: random + appropriateness."""
    global _responses_since_last_humor
    _responses_since_last_humor += 1

    if _responses_since_last_humor < HUMOR_COOLDOWN:
        return False

    if random.random() > HUMOR_PROBABILITY:
        return False

    if response_length < 50:
        return False

    mood = meta_result.get("mood", "спокоен")
    request_type = meta_result.get("request_type", "")

    if mood in ("раздражён", "растерян"):
        return False
    if request_type in ("жалоба", "техпомощь"):
        return False
    if any(w in student_msg.lower() for w in [
        "не работает", "ошибка", "помогите", "не понимаю",
        "сломал", "падает", "краш", "баг", "error", "fail",
    ]):
        return False

    if student_interactions < 2:
        return False

    return True


def select_humor_type(
    student_interactions: int = 0,
    response_word_count: int = 0,
) -> str:
    """Select humor type with constraints."""
    global _last_humor_type

    available = dict(HUMOR_TYPES)

    # backhanded only for familiar students (3+ interactions)
    if student_interactions < 3:
        weight = available.pop("backhanded", 0)
        if "confession" in available:
            available["confession"] += weight

    # non_sequitur only for long responses (60+ words)
    if response_word_count < 60:
        weight = available.pop("non_sequitur", 0)
        if "understatement" in available:
            available["understatement"] += weight

    # Don't repeat type twice in a row
    if _last_humor_type and _last_humor_type in available and len(available) > 1:
        weight = available.pop(_last_humor_type)
        per_type = weight / len(available)
        for k in available:
            available[k] += per_type

    types = list(available.keys())
    weights = [available[t] for t in types]
    chosen = random.choices(types, weights=weights, k=1)[0]

    _last_humor_type = chosen
    return chosen


def generate_humor(topic: str, humor_type: str) -> Optional[str]:
    """Generate a joke via separate LLM call with few-shot examples."""
    examples = HUMOR_EXAMPLES.get(humor_type, [])
    description = HUMOR_TYPE_DESCRIPTIONS.get(humor_type, "")

    if not examples:
        print(f"[HUMOR] No examples for type '{humor_type}', skipping")
        return None

    examples_text = "\n".join(f"  {i+1}. {ex}" for i, ex in enumerate(examples))

    prompt = f"""Ты — преподаватель IT-курса с сухим британским чувством юмора.
Ты никогда не шутишь. Ты говоришь правду ровным тоном. Люди сами решают, смешно или нет.

Приём: {description}

Вот {len(examples)} примеров этого приёма — изучи стиль, ритм, длину, структуру.
НЕ копируй их. Создай НОВУЮ фразу в точно таком же стиле.

Примеры:
{examples_text}

Тема для новой фразы: {topic}

Правила:
- Максимум {HUMOR_MAX_WORDS} слов
- Связана с темой "{topic}"
- Тот же ритм и структура что в примерах выше
- Не начинай с "Кстати" или "К слову"
- Не объясняй что это шутка
- Не ставь "ха-ха", скобки, смайлы
- Русский язык, допустима одна английская вставка (well, technically, fair enough)
- Если не придумал уместное — ответь только словом SKIP

Только фразу, без кавычек:"""

    try:
        kwargs = {
            "model": HUMOR_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 80,
            "temperature": HUMOR_TEMPERATURE,
        }
        api_base = os.getenv("CORE_LLM_API_BASE")
        if api_base and api_base != "NONE":
            kwargs["api_base"] = api_base

        response = litellm.completion(**kwargs)
        result = response.choices[0].message.content.strip().strip('"\'')

        if not result or "SKIP" in result:
            return None
        if len(result.split()) > HUMOR_MAX_WORDS + 5:
            return None
        if len(result) < 10:
            return None

        bad_patterns = ["ха-ха", "хах", "лол", "шутка", "кстати говоря",
                        "😄", "))", "смешно", "анекдот", "прикол"]
        if any(p in result.lower() for p in bad_patterns):
            return None

        print(f"[HUMOR] Generated ({humor_type}): '{result}'")
        return result

    except Exception as e:
        print(f"[HUMOR] Generation error: {e}")
        return None


def inject_humor_into_response(response_text: str, humor_line: str) -> str:
    """Insert joke into response — in the middle, between semantic blocks."""
    sentences = re.split(r'(?<=[.!?])\s+', response_text.strip())

    if len(sentences) >= 4:
        insert_pos = 2
        sentences.insert(insert_pos, humor_line)
    elif len(sentences) >= 2:
        sentences.insert(1, humor_line)
    else:
        sentences.append(humor_line)

    return " ".join(sentences)


def try_humor(
    response_text: str,
    topic: str,
    meta_result: dict,
    student_msg: str,
    student_interactions: int = 0,
) -> str:
    """Main entry point. Called after response generation, before TTS split.
    Returns response with or without humor."""
    global _responses_since_last_humor

    word_count = len(response_text.split())

    if not should_inject_humor(meta_result, student_msg, student_interactions, len(response_text)):
        return response_text

    humor_type = select_humor_type(student_interactions, word_count)
    humor_line = generate_humor(topic, humor_type)

    if humor_line is None:
        return response_text

    _responses_since_last_humor = 0

    result = inject_humor_into_response(response_text, humor_line)
    return result
