"""Run retrieval-метрики P@1/3/5 + MRR + L2 distributions for relevant vs distractor."""
from __future__ import annotations

import json
import os
import statistics
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Load .env
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, str(ROOT / "src"))

from agent.rag import RagModel  # noqa
from langchain_community.vectorstores import FAISS  # noqa

print("[RAG] init...")
t0 = time.time()
rag = RagModel()
print(f"[RAG] init done in {time.time() - t0:.2f}s")

# Map chunk_id (FAISS position) -> doc_id (langchain UUID) using vec_store.index_to_docstore_id
index_to_id = rag.vec_store.index_to_docstore_id
id_to_index = {v: k for k, v in index_to_id.items()}
print(f"[RAG] {len(index_to_id)} chunks indexed")

chunks = json.loads((ROOT / "eval_results" / "_chunks.json").read_text(encoding="utf-8"))
chunk_id_to_content = {c["chunk_id"]: c["content"] for c in chunks}

gt = json.loads((ROOT / "eval_results" / "_gt_questions.json").read_text(encoding="utf-8"))
print(f"[GT] {len(gt)} questions loaded")

# ----------------------------------------------------------------------
# Run retrieval, record full ranking for each query
# ----------------------------------------------------------------------
results = []
relevant_L2 = []       # (qid, gt_chunk_id, L2 distance to gt)
distractor_L2 = []     # all (q, non-gt) pairs in top-10 (rich set for histogram)

for q in gt:
    qid = q["qid"]
    question = q["question"]
    gt_id = q["gt_chunk_id"]

    # Get ALL 140 ranked
    t = time.time()
    docs_scores = rag.vec_store.similarity_search_with_score(question, k=140)
    retrieve_ms = (time.time() - t) * 1000

    # Build ranked list of chunk_ids by matching doc UUID
    ranked = []
    for doc, score in docs_scores:
        # doc.id may not be set; match by content
        # Faster: match by content equality against chunk_id->content map
        # langchain FAISS keeps doc objects from docstore; metadata.source is set,
        # but uuid isn't on doc directly. We match by exact page_content equality.
        ranked.append({"content": doc.page_content, "L2": float(score)})

    # Find rank of GT chunk by content equality
    gt_content = chunk_id_to_content[gt_id]
    rank = None
    for i, r in enumerate(ranked, start=1):
        if r["content"] == gt_content:
            rank = i
            relevant_L2.append({"qid": qid, "gt_chunk_id": gt_id, "L2": r["L2"]})
            break

    # Top-10 non-GT for distractor histogram
    distractor_count = 0
    for r in ranked[:10]:
        if r["content"] != gt_content:
            distractor_L2.append({"qid": qid, "L2": r["L2"]})
            distractor_count += 1

    top5_contents = [r["content"] for r in ranked[:5]]
    in_top1 = gt_content == top5_contents[0]
    in_top3 = gt_content in top5_contents[:3]
    in_top5 = gt_content in top5_contents

    rr = (1.0 / rank) if (rank is not None and rank <= 5) else 0.0

    results.append({
        "qid": qid,
        "question": question,
        "gt_chunk_id": gt_id,
        "gt_source": q["gt_source"],
        "retrieve_ms": retrieve_ms,
        "rank": rank,
        "top1": in_top1,
        "top3": in_top3,
        "top5": in_top5,
        "rr_top5": rr,
        "top1_L2": ranked[0]["L2"],
        "top3_L2": [r["L2"] for r in ranked[:3]],
    })
    flag = "✓" if in_top1 else ("." if in_top5 else "✗")
    print(f"[Q#{qid:>2}] {flag} rank={rank}  top1_L2={ranked[0]['L2']:.3f}  "
          f"{retrieve_ms:.1f}ms  | {question[:55]}")

# ----------------------------------------------------------------------
# Aggregate metrics
# ----------------------------------------------------------------------
N = len(results)
p1 = sum(r["top1"] for r in results) / N
p3 = sum(r["top3"] for r in results) / N
p5 = sum(r["top5"] for r in results) / N
recall5 = p5  # same thing in single-GT setup
mrr = sum(r["rr_top5"] for r in results) / N

