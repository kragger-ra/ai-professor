"""LLM-as-judge v3 — final calibrated version.

Critical fixes vs v2:
1. Pass system_prompt + course_config to judge so it can recognize statics there.
2. Explicit paraphrase rule: 'А хранит X' is supported by 'X хранится в А' or 'А содержит X'.
3. Explicit allowance for general AI/ML common knowledge that doesn't contradict retrieved.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

api_base = os.environ.get("LM_STUDIO_API_BASE").rstrip("/")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")

course = json.loads((ROOT / "data" / "current_course.json").read_text(encoding="utf-8"))
COURSE_FACTS = (
    f"Курс: «{course.get('name')}» (short: {course.get('short_name')}). "
    f"Тема: {course.get('topic')}. Аудитория: {course.get('audience')}. "
    f"Ключевые слова курса: {', '.join(course.get('example_keywords', []))}."
)


JUDGE_PROMPT = """Ты — независимый эксперт. Оцениваешь faithfulness одного ответа RAG-системы.

КОНТЕКСТ СИСТЕМЫ. Это голосовой ИИ-тьютор курса.
Статические факты, которые тьютор ЗАВЕДОМО знает из system prompt (это grounded по умолчанию):
{course_facts}
Также тьютору ПРЕДПИСАНО: использовать бытовые аналогии, переводить канцелярит на разговорный русский,
вставлять лексические маркеры («запомни», «главное здесь»), приводить иллюстративные примеры.

ВОПРОС СТУДЕНТА:
{question}

RETRIEVED CHUNKS (что система достала из FAISS для этого вопроса):
{retrieved}

ОТВЕТ ИИ-ТЬЮТОРА:
{answer}

ВЫДЕЛИ из ответа только КОНКРЕТНЫЕ ФАКТИЧЕСКИЕ СУЩНОСТИ:
- название технологии / компонента / инструмента / файла (например, «LangGraph», «SQLite», «tool_status», «name_tool_status», «UserInfo»)
- конкретная цифра / версия / путь
- описание МЕХАНИЗМА, как именно X делает Y (если это конкретная техническая деталь, не общая идея)
- утверждение о наличии/отсутствии конкретной фичи

НЕ считать фактическим утверждением (это персонажная подача, а не выдумка):
- бытовая аналогия («стикер», «записная книжка», «картотека», «полка»)
- иллюстративный пример («например, ранг 4 это знакомый пользователь»)
- мета-фраза тьютора («я объясню проще», «запомни», «главное здесь», «если хочешь, разберу дальше»)
- общая методическая фраза («это нужно для удобства»)
- общеизвестные факты про AI/ML, не противоречащие retrieved (например, «LLM генерирует текст», «STT переводит речь в текст»)
- факты из контекста системы (см. «Статические факты» выше)
- ПАРАФРАЗА того, что в retrieved. Если в retrieved «А хранит X», а в ответе «X хранится в А» — это grounded.

ПРАВИЛО ПАРАФРАЗЫ. Прежде чем флагать утверждение как unsupported, проверь:
- Совпадает ли смысл с retrieved при разных формулировках?
- Является ли это переводом канцелярита в обычный русский, который сделал тьютор намеренно?
- Является ли это статическим фактом про курс из списка выше?
Если хоть на одно «да» — это grounded.

КАТЕГОРИИ:
- "grounded" — фактические сущности либо в retrieved, либо в статических фактах курса, либо отсутствуют (одни аналогии и общие фразы).
- "honest_disclaimer" — ответ содержит факты, которых нет в retrieved/статике, НО есть явная оговорка («в материалах курса этого нет, но из общих знаний…»).
- "hallucination" — есть как минимум одна КОНКРЕТНАЯ техническая сущность (название, путь, механизм), которой нет ни в retrieved, ни в статических фактах, и нет дисклеймера.
- "correct_refusal" — система сказала «не понял, уточни / пришли больше контекста» и не начала выдумывать.
- "non_factual" — простое приветствие / ack / уточнение без фактов.

Будь СПРАВЕДЛИВ. Не флагай парафразу. Не флагай аналогию. Не флагай статический факт курса.

Верни ТОЛЬКО валидный JSON:
{{"category": "grounded|honest_disclaimer|hallucination|correct_refusal|non_factual",
  "fact_kernels": ["..."],
  "unsupported_kernels": ["..."],
  "reasoning": "одна короткая фраза"}}"""


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)
def extract_json(text):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


reruns = json.loads((ROOT / "eval_results" / "_faithfulness_rerun.json").read_text(encoding="utf-8"))
verdicts = []
for r in reruns:
    qid = r["qid"]
    prompt = JUDGE_PROMPT.format(
        course_facts=COURSE_FACTS,
        question=r["question"],
        retrieved=r["rag_full_text"] or "(retrieved пусто)",
        answer=r["fresh_answer"],
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": 500,
        "temperature": 0.1,
        "stream": False,
        "reasoning_effort": "none",
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t = time.time()
    try:
        rr = requests.post(f"{api_base}/chat/completions", json=body, headers=headers, timeout=60)
        rr.raise_for_status()
        text = rr.json()["choices"][0]["message"]["content"]
        verdict = extract_json(text) or {"category": "PARSE_FAIL", "reasoning": text[:200]}
    except Exception as e:
        verdict = {"category": "API_FAIL", "reasoning": str(e)[:200]}
    dt = time.time() - t
    verdict["qid"] = qid
    verdict["judge_time_s"] = round(dt, 2)
    verdicts.append(verdict)
    flag = {
        "grounded": "✓", "honest_disclaimer": "i", "correct_refusal": "?",
        "hallucination": "✗", "non_factual": "—"
    }.get(verdict.get("category", ""), "??")
    print(f"[J#{qid:>2}] {flag} {verdict.get('category','?'):<20} ({dt:.1f}s) "
          f"q={r['question'][:42]}")
    if verdict.get("category") == "hallucination":
        for u in verdict.get("unsupported_kernels", []):
            print(f"        ✗ {u}")

# Save
out = []
for r in reruns:
    v = next((x for x in verdicts if x["qid"] == r["qid"]), {})
    out.append({**r, "verdict_v3": v})
(ROOT / "eval_results" / "_faithfulness_verdicts_v3.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)

from collections import Counter
cats = Counter(v.get("category", "?") for v in verdicts)
N = len(verdicts)
print()
print("=" * 60)
print(f"AGGREGATE FAITHFULNESS v3 (N={N})")
print("=" * 60)
for c in ["grounded", "honest_disclaimer", "correct_refusal", "hallucination", "non_factual"]:
    n = cats.get(c, 0)
    print(f"  {c:<20} {n:>2}/{N}  ({n/N*100:.0f}%)")
factual = sum(cats.get(c, 0) for c in ("grounded", "honest_disclaimer", "hallucination"))
trustworthy = cats.get("grounded", 0) + cats.get("honest_disclaimer", 0)
if factual:
    print(f"\n  Faithfulness rate (grounded+disclaimer / factual): "
          f"{trustworthy}/{factual} = {trustworthy/factual*100:.0f}%")
print(f"  Hallucination rate (all {N}): {cats.get('hallucination', 0)}/{N} = "
      f"{cats.get('hallucination',0)/N*100:.0f}%")
