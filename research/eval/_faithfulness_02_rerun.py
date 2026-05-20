"""Re-run each historical question through current system: retrieve + generate answer.

Output for each sample: (question, retrieved_chunks, fresh_answer, retrieval_L2).
"""
from __future__ import annotations

import json
import os
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

sys.path.insert(0, str(ROOT / "src"))

# RAG init (loads embeddings + FAISS index, warm-up takes ~7s)
print("[init] RAG...")
t = time.time()
from agent.rag import RagModel
rag = RagModel()
print(f"[init] RAG ready in {time.time() - t:.2f}s")

# Real system prompt — same path that the agent uses in production
from lecture import course_config
SYS_TEMPLATE = (ROOT / "resources" / "Prompts" / "personalities_professor.yml").read_text(encoding="utf-8")
sys_prompt_simpler = SYS_TEMPLATE.split("professor_simpler:", 1)[1].split("professor_neutral:", 1)[0]
sys_prompt_simpler = "\n".join(l[2:] if l.startswith("  ") else l for l in sys_prompt_simpler.splitlines())
cfg = course_config.get_current()
sys_prompt_simpler = cfg.render(sys_prompt_simpler)

samples = json.loads((ROOT / "eval_results" / "_faithfulness_sample.json").read_text(encoding="utf-8"))
print(f"[init] {len(samples)} samples")

api_base = os.environ.get("LM_STUDIO_API_BASE").rstrip("/")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")
reasoning = os.environ.get("LM_STUDIO_REASONING_EFFORT", "none")

# Build like construct_prompt does: persona + RAG context with header per L2 zone
def build_rag_context(query):
    rag_text = rag.explain(query)
    sources = list(rag.last_sources) if hasattr(rag, "last_sources") else []
    score = rag.last_score
    if not rag_text:
        return None, score, sources, ""
    if score < 0.8:
        header = "## Контекст из материалов курса (высокая релевантность):"
    elif score < 1.2:
        header = "## Контекст из материалов курса (частичное совпадение — дополни из своих знаний):"
    else:
        header = "## Контекст из материалов курса (низкая релевантность — опирайся на свои знания):"
    return rag_text, score, sources, f"\n\n{header}\n{rag_text}"

results = []
for i, s in enumerate(samples):
    q = s["student_query"].strip()
    rag_text, score, sources, rag_block = build_rag_context(q)
    full_sys = sys_prompt_simpler + (rag_block or "")
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": full_sys},
            {"role": "user", "content": q},
        ],
        "max_completion_tokens": 400,
        "temperature": 0.6,
        "stream": False,
    }
    if reasoning:
        body["reasoning_effort"] = reasoning
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t = time.time()
    try:
        r = requests.post(f"{api_base}/chat/completions", json=body, headers=headers, timeout=60)
        r.raise_for_status()
        answer = r.json()["choices"][0]["message"]["content"].strip()
        usage = r.json().get("usage", {})
    except Exception as e:
        print(f"[#{i+1}] FAIL: {e}")
        continue
    dt = time.time() - t
    results.append({
        "qid": i + 1,
        "metrics_id": s["id"],
        "timestamp": s["timestamp"],
        "question": q,
        "rag_top_L2": float(score) if score is not None else None,
        "rag_top_sources": sources,
        "rag_full_text": rag_text or "",
        "fresh_answer": answer,
        "historical_answer": s["agent_response"],
        "gen_time_s": round(dt, 2),
        "usage": usage,
    })
    print(f"[#{i+1:>2}] L2={score:.3f} gen={dt:.1f}s "
          f"q={q[:50]}  → ans={answer[:60]}")

out = ROOT / "eval_results" / "_faithfulness_rerun.json"
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSaved {len(results)} re-runs → {out}")
