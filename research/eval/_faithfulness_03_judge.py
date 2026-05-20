"""LLM-as-judge: classify each (q, retrieved, answer) into faithfulness category."""
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

JUDGE_PROMPT = """Ты — независимый эксперт по оценке систем RAG (retrieval-augmented generation). На вход подан реальный диалог: вопрос студента, retrieved chunks (то, что система нашла в индексе по этому вопросу), и ответ ИИ-тьютора. Твоя задача — классифицировать ответ по категории faithfulness.

ВОПРОС СТУДЕНТА:
{question}

RETRIEVED CHUNKS (контекст из материалов курса PersonaLab Workshop, который система передала LLM):
{retrieved}

ОТВЕТ ИИ-ТЬЮТОРА:
{answer}

Выдели в ответе все фактические утверждения (про устройство системы, термины, цифры, команды, имена компонентов). Игнорируй вежливые формулы, перефразирование вопроса, маркеры манеры ("запомни", "главное здесь").

Категории (выбери ОДНУ):

- "grounded" — все ключевые фактические утверждения в ответе явно поддерживаются retrieved chunks. Может быть лёгкая перефразировка, но факты те же.
- "honest_disclaimer" — ответ содержит факты, которых НЕТ в retrieved chunks, НО система явно сказала об этом ("в материалах курса этого нет, но из общих знаний...", "из общих знаний...", "не из курса, но..."). Граница вне-RAG-части помечена честно.
- "hallucination" — ответ содержит как минимум одно конкретное утверждение (термин, имя, цифра, механизм), которого нет в retrieved chunks, БЕЗ оговорки про общие знания. Это и есть выдумка/опасный случай.
- "correct_refusal" — ответ корректно сказал "этого нет в материалах" / "пришли больше контекста" / "не понял вопрос", и НЕ начал выдумывать факты. Применять, когда retrieved chunks плохо покрывают вопрос или вопрос меня-уровня ("объясни фрагмент" без фрагмента).
- "non_factual" — реплика конверсационная (приветствие, ack "хорошо", уточняющее переспрашивание без новых фактов). Нет фактических утверждений для оценки.

Если сомневаешься между "grounded" и "hallucination" — смотри, есть ли в retrieved chunks хотя бы парафраза этого утверждения. Если нет — это hallucination. Будь строгим.

Если в ответе есть и grounded факты, и одна неподтверждённая деталь без оговорки — это "hallucination" (одна выдумка ломает категорию).

Если retrieved chunks плохо отвечают на вопрос, а ответ построен на общих знаниях БЕЗ оговорки — это "hallucination". Если с оговоркой — "honest_disclaimer".

Верни ТОЛЬКО валидный JSON следующего вида:
{{"category": "grounded|honest_disclaimer|hallucination|correct_refusal|non_factual",
  "unsupported_claims": ["короткий список конкретных утверждений из ответа, которых нет в retrieved (или пустой массив)"],
  "reasoning": "одна-две короткие фразы — что именно повлияло на категорию"}}"""

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
        retrieved=r["rag_full_text"] or "(retrieved пусто — система не вставила контекст)",
        answer=r["fresh_answer"],
    )
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_completion_tokens": 400,
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
    print(f"[J#{qid:>2}] {flag} {verdict.get('category','?'):<20} ({dt:.1f}s)  "
          f"q={r['question'][:45]}")
    if verdict.get("category") == "hallucination":
        print(f"        unsupported: {verdict.get('unsupported_claims', [])}")
    if verdict.get("category") in ("PARSE_FAIL", "API_FAIL"):
        print(f"        FAIL: {verdict.get('reasoning', '')[:120]}")

# Merge verdicts into samples for the report
out = []
for r in reruns:
    v = next((x for x in verdicts if x["qid"] == r["qid"]), {})
    out.append({
        **r,
        "verdict": v,
    })

(ROOT / "eval_results" / "_faithfulness_verdicts.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
)

# Aggregate
from collections import Counter
cats = Counter(v.get("category", "?") for v in verdicts)
N = len(verdicts)
print()
print("=" * 60)
print("AGGREGATE FAITHFULNESS")
print("=" * 60)
for c in ["grounded", "honest_disclaimer", "correct_refusal", "hallucination", "non_factual",
          "PARSE_FAIL", "API_FAIL"]:
    n = cats.get(c, 0)
    if n or c in ("grounded", "honest_disclaimer", "hallucination", "correct_refusal", "non_factual"):
        print(f"  {c:<20} {n:>2}/{N}  ({n/N*100:.0f}%)")

# Faithfulness rate: % of factual-bearing answers that were grounded or honest_disclaimer
factual = sum(cats.get(c, 0) for c in ("grounded", "honest_disclaimer", "hallucination"))
trustworthy = cats.get("grounded", 0) + cats.get("honest_disclaimer", 0)
if factual:
    print(f"\n  Faithfulness rate (grounded+disclaimer / factual responses): "
          f"{trustworthy}/{factual} = {trustworthy/factual*100:.0f}%")
print(f"  Hallucination rate (всех 20): {cats.get('hallucination', 0)}/{N} = "
      f"{cats.get('hallucination',0)/N*100:.0f}%")
