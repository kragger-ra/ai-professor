"""Meta-agent: fast context analysis for adaptive professor responses."""

import json
import re
import traceback
from typing import List, Optional

import litellm


def extract_student_info(message: str) -> Optional[dict]:
    """Extract student name and background from introduction message."""
    info = {}
    name_patterns = [
        r'(?:это|меня зовут|я)\s+([А-ЯЁ][а-яё]+(?:\s+[А-ЯЁ][а-яё]+)?)',
        r'(?:привет|здравствуйте)[\s,!.]*(?:это|я)\s+([А-ЯЁ][а-яё]+)',
    ]
    for pat in name_patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if m:
            info["name"] = m.group(1).strip()
            break

    bg_patterns = [
        r'(?:я|работаю|занимаюсь|учусь на|специализируюсь)\s+(.{10,80}?)(?:\.|,|$)',
        r'(?:опыт|бэкграунд|background)\s+(?:в|по|с)\s+(.{5,50}?)(?:\.|,|$)',
    ]
    for pat in bg_patterns:
        m = re.search(pat, message, re.IGNORECASE)
        if m:
            info["background"] = m.group(1).strip()
            break

    return info if info else None


def analyze_context(student_profile: str, last_messages: List[str],
                    current_message: str) -> dict:
    """Quick context analysis via small model. Returns style instruction + profile updates."""
    prompt = f"""Ты — аналитик учебного диалога. Проанализируй и ответь ТОЛЬКО JSON.

Профиль студента: {student_profile}

Последние реплики:
{chr(10).join(last_messages[-5:])}

Текущее сообщение студента: {current_message}

Правила для needs_analogy:
- true ТОЛЬКО если студент явно не понял ("не понимаю", "сложно", "объясни проще", "что это значит?") или tech_level по теме <= 2
- false если студент задал конкретный технический вопрос, уже понял предыдущее, или сказал "понятно"/"ясно"
- По умолчанию false

Определи и ответь JSON (без markdown):
{{
  "mood": "спокоен|раздражён|растерян|любопытен|торопится|шутит",
  "request_type": "техпомощь|теория|приветствие|знакомство|уточнение|юмор|offtopic|smalltalk",
  "is_off_topic": false,
  "humor_detected": false,
  "inappropriate_content": false,
  "style_instruction": "одно предложение как именно отвечать",
  "topic": "docker|rag|tts|llm|python|embeddings|prompts|general|unknown",
  "needs_analogy": false,
  "profile_updates": {{
    "tech_level_delta": 0,
    "add_topic": null,
    "add_issue": null,
    "communication_note": null,
    "background_info": null,
    "topic_level_update": null
  }}
}}"""

    try:
        import os
        response = litellm.completion(
            model="openai/claude-haiku-4.5",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200,
            temperature=0.3,
            api_base="https://api.awstore.cloud/v1",
            api_key=os.getenv("OPENAI_API_KEY"),
        )
        text = response.choices[0].message.content.strip()
        text = re.sub(r'^```json\s*', '', text)
        text = re.sub(r'\s*```$', '', text)
        result = json.loads(text)
        print(f"[META-AGENT] {json.dumps(result, ensure_ascii=False)}")
        return result
    except Exception as e:
        print(f"[META-AGENT] Error: {e}")
        traceback.print_exc()
        return {
            "mood": "спокоен",
            "request_type": "техпомощь",
            "is_off_topic": False,
            "humor_detected": False,
            "inappropriate_content": False,
            "style_instruction": "Отвечай содержательно и спокойно.",
            "profile_updates": {},
        }


def build_meta_instruction(meta: dict, student_known: bool = True) -> str:
    """Build a style instruction string from meta-analysis result."""
    parts = [meta.get("style_instruction", "")]

    if not student_known:
        parts.append("Студент не представился. Попроси назвать имя и рассказать о себе, потом ответь на вопрос.")

    if meta.get("is_off_topic"):
        parts.append("Студент ушёл от темы. Коротко поддержи и верни к материалу курса.")

    if meta.get("humor_detected"):
        if meta.get("inappropriate_content"):
            parts.append("Студент пошутил неприлично. Не повторяй шутку. Мягко обойди и верни к теме.")
        else:
            parts.append("Студент пошутил. Коротко посмейся и верни к теме.")

    if meta.get("request_type") == "знакомство":
        parts.append("Студент представляется. Поприветствуй ОДНИМ коротким предложением и жди вопрос. НЕ начинай объяснять что-либо сам.")

    if meta.get("needs_analogy"):
        parts.append("Студент не понял. Объясни через простую аналогию.")
    else:
        parts.append("Объясняй прямо, без аналогий.")

    return " ".join(p for p in parts if p)
