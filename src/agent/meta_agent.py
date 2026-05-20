"""Meta-agent: fast pre-flight analysis for adaptive professor responses.

Runs ONE small-model call per Q&A and returns a slim JSON the main agent
folds into its system prompt. Seven fields, each closes a gap the main LLM
can't reliably handle from chat history alone:

  mood            tone calibration (calm / lost / curious / annoyed)
  level           1..5 comprehension of the CURRENT topic
  needs_analogy   should the answer use an everyday analogy
  stt_garbled     low confidence in transcription — ask to repeat
  ref             what 'это / он / то' references back to (or null)
  stuck_on        concept the student keeps missing (or null)
  style_hint      explicit format instruction from the student
                  ("отвечай короче но так же подробно", "без терминов",
                   "больше примеров") — short imperative or null

Defaults to gpt-5.4-nano via OpenAI for cheap ($0.0003/call). Set
META_LOCAL_MODEL to override; falls back to LM_STUDIO_MODEL_NAME.
META_BACKEND=off disables entirely (returns inert defaults, no LLM call).
"""

import json
import os
import re
import traceback
from typing import List, Optional

import litellm
import requests

# Backend modes:
#   local — POST to LM_STUDIO_API_BASE (which is OpenAI by default now)
#   cloud — litellm.completion (META_CLOUD_MODEL)
#   off   — no LLM call, returns safe defaults
_META_BACKEND = os.getenv("META_BACKEND", "local").lower()

_LM_STUDIO_BASE = os.getenv("LM_STUDIO_API_BASE", "http://127.0.0.1:22227/v1").rstrip("/")
_LM_STUDIO_API_KEY = os.getenv("LM_STUDIO_API_KEY", "")
_REASONING_EFFORT = os.getenv("LM_STUDIO_REASONING_EFFORT", "").strip()
# Meta runs on a cheap model independent of the main LLM. Default to nano.
_META_MODEL = (
    os.getenv("META_LOCAL_MODEL", "").strip()
    or os.getenv("LM_STUDIO_MODEL_NAME", "gpt-5.4-nano")
)

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


# Safe defaults — what we return when meta is disabled or all backends fail.
SAFE_DEFAULTS = {
    "mood": "спокоен",
    "level": 3,
    "needs_analogy": False,
    "stt_garbled": False,
    "ref": None,
    "stuck_on": None,
    "style_hint": None,
}


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
    """Single non-streaming call to the configured OpenAI-compatible endpoint.

    Uses META_LOCAL_MODEL (default gpt-5.4-nano) so the main lecture LLM and
    the meta-agent can live on different cost tiers.
    """
    body = {
        "model": _META_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": 200,
        "temperature": 0.2,
        "stream": False,
    }
    if _REASONING_EFFORT:
        body["reasoning_effort"] = _REASONING_EFFORT
    headers = {"Authorization": f"Bearer {_LM_STUDIO_API_KEY}"} if _LM_STUDIO_API_KEY else None
    try:
        r = requests.post(
            f"{_LM_STUDIO_BASE}/chat/completions",
            json=body, headers=headers, timeout=10,
        )
        r.raise_for_status()
        text = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"[META-AGENT] Local call failed: {e}")
        return None
    return _extract_json(text)


def extract_student_info(message: str) -> Optional[dict]:
    """Regex-only — extract student name and background from an intro message.

    Independent of the meta LLM; runs unconditionally on the first turn.
    """
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


# Prompt for the meta call. Seven fields, terse rules, hard JSON-only contract.
_META_PROMPT_TEMPLATE = """Ты — аналитик учебного диалога. Смотришь на последние реплики и определяешь по студенту семь параметров. Отвечай ТОЛЬКО валидным JSON без markdown.

Профиль студента: {profile}

Последние реплики (старые → новые):
{history}

Текущая реплика студента: {current}

Поля:
- "mood" — "спокоен" | "растерян" | "любопытен" | "раздражён"
- "level" — 1..5, насколько студент въезжает в ТЕКУЩУЮ тему (не общий уровень, а здесь и сейчас по последним 3-5 репликам)
- "needs_analogy" — true ТОЛЬКО если: студент явно не понял ("не понимаю/сложно/проще/что это значит") ИЛИ level<=2. Иначе false.
- "stt_garbled" — true если в реплике явно несвязные/несуществующие слова, ломаный русский, обрывки — STT мог накосячить. False если речь связная.
- "ref" — если в текущей реплике есть местоимение/указатель ("это / он / она / тот / та / такой") и непонятно к чему — короткое словосочетание из истории к чему отсылка. Null если ясно или нет отсылки.
- "stuck_on" — если студент уже 2+ раза за последние 5 реплик возвращается к одной концепции и явно её не схватывает — название концепции одним словом/словосочетанием. Иначе null.
- "style_hint" — если студент в текущей реплике ЯВНО даёт инструкцию о ФОРМАТЕ ответа (как именно отвечать), извлеки её одним коротким повелительным предложением. Примеры что считается style_hint: "отвечай короче, но так же подробно" → "отвечай короче, при этом сохраняй уровень подробности примеров"; "понятнее, но дольше" → "объясняй понятнее, не сокращай"; "больше примеров" → "давай больше примеров"; "без терминов" → "избегай технических терминов"; "не используй аналогии" → "отвечай без бытовых аналогий". Если студент просто задал вопрос или комментирует содержание, а не формат — null. Не выдумывай, бери только из текущей реплики.

Формат ответа (ровно эти ключи):
{{"mood":"...","level":3,"needs_analogy":false,"stt_garbled":false,"ref":null,"stuck_on":null,"style_hint":null}}"""