print()
print("=" * 60)
print(f"AGGREGATE METRICS (N={N})")
print("=" * 60)
print(f"  precision@1 = {p1:.3f}  ({sum(r['top1'] for r in results)}/{N})")
print(f"  precision@3 = {p3:.3f}  ({sum(r['top3'] for r in results)}/{N})")
print(f"  precision@5 = {p5:.3f}  ({sum(r['top5'] for r in results)}/{N})")
print(f"  recall@5    = {recall5:.3f}")
print(f"  MRR@5       = {mrr:.3f}")

# Where misses occur
misses = [r for r in results if not r["top5"]]
if misses:
    print(f"\n  Misses (rank > 5): {len(misses)}")
    for r in misses:
        print(f"    Q#{r['qid']:2d} rank={r['rank']}  src={r['gt_source']}  | {r['question'][:60]}")

# Source breakdown
from collections import defaultdict
by_src = defaultdict(lambda: {"n": 0, "p1": 0, "p3": 0, "p5": 0})
for r in results:
    s = by_src[r["gt_source"]]
    s["n"] += 1
    s["p1"] += int(r["top1"])
    s["p3"] += int(r["top3"])
    s["p5"] += int(r["top5"])
print("\nBy source:")
for src, s in by_src.items():
    print(f"  {src}: P@1={s['p1']}/{s['n']}  P@3={s['p3']}/{s['n']}  P@5={s['p5']}/{s['n']}")

# Retrieval timing
ret_times = sorted(r["retrieve_ms"] for r in results)
print(f"\nretrieve_full timing (full k=140 search):")
print(f"  p50={ret_times[len(ret_times)//2]:.1f} ms")
print(f"  p95={ret_times[int(len(ret_times)*0.95) if len(ret_times) > 5 else -1]:.1f} ms")
print(f"  mean={statistics.mean(ret_times):.1f} ms")

