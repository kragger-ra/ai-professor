"""Faithfulness eval at N=100 — same methodology as N=20 (03_faithfulness.md), 5x bigger sample.

Sample composition:
  - 70 real Q&A from data/metrics.db (full набор interactions от апробации 16-21.05)
  - 30 LLM-synthesized Q's по PersonaLab корпусу (одна Q на «представительный» чанк)
  → tagged with source="metrics_db" / "synthetic_corpus" for downstream split-analysis

Critical: this evaluation runs against the PersonaLab corpus (matching the
historical Q&A in metrics.db), NOT the currently-active Вайб-кодинг course.
We load the persisted PersonaLab FAISS backup directly via FAISS.load_local —
the live data/rag_vector_store/ is untouched and the active course config on
disk (data/current_course.json) is never overwritten.

Phases (CLI flags below):
  --phase sample   write _faithfulness_sample_n100.json
  --phase rerun    read sample, generate fresh_answer per Q via gpt-5.4 + PersonaLab retrieval
  --phase judge    read rerun, LLM-as-judge (v3 prompt) per Q
  --phase report   aggregate counts, print summary, no I/O beyond stdout
  --phase all      run all four in sequence (default)

Costs (rough): ~$1 total at gpt-5.4 prices (~$0.30 sample-gen, ~$0.35 rerun, ~$0.35 judge).
Wall clock: ~10-15 min sequential (rate-limited by OpenAI).

Resumable: each phase writes its checkpoint JSON, downstream phases read it.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import requests
import yaml

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# ---------------------------------------------------------------------------
# Paths and env
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[2]  # research/eval -> research -> repo_root
RESULTS_DIR = REPO_ROOT / "research" / "eval_results"
METRICS_DB = REPO_ROOT / "data" / "metrics.db"
PERSONALAB_INDEX_DIR = REPO_ROOT / "data" / "rag_vector_store_personalab_backup"
CHUNKS_JSON = RESULTS_DIR / "_chunks.json"   # original PersonaLab chunks (140), used for synth Q gen
PERSONALITIES = REPO_ROOT / "resources" / "Prompts" / "personalities_professor.yml"

SAMPLE_JSON  = RESULTS_DIR / "_faithfulness_sample_n100.json"
RERUN_JSON   = RESULTS_DIR / "_faithfulness_rerun_n100.json"
VERDICTS_JSON = RESULTS_DIR / "_faithfulness_verdicts_n100.json"


def _apply_suffix(suffix: str) -> None:
    """Re-point rerun/verdicts/aggregate outputs to *_<suffix>.json.

    Sample path stays the same — same sample is replayed against the
    edited prompt for like-for-like comparison.
    """
    global RERUN_JSON, VERDICTS_JSON
    if not suffix:
        return
    RERUN_JSON = RESULTS_DIR / f"_faithfulness_rerun_n100_{suffix}.json"
    VERDICTS_JSON = RESULTS_DIR / f"_faithfulness_verdicts_n100_{suffix}.json"

# Read .env from repo root (script does NOT cd into the repo because that
# would confuse the langchain FAISS loader's relative path resolution).
def _load_env() -> None:
    env_path = REPO_ROOT / ".env"
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

_load_env()

# Make tutor.* importable
sys.path.insert(0, str(REPO_ROOT))


# ---------------------------------------------------------------------------
# Hardcoded PersonaLab course config (we don't touch data/current_course.json)
# ---------------------------------------------------------------------------

PERSONALAB_CFG = {
    "name": "PersonaLab Workshop",
    "topic": "создание цифрового персонажа на базе LLM + STT + TTS + RAG",
    "short_name": "PersonaLab",
    "teaching_style": "дружелюбно",
    "audience": "разработчик с базой Python",
    "example_keywords": ["PersonaLab", "RAG", "LLM", "STT", "TTS", "профиль персонажа", "FAISS", "bge-m3"],
}

COURSE_FACTS = (
    f"Курс: «{PERSONALAB_CFG['name']}» (short: {PERSONALAB_CFG['short_name']}). "
    f"Тема: {PERSONALAB_CFG['topic']}. Аудитория: {PERSONALAB_CFG['audience']}. "
    f"Ключевые слова курса: {', '.join(PERSONALAB_CFG['example_keywords'])}."
)


def _render_course(template: str) -> str:
    out = template
    for k, v in PERSONALAB_CFG.items():
        out = out.replace("{COURSE_" + k.upper() + "}", str(v))
    return out


# ---------------------------------------------------------------------------
# OpenAI helper (same endpoint as production: api.openai.com via .env)
# ---------------------------------------------------------------------------

API_BASE = os.environ["LM_STUDIO_API_BASE"].rstrip("/")
API_KEY  = os.environ["OPENAI_API_KEY"]
MODEL    = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")
REASONING = os.environ.get("LM_STUDIO_REASONING_EFFORT", "none")
HEADERS = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}


def chat(messages, *, max_tokens=400, temperature=0.6, timeout=60) -> tuple[str, dict, float]:
    body: dict[str, Any] = {
        "model": MODEL,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    if REASONING:
        body["reasoning_effort"] = REASONING
    t0 = time.time()
    r = requests.post(f"{API_BASE}/chat/completions", json=body, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    j = r.json()
    return j["choices"][0]["message"]["content"].strip(), j.get("usage", {}), time.time() - t0


# ---------------------------------------------------------------------------
# RAG: load PersonaLab backup directly via langchain (no live RagModel state)
# ---------------------------------------------------------------------------

_rag_cache = {"vec": None, "emb": None}


def _get_rag():
    if _rag_cache["vec"] is not None:
        return _rag_cache["vec"]
    print("[rag] loading PersonaLab backup index...")
    from langchain_community.vectorstores import FAISS
    from tutor.brain.embeddings import get_embeddings_model
    emb = get_embeddings_model()
    vec = FAISS.load_local(
        folder_path=str(PERSONALAB_INDEX_DIR),
        embeddings=emb,
        index_name="knowledge",
        allow_dangerous_deserialization=True,
    )
    _rag_cache["vec"] = vec
    _rag_cache["emb"] = emb
    # warmup
    _ = vec.similarity_search_with_score("PersonaLab", k=2)
    print(f"[rag] loaded {len(vec.docstore._dict)} chunks, warmup OK")
    return vec


def retrieve(query: str, k: int = 3) -> tuple[str, float, list[dict]]:
    """Mimic tutor.brain.rag.RagModel.explain() output:
       returns (joined_top2_text_or_empty, top1_L2, top2_sources_meta_list)."""
    vec = _get_rag()
    docs_with_scores = vec.similarity_search_with_score(query, k=k)
    if not docs_with_scores:
        return "", float("inf"), []
    scores = [s for _, s in docs_with_scores]
    best = min(scores)
    sources = [
        {
            "score": float(s),
            "kind": d.metadata.get("kind", ""),
            "subject": d.metadata.get("subject", ""),
            "source": d.metadata.get("source", ""),
            "preview": (d.page_content[:120]).strip(),
        }
        for d, s in docs_with_scores[:2]
    ]
    if best > 1.5:
        return "", best, sources
    text = "\n\n".join(d.page_content for d, _ in docs_with_scores[:2])
    return text, best, sources


# ---------------------------------------------------------------------------
# System prompt construction (mirrors tutor.brain.prompt.construct_prompt
# but uses local PERSONALAB_CFG instead of touching course state on disk)
# ---------------------------------------------------------------------------

_personality_cache = {"data": None}


def _personality(key: str) -> str:
    if _personality_cache["data"] is None:
        with open(PERSONALITIES, "r", encoding="utf-8") as f:
            _personality_cache["data"] = yaml.safe_load(f) or {}
    return _personality_cache["data"].get(key, "")


def build_system_prompt(rag_text: str, rag_score: float) -> str:
    base = _render_course(_personality("professor_simpler"))
    if not rag_text:
        return base
    if rag_score < 0.8:
        header = "## Контекст из материалов курса (высокая релевантность):"
    elif rag_score < 1.2:
        header = "## Контекст из материалов курса (частичное совпадение — дополни из своих знаний):"
    else:
        header = "## Контекст из материалов курса (низкая релевантность — опирайся на свои знания):"
    return f"{base}\n\n{header}\n{rag_text}"


# ---------------------------------------------------------------------------
# PHASE A — SAMPLE: pull 70 real + generate 30 synthetic = 100
# ---------------------------------------------------------------------------

GEN_PROMPT = """Прочитай фрагмент учебного материала курса «PersonaLab Workshop» (тема: создание цифрового персонажа на базе LLM + STT + TTS + RAG).

