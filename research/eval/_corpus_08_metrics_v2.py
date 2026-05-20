"""Retrieval metrics on v2 index using 54 remapped GT (multi-GT)."""
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

emb = get_embeddings_model()
vec_store = FAISS.load_local(
    folder_path=str(ROOT / "data" / "rag_vector_store_full_v2"),
    embeddings=emb,
    index_name="knowledge",
    allow_dangerous_deserialization=True,
)
print(f"[init] v2 index ntotal = {vec_store.index.ntotal}")

chunks = json.loads((ROOT / "eval_results" / "_chunks_full_v2.json").read_text(encoding="utf-8"))
chunk_id_to_content = {c["chunk_id"]: c["content"] for c in chunks}
gt = json.loads((ROOT / "eval_results" / "_gt_questions_v2.json").read_text(encoding="utf-8"))
print(f"[init] {len(gt)} GT questions (multi-GT)")

results = []
relevant_L2 = []
distractor_L2 = []

for q in gt:
    qid = q["qid"]
    question = q["question"]
    gt_ids = set(q["gt_chunk_ids_v2"])
    gt_contents = {chunk_id_to_content[i] for i in gt_ids}

    t = time.time()
    docs_scores = vec_store.similarity_search_with_score(question, k=vec_store.index.ntotal)
    retrieve_ms = (time.time() - t) * 1000

    ranked = [{"content": d.page_content, "L2": float(s)} for d, s in docs_scores]
    # rank = first position of ANY GT chunk
    rank = None
    for i, r in enumerate(ranked, start=1):
        if r["content"] in gt_contents:
            rank = i
            relevant_L2.append({"qid": qid, "L2": r["L2"]})
            break

    # Distractors: top-10 chunks that are NOT in gt_contents
    for r in ranked[:10]:
        if r["content"] not in gt_contents:
            distractor_L2.append({"qid": qid, "L2": r["L2"]})

    top5 = [r["content"] for r in ranked[:5]]
    in_top1 = top5[0] in gt_contents
    in_top3 = any(c in gt_contents for c in top5[:3])
    in_top5 = any(c in gt_contents for c in top5)
    rr = (1.0 / rank) if (rank is not None and rank <= 5) else 0.0

    results.append({
        "qid": qid,
        "from": q.get("from", "?"),
        "gt_source": q["gt_source"],
        "gt_chunk_ids": list(gt_ids),
        "rank": rank,
        "top1": in_top1, "top3": in_top3, "top5": in_top5,
        "rr_top5": rr,
        "top1_L2": ranked[0]["L2"],
        "retrieve_ms": retrieve_ms,
    })
    flag = "✓" if in_top1 else ("." if in_top5 else "✗")
    print(f"[Q#{qid:>2}] {flag} rank={rank:>3} L2={ranked[0]['L2']:.3f} "
          f"GT={list(gt_ids)} | [{q.get('from','?')}] {question[:46]}")

N = len(results)
p1 = sum(r["top1"] for r in results) / N
p3 = sum(r["top3"] for r in results) / N
p5 = sum(r["top5"] for r in results) / N
mrr = sum(r["rr_top5"] for r in results) / N

print("\n" + "=" * 60)
print(f"AGGREGATE METRICS (v2 preprocessed, N={N})")
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

# Latency (warmup skip)
ret_times = sorted(r["retrieve_ms"] for r in results)[1:]  # skip warmup outlier
print(f"\nretrieve_full timing (skip warmup, k={vec_store.index.ntotal}):")
print(f"  p50={ret_times[len(ret_times)//2]:.1f} ms")
print(f"  p95={ret_times[int(len(ret_times)*0.95) if len(ret_times) > 5 else -1]:.1f} ms")
print(f"  mean={statistics.mean(ret_times):.1f} ms")

# L2 distribution
rel = sorted(x["L2"] for x in relevant_L2)
dis = sorted(x["L2"] for x in distractor_L2)
def quantile(arr, q):
    return arr[min(int(q*len(arr)), len(arr)-1)] if arr else 0
print(f"\nRelevant L2 (N={len(rel)}):")
if rel:
    print(f"  min={rel[0]:.3f} p50={quantile(rel,.5):.3f} p95={quantile(rel,.95):.3f} "
          f"max={rel[-1]:.3f}  mean={statistics.mean(rel):.3f}")
print(f"Distractor L2 (N={len(dis)}):")
if dis:
    print(f"  min={dis[0]:.3f} p50={quantile(dis,.5):.3f} p95={quantile(dis,.95):.3f} "
          f"max={dis[-1]:.3f}  mean={statistics.mean(dis):.3f}")

# Thresholds
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
    rec = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    if best is None or f1 > best[3]:
        best = (thr, prec, rec, f1)
print(f"\nF1-optimal: thr={best[0]} prec={best[1]:.3f} rec={best[2]:.3f} F1={best[3]:.3f}")

# Save
(ROOT / "eval_results" / "_retrieval_metrics_v2.json").write_text(
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

# Histogram
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.figure(figsize=(8, 4.5))
    bins = [i * 0.1 for i in range(21)]
    plt.hist(rel, bins=bins, alpha=0.7, label=f"relevant n={len(rel)}", color="#2c7a3a")
    plt.hist(dis, bins=bins, alpha=0.5, label=f"distractor n={len(dis)}", color="#a63a3a")
    for thr in (0.8, 1.2, 1.5):
        plt.axvline(thr, color="black", linestyle=":", alpha=0.7, linewidth=1)
        plt.text(thr, plt.gca().get_ylim()[1] * 0.95, f" {thr}", verticalalignment="top")
    plt.axvline(best[0], color="blue", linestyle="--", linewidth=1.5, label=f"F1-optimal = {best[0]:.2f}")
    plt.xlabel("L2 distance"); plt.ylabel("count")
    plt.title(f"L2 distribution — v2 preprocessed (N={vec_store.index.ntotal})")
    plt.legend(); plt.tight_layout()
    plt.savefig(ROOT / "eval_results" / "L2_distribution_v2.png", dpi=120)
    print("Saved → eval_results/L2_distribution_v2.png")
except Exception as e:
    print(f"matplotlib failed: {e}")
