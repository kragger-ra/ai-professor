"""Retrieval metrics on the FULL corpus index using the 57-question GT.

Mirrors `_rag_eval_03_metrics.py` but points at data/rag_vector_store_full/.
Adds per-week breakdown and old/new question split for like-for-like comparison.
"""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

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

from langchain_community.vectorstores import FAISS
from agent.llm_clients.lc_clients import get_embeddings_model

print("[init] embeddings model")
emb = get_embeddings_model()
print("[init] load FAISS")
t = time.time()
vec_store = FAISS.load_local(
    folder_path=str(ROOT / "data" / "rag_vector_store_full"),
    embeddings=emb,
    index_name="knowledge",
    allow_dangerous_deserialization=True,
)
print(f"[init] load done in {time.time()-t:.2f}s")
print(f"[init] ntotal = {vec_store.index.ntotal}")

chunks = json.loads((ROOT / "eval_results" / "_chunks_full.json").read_text(encoding="utf-8"))
chunk_id_to_content = {c["chunk_id"]: c["content"] for c in chunks}
gt = json.loads((ROOT / "eval_results" / "_gt_questions_full.json").read_text(encoding="utf-8"))
print(f"[init] {len(gt)} GT questions")

results = []
relevant_L2 = []
distractor_L2 = []

for q in gt:
    qid = q["qid"]
    question = q["question"]
    gt_id = q["gt_chunk_id"]
    gt_content = chunk_id_to_content[gt_id]

    t = time.time()
    docs_scores = vec_store.similarity_search_with_score(question, k=vec_store.index.ntotal)
    retrieve_ms = (time.time() - t) * 1000

    ranked = [{"content": d.page_content, "L2": float(s)} for d, s in docs_scores]
    rank = None
    for i, r in enumerate(ranked, start=1):
        if r["content"] == gt_content:
            rank = i
            relevant_L2.append({"qid": qid, "L2": r["L2"]})
            break

    for r in ranked[:10]:
        if r["content"] != gt_content:
            distractor_L2.append({"qid": qid, "L2": r["L2"]})

    top5 = [r["content"] for r in ranked[:5]]
    results.append({
        "qid": qid,
        "from": q.get("from", "?"),
        "question": question,
        "gt_chunk_id": gt_id,
        "gt_source": q["gt_source"],
        "retrieve_ms": retrieve_ms,
        "rank": rank,
        "top1": gt_content == top5[0],
        "top3": gt_content in top5[:3],
        "top5": gt_content in top5,
        "rr_top5": (1.0 / rank) if (rank is not None and rank <= 5) else 0.0,
        "top1_L2": ranked[0]["L2"],
    })
    flag = "✓" if (gt_content == top5[0]) else ("." if gt_content in top5 else "✗")
    print(f"[Q#{qid:>2}] {flag} rank={rank:>3} L2={ranked[0]['L2']:.3f} "
          f"{retrieve_ms:.1f}ms | [{q.get('from','?')}] {question[:50]}")

N = len(results)
p1 = sum(r["top1"] for r in results) / N
p3 = sum(r["top3"] for r in results) / N
p5 = sum(r["top5"] for r in results) / N
mrr = sum(r["rr_top5"] for r in results) / N

print("\n" + "=" * 60)
print(f"AGGREGATE METRICS (full corpus, N={N})")
print("=" * 60)
print(f"  precision@1 = {p1:.3f}  ({sum(r['top1'] for r in results)}/{N})")
print(f"  precision@3 = {p3:.3f}  ({sum(r['top3'] for r in results)}/{N})")
print(f"  precision@5 = {p5:.3f}  ({sum(r['top5'] for r in results)}/{N})")
print(f"  MRR@5       = {mrr:.3f}")

# Old/new split
for tag in ("old", "new"):
    rs = [r for r in results if r["from"] == tag]
    if not rs:
        continue
    print(f"\n  Subset '{tag}' (N={len(rs)}):")
    print(f"    P@1={sum(r['top1'] for r in rs)/len(rs):.3f}  "
          f"P@3={sum(r['top3'] for r in rs)/len(rs):.3f}  "
          f"P@5={sum(r['top5'] for r in rs)/len(rs):.3f}  "
          f"MRR={sum(r['rr_top5'] for r in rs)/len(rs):.3f}")

# By source
by_src = defaultdict(lambda: {"n": 0, "p1": 0, "p3": 0, "p5": 0})
for r in results:
    s = by_src[r["gt_source"]]
    s["n"] += 1
    s["p1"] += int(r["top1"])
    s["p3"] += int(r["top3"])
    s["p5"] += int(r["top5"])
