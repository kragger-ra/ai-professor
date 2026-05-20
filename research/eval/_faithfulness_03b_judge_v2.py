"""LLM-as-judge v2 — calibrated rubric that distinguishes:
- novel FACTS (mechanism, name, number) not in retrieved → hallucination
- new ANALOGIES/REPHRASING of facts that ARE in retrieved → fine, that's the persona
- meta-statements ("я объясню проще", "запомни") → not factual claims
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

JUDGE_PROMPT = """Ты — независимый эксперт. Оцениваешь faithfulness ответа RAG-системы.

КОНТЕКСТ: система — это голосовой ИИ-тьютор курса «PersonaLab Workshop» (создание цифрового персонажа: LLM+STT+TTS+RAG). Тьютору ПРЕДПИСАНО:
- использовать бытовые аналогии («стикер», «записная книжка», «полка инструментов»),
- переформулировать канцелярит из материала на разговорный русский,
- вставлять лексические маркеры («запомни», «главное здесь»),
- добавлять конкретные примеры для иллюстрации.

Поэтому аналогии, примеры и переформулировки НЕ являются галлюцинациями — они эксплицитная задача персонажа. Галлюцинация = НОВАЯ ФАКТИЧЕСКАЯ СУЩНОСТЬ, которой нет в retrieved.

Что считать фактической сущностью:
- название инструмента / компонента / технологии (например, «LangGraph», «tool_status», «name_tool_status»)
- конкретная цифра, версия, путь, имя файла
- описание механизма работы (как именно происходит X)
- утверждение о наличии/отсутствии фичи

Что НЕ считать фактом, а оформлением:
- бытовая аналогия (стикер, картотека, записная книжка, полка)
- пример иллюстрации («например, ранг 4 значит знакомый пользователь»)
- мета-фраза тьютора («я объясню проще», «запомни», «главное здесь»)
- общая методическая фраза («это нужно для удобства», «чтобы быстрее ориентироваться»)
- перефразирование того же факта другими словами

ВОПРОС СТУДЕНТА:
{question}

RETRIEVED CHUNKS (то, что было в системном промпте при генерации ответа):
{retrieved}

ОТВЕТ ИИ-ТЬЮТОРА:
{answer}

ШАГИ:
1. Извлеки из ответа только ФАКТИЧЕСКИЕ СУЩНОСТИ по списку выше (не оформление).
2. Для каждой проверь: есть ли она в retrieved (буквально или явной парафразой)?
3. Если ответ — простая ack/уточнение/приветствие, без новых фактов — это "non_factual".
4. Если в ответе нет ни одной фактической сущности и ответ — это переформулировка/расширение того, что было в retrieved + аналогии — это "grounded".
5. Если есть хотя бы 1 фактическая сущность, которая не в retrieved, и нет дисклеймера «из общих знаний» — это "hallucination".
6. Если фактических сущностей нет в retrieved, НО есть явная оговорка «в материалах курса этого нет, но из общих знаний» — это "honest_disclaimer".
7. Если ответ говорит «не понял вопрос / пришли больше контекста / уточни» вместо выдумывания — это "correct_refusal".

Будь СПРАВЕДЛИВ: аналогии — это не выдумки. Цели — это не факты. Только конкретные сущности.

ВЕРНИ ТОЛЬКО валидный JSON:
{{"category": "grounded|honest_disclaimer|hallucination|correct_refusal|non_factual",
  "fact_kernels": ["перечислены фактические сущности, которые ты проверил"],
  "unsupported_kernels": ["те из них, что не нашёл в retrieved (или пустой массив)"],
  "reasoning": "одно короткое предложение"}}"""

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
print(f"Loaded {len(reruns)} reruns")

verdicts = []
for r in reruns:
    qid = r["qid"]
    prompt = JUDGE_PROMPT.format(
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
        verdict = extract_json(text)
        if not verdict:
            verdict = {"category": "PARSE_FAIL", "reasoning": text[:200]}
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
            print(f"        ✗ unsupported: {u}")
    if verdict.get("category") in ("PARSE_FAIL", "API_FAIL"):
        print(f"        FAIL: {verdict.get('reasoning', '')[:120]}")

# Save merged
out = []
for r in reruns:
    v = next((x for x in verdicts if x["qid"] == r["qid"]), {})
    out.append({**r, "verdict_v2": v})
(ROOT / "eval_results" / "_faithfulness_verdicts_v2.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)

# Aggregate
from collections import Counter
cats = Counter(v.get("category", "?") for v in verdicts)
N = len(verdicts)
print()
print("=" * 60)
print(f"AGGREGATE FAITHFULNESS v2 (N={N})")
print("=" * 60)
for c in ["grounded", "honest_disclaimer", "correct_refusal", "hallucination", "non_factual"]:
    n = cats.get(c, 0)
    print(f"  {c:<20} {n:>2}/{N}  ({n/N*100:.0f}%)")
factual = sum(cats.get(c, 0) for c in ("grounded", "honest_disclaimer", "hallucination"))
trustworthy = cats.get("grounded", 0) + cats.get("honest_disclaimer", 0)
if factual:
    print(f"\n  Faithfulness rate (grounded+disclaimer / factual responses): "
          f"{trustworthy}/{factual} = {trustworthy/factual*100:.0f}%")
print(f"  Hallucination rate (всех {N}): {cats.get('hallucination', 0)}/{N} = "
      f"{cats.get('hallucination',0)/N*100:.0f}%")