ФРАГМЕНТ:
{chunk}

Сгенерируй ОДИН вопрос, который мог бы задать студент тьютору в голосовом разговоре. Жёсткие правила:
- Ответ на вопрос должен лежать в этом фрагменте.
- Студент говорит вслух — вопрос звучит естественно, разговорно, 1-2 предложения, без формальностей.
- НЕ копируй редкие/специфичные термины и формулировки из фрагмента дословно — перефразируй так, как студент реально спросил бы.
- Если фрагмент описывает X — спрашивай «что такое X / как работает X / зачем X», а не «процитируй мне определение X».
- Не задавай мета-вопросы вроде «о чём этот фрагмент».
- Вопрос на русском.

Ответь ОДНОЙ строкой — самим вопросом, без префиксов, без кавычек, без пояснений."""


def phase_sample() -> list[dict]:
    print("=" * 70)
    print("PHASE A — sample")
    print("=" * 70)

    # --- 70 historical from metrics.db ---
    con = sqlite3.connect(str(METRICS_DB))
    con.row_factory = sqlite3.Row
    cur = con.cursor()
    cur.execute("""
        SELECT id, timestamp, student_query, agent_response, response_time_ms, rag_sources
        FROM interactions
        WHERE student_query IS NOT NULL AND TRIM(student_query) != ''
          AND agent_response IS NOT NULL AND TRIM(agent_response) != ''
        ORDER BY id
    """)
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    print(f"[A] metrics.db: {len(rows)} non-empty interactions (taking all)")

    hist_sample = []
    for r in rows:
        hist_sample.append({
            "qid": len(hist_sample) + 1,
            "source": "metrics_db",
            "metrics_id": r["id"],
            "timestamp": r["timestamp"],
            "student_query": r["student_query"].strip(),
            "historical_answer": r["agent_response"].strip(),
        })

    # --- 30 synthetic on PersonaLab chunks ---
    chunks = json.loads(CHUNKS_JSON.read_text(encoding="utf-8"))
    # Stratify by source file like _rag_eval_02_generate_questions.py
    by_source = defaultdict(list)
    for c in chunks:
        name = c["source"].split("\\")[-1].split("/")[-1]
        by_source[name].append(c)

    # Distribute 30 across files proportionally (round-robin from largest sources first)
    sources_sorted = sorted(by_source.items(), key=lambda kv: -len(kv[1]))
    target_total = 30
    plan = {}
    for name, lst in sources_sorted:
        plan[name] = max(1, round(len(lst) / len(chunks) * target_total))
    # Trim/grow to exactly 30
    while sum(plan.values()) > target_total:
        # remove from largest bucket
        k = max(plan, key=plan.get)
        plan[k] -= 1
    while sum(plan.values()) < target_total:
        k = min(plan, key=plan.get)
        plan[k] += 1
    print(f"[A] synth plan: {plan}")

    def is_content(c):
        text = c["content"].strip()
        if len(text) < 150:
            return False
        body_lines = [ln for ln in text.split("\n") if ln.strip() and not ln.strip().startswith("#")]
        return len(body_lines) >= 2

    picked = []
    for src_name, n in plan.items():
        cands = [c for c in by_source[src_name] if is_content(c)] or by_source[src_name]
        step = max(1, len(cands) // n)
        chosen = cands[::step][:n]
        if len(chosen) < n:
            rest = [c for c in cands if c not in chosen]
            chosen += rest[: n - len(chosen)]
        picked.extend(chosen)
    print(f"[A] picked {len(picked)} chunks for synth Q gen")

    synth_sample = []
    qid_base = len(hist_sample)
    for i, c in enumerate(picked):
        chunk_text = c["content"][:1400]
        try:
            q_text, _, dt = chat(
                [{"role": "user", "content": GEN_PROMPT.format(chunk=chunk_text)}],
                max_tokens=120, temperature=0.7,
            )
            q_text = q_text.strip("«»\"'`-—– ")
            q_text = re.sub(r"^[\d.)]+\s*", "", q_text)
        except Exception as e:
            print(f"  [synth#{i+1}] FAIL: {e}")
            continue
        synth_sample.append({
            "qid": qid_base + len(synth_sample) + 1,
            "source": "synthetic_corpus",
            "gt_chunk_id": c.get("chunk_id"),
            "gt_source": c["source"].split("\\")[-1].split("/")[-1],
            "gt_preview": c["content"][:200],
            "student_query": q_text,
            "historical_answer": None,
        })
        print(f"  [synth#{i+1:>2}] ({dt:.1f}s) [{synth_sample[-1]['gt_source']}] {q_text[:80]}")

    sample = hist_sample + synth_sample
    SAMPLE_JSON.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[A] saved {len(sample)} samples ({len(hist_sample)} hist + {len(synth_sample)} synth) → {SAMPLE_JSON.name}")
    return sample


# ---------------------------------------------------------------------------
# PHASE B — RERUN: retrieve + generate fresh answer for every Q
# ---------------------------------------------------------------------------

def phase_rerun() -> list[dict]:
    print("=" * 70)
    print("PHASE B — rerun")
    print("=" * 70)

    samples = json.loads(SAMPLE_JSON.read_text(encoding="utf-8"))
    print(f"[B] {len(samples)} samples to rerun")
    _get_rag()  # warmup

    results = []
    for s in samples:
        q = s["student_query"]
        rag_text, score, sources = retrieve(q)
        sys_prompt = build_system_prompt(rag_text, score)
        try:
            ans, usage, dt = chat(
                [{"role": "system", "content": sys_prompt},
                 {"role": "user", "content": q}],
                max_tokens=400, temperature=0.6,
            )
        except Exception as e:
            print(f"  [B#{s['qid']:>3}] FAIL: {e}")
            continue
        results.append({
            **s,
            "rag_top_L2": float(score) if score != float("inf") else None,
            "rag_top_sources": sources,
            "rag_full_text": rag_text,
            "fresh_answer": ans,
            "gen_time_s": round(dt, 2),
            "usage": usage,
        })
        print(f"  [B#{s['qid']:>3}] L2={score:.3f} gen={dt:.1f}s "
              f"q={q[:42]} → ans={ans[:50]}")

    RERUN_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[B] saved {len(results)} reruns → {RERUN_JSON.name}")
    return results


# ---------------------------------------------------------------------------
# PHASE C — JUDGE: v3 paraphrase-aware judge
# ---------------------------------------------------------------------------

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
- название технологии / компонента / инструмента / файла
- конкретная цифра / версия / путь
- описание МЕХАНИЗМА, как именно X делает Y (если это конкретная техническая деталь, не общая идея)
- утверждение о наличии/отсутствии конкретной фичи

НЕ считать фактическим утверждением (это персонажная подача, а не выдумка):
- бытовая аналогия («стикер», «записная книжка», «картотека», «полка»)
- иллюстративный пример («например, ранг 4 это знакомый пользователь»)
- мета-фраза тьютора («я объясню проще», «запомни», «главное здесь», «если хочешь, разберу дальше»)
- общая методическая фраза («это нужно для удобства»)
- общеизвестные факты про AI/ML, не противоречащие retrieved
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
- "hallucination" — есть как минимум одна КОНКРЕТНАЯ техническая сущность, которой нет ни в retrieved, ни в статических фактах, и нет дисклеймера.
- "correct_refusal" — система сказала «не понял, уточни / пришли больше контекста» и не начала выдумывать.
- "non_factual" — простое приветствие / ack / уточнение без фактов.

Будь СПРАВЕДЛИВ. Не флагай парафразу. Не флагай аналогию. Не флагай статический факт курса.

Верни ТОЛЬКО валидный JSON:
{{"category": "grounded|honest_disclaimer|hallucination|correct_refusal|non_factual",
  "fact_kernels": ["..."],
  "unsupported_kernels": ["..."],
  "reasoning": "одна короткая фраза"}}"""

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str):
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text)
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def phase_judge() -> list[dict]:
    print("=" * 70)
    print("PHASE C — judge (v3 paraphrase-aware)")
    print("=" * 70)

    reruns = json.loads(RERUN_JSON.read_text(encoding="utf-8"))
    print(f"[C] {len(reruns)} reruns to judge")

    out = []
    for r in reruns:
        prompt = JUDGE_PROMPT.format(
            course_facts=COURSE_FACTS,
            question=r["student_query"],
            retrieved=r.get("rag_full_text") or "(retrieved пусто)",
            answer=r["fresh_answer"],
        )
        try:
            text, _, dt = chat(
                [{"role": "user", "content": prompt}],
                max_tokens=500, temperature=0.1,
            )
            verdict = _extract_json(text) or {"category": "PARSE_FAIL", "reasoning": text[:200]}
        except Exception as e:
            verdict = {"category": "API_FAIL", "reasoning": str(e)[:200]}
            dt = 0.0
        verdict["qid"] = r["qid"]
        verdict["source"] = r.get("source", "?")
        verdict["judge_time_s"] = round(dt, 2)
        flag = {"grounded": "+", "honest_disclaimer": "i", "correct_refusal": "?",
                "hallucination": "X", "non_factual": "-"}.get(verdict.get("category", ""), "??")
        print(f"  [C#{r['qid']:>3}] {flag} {verdict.get('category','?'):<20} ({dt:.1f}s) "
              f"q={r['student_query'][:38]}")
        if verdict.get("category") == "hallucination":
            for u in verdict.get("unsupported_kernels", []) or []:
                print(f"          X {u}")
        out.append({**r, "verdict": verdict})

    VERDICTS_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[C] saved {len(out)} verdicts → {VERDICTS_JSON.name}")
    return out