def analyze_context(student_profile: str, last_messages: List[str],
                    current_message: str) -> dict:
    """Run meta analysis and return a six-field dict.

    If META_BACKEND=off, returns SAFE_DEFAULTS without any LLM call (no log
    noise). On backend failure, returns SAFE_DEFAULTS with a warning.
    """
    if _META_BACKEND == "off":
        return dict(SAFE_DEFAULTS)

    history_text = "\n".join(last_messages[-5:]) if last_messages else "(нет истории)"
    prompt = _META_PROMPT_TEMPLATE.format(
        profile=student_profile or "(новый студент)",
        history=history_text,
        current=current_message or "(пусто)",
    )

    result: Optional[dict] = None
    if _META_BACKEND in ("local", "auto"):
        result = _call_local_meta(prompt)
    if result is None and _META_BACKEND in ("cloud", "auto"):
        try:
            response = litellm.completion(
                model=os.getenv("META_CLOUD_MODEL", "openai/gpt-5.4-nano"),
                messages=[{"role": "user", "content": prompt}],
                max_completion_tokens=200,
                temperature=0.2,
                api_base=os.getenv("META_CLOUD_API_BASE") or None,
                api_key=os.getenv("OPENAI_API_KEY"),
            )
            text = response.choices[0].message.content.strip()
            result = _extract_json(text)
        except Exception as e:
            print(f"[META-AGENT] Cloud fallback failed: {e}")

    if result is None:
        print("[META-AGENT] backend failed — using safe defaults")
        return dict(SAFE_DEFAULTS)

    # Merge with defaults so a missing key doesn't crash downstream.
    out = dict(SAFE_DEFAULTS)
    for k in SAFE_DEFAULTS:
        if k in result:
            out[k] = result[k]
    print(f"[META-AGENT] {json.dumps(out, ensure_ascii=False)}")
    return out


def build_meta_instruction(meta: dict, student_known: bool = True) -> str:
    """Render the meta dict into a short instruction injected into the
    professor's system prompt. Keep it terse — every word here costs input
    tokens on every Q&A turn.
    """
    parts: list = []

    # Mood → tone (only emit non-default moods to save tokens)
    mood = meta.get("mood", "спокоен")
    if mood == "растерян":
        parts.append("Студент растерян — снижай темп, объясняй проще, без жаргона.")
    elif mood == "раздражён":
        parts.append("Студент раздражён — кратко по сути, без лишней теории и без 'отличный вопрос'.")
    elif mood == "любопытен":
        parts.append("Студент включён — можно глубже, добавляй неочевидные детали.")

    # Comprehension level → depth
    level = meta.get("level", 3)
    if level <= 2:
        parts.append("Уровень понимания низкий — разбей объяснение на 1-2 предложения и спроси понял ли.")
    elif level >= 4:
        parts.append("Уровень понимания высокий — не упрощай, можно техническими терминами.")

    if meta.get("needs_analogy"):
        parts.append("Дай ОДНУ простую бытовую аналогию перед техническим объяснением.")
    else:
        parts.append("Без аналогий — отвечай прямо.")

    # Anaphora resolution — feed the resolved referent into the prompt so RAG
    # search and the LLM both know what "это" actually points to.
    ref = meta.get("ref")
    if ref:
        parts.append(f"В реплике 'это/он/тот' = «{ref}». Отвечай про {ref}, не про слово 'это'.")

    # Concept stuck loop — force a different framing.
    stuck = meta.get("stuck_on")
    if stuck:
        parts.append(
            f"Студент третий раз возвращается к «{stuck}» и не схватывает. Зайди с ПРИНЦИПИАЛЬНО "
            f"другой стороны: другая метафора / физическая аналогия / пошаговый пример с числами."
        )

    # STT garble — defensively ask to repeat instead of hallucinating around it.
    if meta.get("stt_garbled"):
        parts.append(
            "Реплика похожа на ошибку распознавания речи — НЕ пытайся угадать смысл. "
            "Скажи: 'Я тебя не расслышал, повтори пожалуйста' и жди."
        )

    if not student_known:
        parts.append("Студент не представился — попроси имя ОДНИМ предложением, потом отвечай.")

    # Explicit student-issued style instruction — highest priority, follow literally.
    style_hint = meta.get("style_hint")
    if style_hint:
        parts.append(
            f"СТУДЕНТ ЯВНО ПОПРОСИЛ ОТВЕЧАТЬ ТАК: {style_hint}. Применяй это к ответу буквально, "
            f"не дополняй и не игнорируй."
        )

    return " ".join(parts)