print("\nBy source:")
for src in sorted(by_src):
    s = by_src[src]
    print(f"  {src:<30} P@1={s['p1']}/{s['n']:<2} P@3={s['p3']}/{s['n']:<2} P@5={s['p5']}/{s['n']}")

ret_times = sorted(r["retrieve_ms"] for r in results)
print(f"\nretrieve_full timing (full k={vec_store.index.ntotal} search):")
print(f"  p50={ret_times[len(ret_times)//2]:.1f} ms")
print(f"  p95={ret_times[int(len(ret_times)*0.95) if len(ret_times) > 5 else -1]:.1f} ms")
print(f"  mean={statistics.mean(ret_times):.1f} ms")

# L2 distribution
rel = sorted(x["L2"] for x in relevant_L2)
dis = sorted(x["L2"] for x in distractor_L2)
def quantile(arr, q):
    return arr[min(int(q*len(arr)), len(arr)-1)]
print(f"\nRelevant L2 (N={len(rel)}):")
print(f"  min={rel[0]:.3f} p25={quantile(rel,.25):.3f} p50={quantile(rel,.5):.3f} "
      f"p75={quantile(rel,.75):.3f} p95={quantile(rel,.95):.3f} max={rel[-1]:.3f}  "
      f"mean={statistics.mean(rel):.3f} stdev={statistics.stdev(rel):.3f}")
print(f"\nDistractor L2 (N={len(dis)}):")
print(f"  min={dis[0]:.3f} p25={quantile(dis,.25):.3f} p50={quantile(dis,.5):.3f} "
      f"p75={quantile(dis,.75):.3f} p95={quantile(dis,.95):.3f} max={dis[-1]:.3f}  "
      f"mean={statistics.mean(dis):.3f} stdev={statistics.stdev(dis):.3f}")

# Threshold validation
print("\nThreshold validation:")
for thr in (0.8, 1.2, 1.5):
    rb = sum(1 for x in rel if x < thr)
    db = sum(1 for x in dis if x < thr)
    print(f"  L2<{thr}: relevant {rb}/{len(rel)} ({rb/len(rel)*100:.0f}%)  "
          f"distractor {db}/{len(dis)} ({db/len(dis)*100:.0f}%)")

# F1 sweep
best = None
for thr in [round(x * 0.05, 2) for x in range(10, 41)]:
    rb = sum(1 for x in rel if x < thr)
    db = sum(1 for x in dis if x < thr)
    tp, fp, fn = rb, db, len(rel) - rb
    prec = tp / (tp + fp) if (tp + fp) else 0
    recl = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * prec * recl / (prec + recl) if (prec + recl) else 0
    if best is None or f1 > best[3]:
        best = (thr, prec, recl, f1)
print(f"\nF1-optimal threshold: {best[0]:.2f}  prec={best[1]:.3f} rec={best[2]:.3f} F1={best[3]:.3f}")

# Save
(ROOT / "eval_results" / "_retrieval_metrics_full.json").write_text(
    json.dumps({
        "summary": {
            "N": N, "ntotal": vec_store.index.ntotal,
            "precision_at_1": p1, "precision_at_3": p3, "precision_at_5": p5,
            "recall_at_5": p5, "MRR_at_5": mrr,
            "f1_optimal_threshold": best[0], "f1_optimal": best[3],
        },
        "per_query": results,
        "relevant_L2": relevant_L2,
        "distractor_L2": distractor_L2,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("\nSaved → eval_results/_retrieval_metrics_full.json")

# Histogram PNG
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.figure(figsize=(8, 4.5))
    bins_edges = [i * 0.1 for i in range(21)]
    plt.hist(rel, bins=bins_edges, alpha=0.7, label=f"relevant n={len(rel)}", color="#2c7a3a")
    plt.hist(dis, bins=bins_edges, alpha=0.5, label=f"distractor n={len(dis)}", color="#a63a3a")
    for thr in (0.8, 1.2, 1.5):
        plt.axvline(thr, color="black", linestyle=":", alpha=0.7, linewidth=1)
        plt.text(thr, plt.gca().get_ylim()[1] * 0.95, f" {thr}", verticalalignment="top")
    plt.axvline(best[0], color="blue", linestyle="--", linewidth=1.5,
                label=f"F1-optimal = {best[0]:.2f}")
    plt.xlabel("L2 distance (lower = more similar)")
    plt.ylabel("count")
    plt.title(f"L2 distribution — full corpus (N={vec_store.index.ntotal} chunks)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(ROOT / "eval_results" / "L2_distribution_full.png", dpi=120)
    print("Saved histogram → eval_results/L2_distribution_full.png")
except Exception as e:
    print(f"matplotlib failed: {e}")