# Save everything
(ROOT / "eval_results" / "_retrieval_metrics.json").write_text(
    json.dumps({
        "summary": {
            "N": N,
            "precision_at_1": p1,
            "precision_at_3": p3,
            "precision_at_5": p5,
            "recall_at_5": recall5,
            "MRR_at_5": mrr,
        },
        "per_query": results,
        "relevant_L2": relevant_L2,
        "distractor_L2": distractor_L2,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("\nSaved → eval_results/_retrieval_metrics.json")

# ----------------------------------------------------------------------
# L2 distribution + threshold validation
# ----------------------------------------------------------------------
rel = [x["L2"] for x in relevant_L2]
dis = [x["L2"] for x in distractor_L2]
rel.sort()
dis.sort()

def quantile(arr, q):
    if not arr:
        return None
    i = int(q * len(arr))
    i = min(i, len(arr) - 1)
    return arr[i]

print()
print("=" * 60)
print("L2 DISTRIBUTION")
print("=" * 60)
print(f"Relevant L2 (q ↔ GT chunk), N={len(rel)}:")
print(f"  min={rel[0]:.3f}  p25={quantile(rel,.25):.3f}  p50={quantile(rel,.5):.3f}  "
      f"p75={quantile(rel,.75):.3f}  p95={quantile(rel,.95):.3f}  max={rel[-1]:.3f}")
print(f"  mean={statistics.mean(rel):.3f}  stdev={statistics.stdev(rel):.3f}")

print(f"\nDistractor L2 (q ↔ non-GT top-10 chunk), N={len(dis)}:")
print(f"  min={dis[0]:.3f}  p25={quantile(dis,.25):.3f}  p50={quantile(dis,.5):.3f}  "
      f"p75={quantile(dis,.75):.3f}  p95={quantile(dis,.95):.3f}  max={dis[-1]:.3f}")
print(f"  mean={statistics.mean(dis):.3f}  stdev={statistics.stdev(dis):.3f}")

# Threshold validation: 0.8 / 1.2 / 1.5
print()
print("Threshold validation (current code: <0.8 high / <1.2 partial / <1.5 low / >1.5 drop):")
for label, thr in [("<0.8", 0.8), ("<1.2", 1.2), ("<1.5", 1.5)]:
    rel_pass = sum(1 for x in rel if x < thr)
    dis_pass = sum(1 for x in dis if x < thr)
    rel_pct = rel_pass / len(rel) * 100
    dis_pct = dis_pass / len(dis) * 100
    print(f"  L2{label:>5}: relevant {rel_pass}/{len(rel)} ({rel_pct:.0f}%)  "
          f"distractor {dis_pass}/{len(dis)} ({dis_pct:.0f}%)")

# Suggest optimal threshold (max F1 between classes) using simple sweep
print()
print("Threshold sweep (maximize separability):")
best = None
for thr in [round(x * 0.05, 2) for x in range(10, 41)]:  # 0.5..2.0 step 0.05
    rel_below = sum(1 for x in rel if x < thr)
    dis_below = sum(1 for x in dis if x < thr)
    # Treat 'below threshold' as 'predicted relevant'
    tp = rel_below
    fp = dis_below
    fn = len(rel) - rel_below
    tn = len(dis) - dis_below
    prec = tp / (tp + fp) if (tp + fp) else 0
    rec = tp / (tp + fn) if (tp + fn) else 0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0
    if best is None or f1 > best[3]:
        best = (thr, prec, rec, f1, tp, fp, fn, tn)
print(f"  Best F1 threshold = {best[0]:.2f}: prec={best[1]:.3f} rec={best[2]:.3f} "
      f"F1={best[3]:.3f} (TP={best[4]} FP={best[5]} FN={best[6]} TN={best[7]})")

# ASCII histogram for the report (10 bins from 0 to 2.0)
def histogram(arr, lo, hi, bins=10):
    width = (hi - lo) / bins
    counts = [0] * bins
    for x in arr:
        b = int((x - lo) / width)
        if 0 <= b < bins:
            counts[b] += 1
        elif x >= hi:
            counts[-1] += 1
    return counts, width

bins = 10
hi = 2.0
rel_h, w = histogram(rel, 0, hi, bins)
dis_h, _ = histogram(dis, 0, hi, bins)
max_count = max(max(rel_h), max(dis_h))
SCALE = 30  # chars wide
print()
print("ASCII histogram (bin width = {:.2f}):".format(w))
print(f"{'bin':>10}  {'relevant':>30}  {'distractor':>30}")
for i in range(bins):
    lo_ = i * w
    hi_ = (i + 1) * w
    r_n = rel_h[i]
    d_n = dis_h[i]
    r_bar = "█" * int(r_n / max_count * SCALE) if r_n else ""
    d_bar = "█" * int(d_n / max_count * SCALE) if d_n else ""
    print(f"  {lo_:.2f}-{hi_:.2f}  {r_bar:<{SCALE}} {r_n:>3}  {d_bar:<{SCALE}} {d_n:>3}")

# Save histogram PNG via matplotlib if available
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.figure(figsize=(8, 4.5))
    bins_edges = [i * 0.1 for i in range(21)]  # 0 to 2.0 step 0.1
    plt.hist(rel, bins=bins_edges, alpha=0.7, label=f"relevant (q↔GT), n={len(rel)}",
             color="#2c7a3a")
    plt.hist(dis, bins=bins_edges, alpha=0.5, label=f"distractor (q↔non-GT top-10), n={len(dis)}",
             color="#a63a3a")
    plt.axvline(0.8, color="black", linestyle=":", alpha=0.7, linewidth=1)
    plt.text(0.8, plt.gca().get_ylim()[1] * 0.95, " 0.8", verticalalignment="top")
    plt.axvline(1.2, color="black", linestyle=":", alpha=0.7, linewidth=1)
    plt.text(1.2, plt.gca().get_ylim()[1] * 0.95, " 1.2", verticalalignment="top")
    plt.axvline(1.5, color="black", linestyle=":", alpha=0.7, linewidth=1)
    plt.text(1.5, plt.gca().get_ylim()[1] * 0.95, " 1.5", verticalalignment="top")
    plt.axvline(best[0], color="blue", linestyle="--", linewidth=1.5,
                label=f"F1-optimal = {best[0]:.2f}")
    plt.xlabel("L2 distance (lower = more similar)")
    plt.ylabel("count")
    plt.title("L2 distribution: relevant vs distractor pairs")
    plt.legend()
    plt.tight_layout()
    plt.savefig(ROOT / "eval_results" / "L2_distribution.png", dpi=120)
    print("\nSaved histogram → eval_results/L2_distribution.png")
except Exception as e:
    print(f"matplotlib skipped: {e}")
