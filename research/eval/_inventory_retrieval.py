"""FAISS retrieval timing — runs after LM Studio bge-m3 is up."""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Manually load .env into os.environ
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    v = v.strip().strip('"').strip("'")
    os.environ[k.strip()] = v

sys.path.insert(0, str(ROOT / "src"))


def gpu_used():
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            text=True, encoding="utf-8",
        ).strip()
        return int(out)
    except Exception:
        return None


print("[RAG] GPU before embeddings:", gpu_used(), "MiB")

from agent.rag import RagModel
t0 = time.time()
rag = RagModel()
print(f"[RAG] Init took {time.time() - t0:.2f}s")
print("[RAG] GPU after embeddings load:", gpu_used(), "MiB")

QUESTIONS = [
    "Что такое цифровой персонаж в курсе?",
    "Объясни разницу между summary и rank в архитектуре агента",
    "Что такое prefill?",
    "Как работает Like Tool?",
    "Что такое tool_status?",
    "Зачем нужен RAG в этой архитектуре?",
    "Что делает Whisper в pipeline?",
    "Зачем Vosk TTS, а не piper?",
    "Что хранится в FAISS-индексе?",
    "Чем меня-агент отличается от основного агента?",
]

# Warmup
rag.retrieve_full(QUESTIONS[0])

results = []
for q in QUESTIONS:
    t = time.time()
    docs = rag.retrieve_full(q)
    dt = (time.time() - t) * 1000
    scores = [s for _, s in docs]
    best = min(scores) if scores else None
    results.append({"q": q, "ms": dt, "top_score": best, "n": len(docs)})
    print(f"  {dt:6.1f} ms  top_L2={best:.3f}" if best is not None else f"  {dt:6.1f} ms  no docs",
          f"  | {q[:50]}")

times = sorted(r["ms"] for r in results)
print()
print(f"[RAG] retrieve_full p50 = {times[len(times)//2]:.1f} ms")
print(f"[RAG] retrieve_full p95 = {times[int(len(times)*0.95) if len(times) > 5 else -1]:.1f} ms")
print(f"[RAG] retrieve_full min/max = {times[0]:.1f} / {times[-1]:.1f} ms")
print(f"[RAG] retrieve_full mean = {statistics.mean(times):.1f} ms")

# Distribution of top-1 L2 scores
scores = [r["top_score"] for r in results if r["top_score"] is not None]
if scores:
    scores.sort()
    print(f"\n[RAG] top-1 L2 across queries: min={scores[0]:.3f} median={scores[len(scores)//2]:.3f} max={scores[-1]:.3f}")

(ROOT / "_inventory_retrieval_results.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\nsaved → _inventory_retrieval_results.json")
print("\n[RAG] final GPU:", gpu_used(), "MiB")
