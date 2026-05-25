"""Inventory probe for the White Coding RAG package.

Read-only.  Loads the persisted FAISS index from data/rag_vector_store/ via the
live tutor.brain.rag.RagModel (current v2 code path), reports corpus / chunk /
embedder parameters, samples chunks, and runs a smoke retrieval.

Does NOT rebuild, modify, switch, or persist anything.  RagModel.__init__ only
reads the on-disk index when it already exists (load_vec_store, db_exists path).
"""
from __future__ import annotations

import json
import os
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
sys.path.insert(0, str(REPO))

from tutor.brain.rag import RagModel, RAG_STORE_DIR  # noqa: E402

out: dict = {}

t0 = time.time()
rag = RagModel()
out["init_time_s"] = round(time.time() - t0, 2)

idx = rag.vec_store.index
docs = rag.docs  # re-derived from the on-disk docstore by the startup-mismatch fix

out["faiss_type"] = type(idx).__name__
out["ntotal"] = int(idx.ntotal)
out["dim"] = int(idx.d)
out["docstore_len"] = len(docs)

faiss_path = Path(RAG_STORE_DIR) / "knowledge.faiss"
pkl_path = Path(RAG_STORE_DIR) / "knowledge.pkl"
out["faiss_bytes"] = faiss_path.stat().st_size
out["pkl_bytes"] = pkl_path.stat().st_size

lengths = sorted(len(d.page_content) for d in docs)
out["chunk_chars"] = {
    "min": lengths[0],
    "median": statistics.median(lengths),
    "mean": round(statistics.mean(lengths), 1),
    "max": lengths[-1],
    "total": sum(lengths),
}

mdkeys = Counter()
for d in docs:
    for k in d.metadata.keys():
        mdkeys[k] += 1
out["metadata_keys"] = {k: n for k, n in mdkeys.most_common()}
out["subject"] = dict(Counter(d.metadata.get("subject") for d in docs))
out["kind"] = dict(Counter(d.metadata.get("kind") for d in docs))
out["source"] = dict(
    Counter(Path(str(d.metadata.get("source", "?"))).name for d in docs)
)

# Embedder config (from env, as the live code reads it)
out["embeddings"] = {
    "EMBEDDINGS_MODEL": os.getenv("EMBEDDINGS_MODEL"),
    "EMBEDDINGS_API_BASE": os.getenv("EMBEDDINGS_API_BASE"),
}

# Full chunk dump: index, first line (sub-section heading), char count
out["chunks"] = [
    {
        "i": i,
        "chars": len(d.page_content),
        "head": d.page_content.split("\n", 1)[0][:90],
        "kind": d.metadata.get("kind"),
        "subject": d.metadata.get("subject"),
    }
    for i, d in enumerate(docs)
]

# 3 deterministic random samples
random.seed(42)
sample_idx = sorted(random.sample(range(len(docs)), 3))
out["samples"] = [
    {
        "i": i,
        "chars": len(docs[i].page_content),
        "metadata": docs[i].metadata,
        "text": docs[i].page_content,
    }
    for i in sample_idx
]

# Smoke retrieval — green-student phrasing, top-3 with L2
QUESTIONS = [
    "Что такое режим планирования?",
    "Чем Claude Code отличается от Codex?",
    "Как работает команда init?",
    "Что такое вайб-кодинг?",
    "Зачем нужен контроль версий?",
]
smoke = []
for q in QUESTIONS:
    t1 = time.time()
    res = rag.retrieve_full(q)
    dt_ms = round((time.time() - t1) * 1000, 1)
    smoke.append(
        {
            "q": q,
            "latency_ms": dt_ms,
            "top3": [
                {
                    "rank": r + 1,
                    "l2": round(float(score), 3),
                    "head": d.page_content.split("\n", 1)[0][:80],
                }
                for r, (d, score) in enumerate(res[:3])
            ],
        }
    )
out["smoke"] = smoke

raw_path = Path(__file__).resolve().parent / "_wc_inventory_raw.json"
raw_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")

# ----- console summary -----
print("\n" + "=" * 64)
print("WHITE CODING RAG INVENTORY PROBE")
print("=" * 64)
print(f"init_time_s     = {out['init_time_s']}")
print(f"faiss_type      = {out['faiss_type']}")
print(f"ntotal          = {out['ntotal']}")
print(f"dim             = {out['dim']}")
print(f"docstore_len    = {out['docstore_len']}")
print(f"faiss bytes     = {out['faiss_bytes']}")
print(f"pkl bytes       = {out['pkl_bytes']}")
print(f"chunk chars     = {out['chunk_chars']}")
print(f"metadata keys   = {out['metadata_keys']}")
print(f"subject         = {out['subject']}")
print(f"kind            = {out['kind']}")
print(f"source          = {out['source']}")
print(f"embeddings      = {out['embeddings']}")
print("\n--- SMOKE RETRIEVAL (top-3, L2) ---")
for s in smoke:
    print(f"\nQ: {s['q']}  ({s['latency_ms']} ms)")
    for t in s["top3"]:
        print(f"  {t['rank']}. L2={t['l2']:.3f}  {t['head']}")
print(f"\nraw dump -> {raw_path}")
