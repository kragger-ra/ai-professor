"""Retrieval metrics P@1/3/5 + MRR + L2 separability for the White Coding RAG."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
os.chdir(REPO)
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"

for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(REPO / "src"))

from langchain_community.vectorstores import FAISS  # noqa
from agent.llm_clients.lc_clients import get_embeddings_model  # noqa

STORE_DIR = REPO / "data" / "rag_vector_store"

emb = get_embeddings_model()
vec = FAISS.load_local(
    folder_path=str(STORE_DIR), embeddings=emb, index_name="knowledge",
    allow_dangerous_deserialization=True,
)
N_CHUNKS = len(vec.index_to_docstore_id)
print(f"[RAG] {N_CHUNKS} chunks loaded")

chunks = json.loads((HERE / "_chunks.json").read_text(encoding="utf-8"))
id_to_content = {c["chunk_id"]: c["content"] for c in chunks}

gt = json.loads((HERE / "_gt_questions.json").read_text(encoding="utf-8"))
print(f"[GT] {len(gt)} questions\n")

results, relevant_L2, distractor_L2 = [], [], []

for q in gt:
    gt_content = id_to_content[q["gt_chunk_id"]]
    t = time.time()
    docs_scores = vec.similarity_search_with_score(q["question"], k=N_CHUNKS)
    retrieve_ms = (time.time() - t) * 1000

    ranked = [(d.page_content, float(s)) for d, s in docs_scores]
    rank = None
    for i, (content, L2) in enumerate(ranked, start=1):
        if content == gt_content:
            rank = i
            relevant_L2.append(L2)
            break
    for content, L2 in ranked[:10]:
        if content != gt_content:
            distractor_L2.append(L2)

    top5 = [c for c, _ in ranked[:5]]
    in1, in3, in5 = (gt_content == top5[0]), (gt_content in top5[:3]), (gt_content in top5)
    rr = (1.0 / rank) if (rank and rank <= 5) else 0.0
    results.append({
        "qid": q["qid"], "theme": q["theme"], "question": q["question"],
        "gt_chunk_id": q["gt_chunk_id"], "gt_source": q["gt_source"],
        "rank": rank, "top1": in1, "top3": in3, "top5": in5, "rr": rr,
        "retrieve_ms": retrieve_ms, "top1_L2": ranked[0][1],
    })
    flag = "OK " if in1 else (" . " if in5 else "XXX")
    print(f"[Q{q['qid']:>2}] {flag} rank={str(rank):>3}  L2top1={ranked[0][1]:.3f}  "
          f"{retrieve_ms:5.1f}ms | {q['question'][:52]}")

N = len(results)
p1 = sum(r["top1"] for r in results) / N
p3 = sum(r["top3"] for r in results) / N
p5 = sum(r["top5"] for r in results) / N
mrr = sum(r["rr"] for r in results) / N

print("\n" + "=" * 60)
print(f"AGGREGATE METRICS (N={N}, corpus={N_CHUNKS} chunks)")
print("=" * 60)
print(f"  precision@1 = {p1:.3f}  ({sum(r['top1'] for r in results)}/{N})")
print(f"  precision@3 = {p3:.3f}  ({sum(r['top3'] for r in results)}/{N})")
print(f"  precision@5 = {p5:.3f}  ({sum(r['top5'] for r in results)}/{N})")
print(f"  MRR@5       = {mrr:.3f}")

by_theme = defaultdict(lambda: {"n": 0, "p1": 0, "p3": 0, "p5": 0})
for r in results:
    s = by_theme[r["theme"]]
    s["n"] += 1
    s["p1"] += int(r["top1"]); s["p3"] += int(r["top3"]); s["p5"] += int(r["top5"])
print("\nBy theme:")
for th, s in by_theme.items():
    print(f"  {th:9s}: P@1={s['p1']}/{s['n']}  P@3={s['p3']}/{s['n']}  P@5={s['p5']}/{s['n']}")

misses = [r for r in results if not r["top5"]]
if misses:
    print(f"\nMisses (rank>5): {len(misses)}")
    for r in misses:
        print(f"  Q{r['qid']} rank={r['rank']} | {r['question'][:55]}")

rt = sorted(r["retrieve_ms"] for r in results)
print(f"\nRetrieval latency: p50={rt[len(rt)//2]:.1f}ms  "
      f"p95={rt[min(int(len(rt)*0.95), len(rt)-1)]:.1f}ms  mean={statistics.mean(rt):.1f}ms")

rel, dis = sorted(relevant_L2), sorted(distractor_L2)
def qn(a, q): return a[min(int(q*len(a)), len(a)-1)]
print("\n" + "=" * 60)
print("L2 SEPARABILITY (lower = more similar)")
print("=" * 60)
print(f"Relevant   (q<->GT)      n={len(rel)}: "
      f"min={rel[0]:.3f} p50={qn(rel,.5):.3f} mean={statistics.mean(rel):.3f} max={rel[-1]:.3f}")
print(f"Distractor (q<->non-GT)  n={len(dis)}: "
      f"min={dis[0]:.3f} p50={qn(dis,.5):.3f} mean={statistics.mean(dis):.3f} max={dis[-1]:.3f}")

best = None
for thr in [round(x*0.05, 2) for x in range(8, 41)]:
    tp = sum(1 for x in rel if x < thr); fp = sum(1 for x in dis if x < thr)
    fn = len(rel) - tp
    prec = tp/(tp+fp) if tp+fp else 0
    rec = tp/(tp+fn) if tp+fn else 0
    f1 = 2*prec*rec/(prec+rec) if prec+rec else 0
    if best is None or f1 > best[1]:
        best = (thr, f1, prec, rec)
print(f"Best-F1 threshold = {best[0]:.2f}  (F1={best[1]:.3f} prec={best[2]:.3f} rec={best[3]:.3f})")
gap = statistics.mean(dis) - statistics.mean(rel)
print(f"Mean gap (distractor - relevant) = {gap:.3f}")

(HERE / "_retrieval_metrics.json").write_text(json.dumps({
    "corpus_chunks": N_CHUNKS, "n_questions": N,
    "precision_at_1": p1, "precision_at_3": p3, "precision_at_5": p5, "mrr_at_5": mrr,
    "by_theme": {k: dict(v) for k, v in by_theme.items()},
    "relevant_L2_mean": statistics.mean(rel), "distractor_L2_mean": statistics.mean(dis),
    "best_f1_threshold": best[0], "best_f1": best[1],
    "latency_p50_ms": rt[len(rt)//2],
    "per_query": results,
}, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSaved -> {HERE / '_retrieval_metrics.json'}")
