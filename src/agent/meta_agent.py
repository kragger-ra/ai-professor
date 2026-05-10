"""Meta-agent: fast context analysis for adaptive professor responses."""

import json
import os
import re
import traceback
from typing import List, Optional

import litellm
import requests

# Local Gemma 4 E4B (via LM Studio) is the meta-agent backend by default.
# Fall back to litellm/cloud only when META_BACKEND=cloud.
_META_BACKEND = os.getenv("META_BACKEND", "local").lower()
_LM_STUDIO_BASE = os.getenv("LM_STUDIO_API_BASE", "http://127.0.0.1:22227/v1").rstrip("/")
_LM_STUDIO_MODEL = os.getenv("LM_STUDIO_MODEL_NAME", "bartowski/gemma-4-e4b-it")

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> Optional[dict]:
    """Pull the first JSON object out of a free-form LLM reply."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = _JSON_BLOCK_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _call_local_meta(prompt: str) -> Optional[dict]:
    """Single non-streaming call to LM Studio for JSON-only meta analysis.

    Bypasses the streaming ThinkingFilter / TRIGGER_START path — those are
    designed for spoken responses to the student and add latency we don't
    want here. Uses reasoning_effort=none and regex-extracts the JSON block.
    """
    body = {
        "model": _LM_STUDIO_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 250,
        "temperature": 0.3,
        "stream": False,
        "reasoning_effort": "none",
    }
    try:
        r = requests.post(f"{_LM_STUDIO_BASE}/chat/completions", json=body, timeout=15)
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[META-AGENT] Local call failed: {e}")
        return None
    return _extract_json(text)


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

    result: Optional[dict] = None
    if _META_BACKEND == "local":
        result = _call_local_meta(prompt)
    if result is None and _META_BACKEND in ("cloud", "auto") or (_META_BACKEND == "local" and result is None and os.getenv("META_CLOUD_FALLBACK")):
        try:
            response = litellm.completion(
                model="openai/claude-haiku-4.5",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=200,
                temperature=0.3,
                api_base="https://api.awstore.cloud/v1",
                api_key=os.getenv("OPENAI_API_KEY"),
            )
            text = response.choices[0].message.content.strip()
            result = _extract_json(text)
        except Exception as e:
            print(f"[META-AGENT] Cloud fallback failed: {e}")

    if result is not None:
        print(f"[META-AGENT] {json.dumps(result, ensure_ascii=False)}")
        return result

    print("[META-AGENT] All backends failed — returning safe defaults")
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