# ---------------------------------------------------------------------------
# PHASE D — REPORT: aggregate + compare to N=20 baseline
# ---------------------------------------------------------------------------

BASELINE_N20 = {
    "grounded": 15, "honest_disclaimer": 0, "correct_refusal": 2,
    "hallucination": 1, "non_factual": 2, "N": 20,
}


def _bucket(verdicts):
    cats = Counter(v["verdict"].get("category", "?") for v in verdicts)
    N = len(verdicts)
    rows = []
    for c in ("grounded", "honest_disclaimer", "correct_refusal", "hallucination", "non_factual"):
        n = cats.get(c, 0)
        pct = (n / N * 100) if N else 0.0
        rows.append((c, n, pct))
    factual = sum(cats.get(c, 0) for c in ("grounded", "honest_disclaimer", "hallucination"))
    trustworthy = cats.get("grounded", 0) + cats.get("honest_disclaimer", 0)
    faithfulness_rate = (trustworthy / factual * 100) if factual else 0.0
    halluc_rate = cats.get("hallucination", 0) / N * 100 if N else 0.0
    return rows, faithfulness_rate, halluc_rate, cats


def phase_report():
    print("=" * 70)
    print("PHASE D — report")
    print("=" * 70)

    verdicts = json.loads(VERDICTS_JSON.read_text(encoding="utf-8"))
    N = len(verdicts)

    rows, faithfulness_rate, halluc_rate, cats = _bucket(verdicts)
    print(f"\nAGGREGATE FAITHFULNESS (N={N}) — full sample")
    print("-" * 60)
    for c, n, pct in rows:
        print(f"  {c:<22} {n:>3}/{N}  ({pct:>4.1f}%)")
    print(f"\n  Faithfulness rate (grounded+disclaimer / factual): {faithfulness_rate:.1f}%")
    print(f"  Hallucination rate (all {N}):                       {halluc_rate:.1f}%")

    # Split by source
    by_src = defaultdict(list)
    for v in verdicts:
        by_src[v.get("source", "?")].append(v)
    print("\nBY SOURCE")
    print("-" * 60)
    for src, vs in by_src.items():
        sub_rows, sub_faith, sub_halluc, _ = _bucket(vs)
        print(f"  source={src!r}  N={len(vs)}  faith={sub_faith:.0f}%  halluc={sub_halluc:.1f}%")
        for c, n, pct in sub_rows:
            print(f"    {c:<22} {n:>3}/{len(vs)} ({pct:>4.1f}%)")

    # Compare to N=20 baseline
    print("\nCOMPARISON TO N=20 BASELINE (03_faithfulness.md)")
    print("-" * 60)
    print(f"  {'category':<22} {'N=20':>10} {'N=100':>10} {'delta':>8}")
    for c, n, pct in rows:
        b = BASELINE_N20.get(c, 0)
        b_pct = b / BASELINE_N20["N"] * 100
        print(f"  {c:<22} {b_pct:>9.1f}% {pct:>9.1f}% {pct - b_pct:>+7.1f}pp")

    # Save raw aggregates as JSON for the markdown step
    agg = {
        "N": N,
        "categories": {c: {"n": n, "pct": pct} for c, n, pct in rows},
        "faithfulness_rate_pct": faithfulness_rate,
        "hallucination_rate_pct": halluc_rate,
        "by_source": {
            src: {
                "N": len(vs),
                "counts": {c: n for c, n, _ in _bucket(vs)[0]},
            } for src, vs in by_src.items()
        },
        "baseline_n20": BASELINE_N20,
    }
    agg_suffix = VERDICTS_JSON.stem.replace("_faithfulness_verdicts_n100", "")
    agg_path = RESULTS_DIR / f"_faithfulness_aggregate_n100{agg_suffix}.json"
    agg_path.write_text(json.dumps(agg, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSaved aggregate → {agg_path.name}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--phase", choices=["sample", "rerun", "judge", "report", "all"], default="all")
    p.add_argument("--suffix", default="",
                   help="Re-point rerun/verdicts/aggregate outputs to *_<suffix>.json (sample untouched).")
    args = p.parse_args()
    _apply_suffix(args.suffix)
    if args.phase in ("sample", "all"):
        phase_sample()
    if args.phase in ("rerun", "all"):
        phase_rerun()
    if args.phase in ("judge", "all"):
        phase_judge()
    if args.phase in ("report", "all"):
        phase_report()


if __name__ == "__main__":
    main()
