"""Run bge-m3 retrieval on the RuBQRetrieval subset, using the production stack.

Embedder: text-embedding-user-bge-m3 via LM Studio (same as the live RAG).
Index:    langchain FAISS IndexFlatL2 (same as production rag.py).
Metrics:  hit@1/3/5, precision@k, recall@5/10, MRR@10, nDCG@10.

Output: eval_results/_dragon_metrics_bgem3.json + L2_distribution_dragon.png
"""
from __future__ import annotations

import json
import math
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

# Load .env (for EMBEDDINGS_* — the production embedder config)
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, str(ROOT / "src"))

from agent.llm_clients.lc_clients import get_embeddings_model  # noqa
from langchain_community.vectorstores import FAISS  # noqa

K = 10  # all metrics computed @<=10

subset = json.loads((ROOT / "eval_results" / "_dragon_subset.json").read_text(encoding="utf-8"))
corpus = subset["corpus"]
queries = subset["queries"]
qrels = {qid: set(ids) for qid, ids in subset["qrels"].items()}
print(f"[subset] {len(queries)} queries, {len(corpus)} passages, "
      f"dataset={subset['dataset']}")

# ----------------------------------------------------------------------
# Build a fresh FAISS index over the subset corpus with the production embedder
# ----------------------------------------------------------------------
emb = get_embeddings_model()
emb.chunk_size = 64  # request batching only — does not affect embedding values
print(f"[embed] model={emb.model}  base={emb.openai_api_base}")

texts = [c["text"] for c in corpus]
metadatas = [{"cid": c["id"]} for c in corpus]

t0 = time.time()
print(f"[embed] embedding {len(texts)} passages + building FAISS IndexFlatL2 ...")
vec_store = FAISS.from_texts(texts, embedding=emb, metadatas=metadatas)
print(f"[embed] index built in {time.time() - t0:.1f}s  ({len(texts)} vectors)")

# ----------------------------------------------------------------------
# Retrieval
# ----------------------------------------------------------------------
def dcg(rels):
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))

results = []
relevant_L2 = []    # L2 of query <-> its top-ranked relevant doc
distractor_L2 = []  # L2 of query <-> non-relevant docs in top-10

for q in queries:
    qid, question = q["qid"], q["text"]
    rel_set = qrels[qid]

    t = time.time()
    docs_scores = vec_store.similarity_search_with_score(question, k=K)
    retrieve_ms = (time.time() - t) * 1000

    ranked = [(d.metadata["cid"], float(s)) for d, s in docs_scores]
    rel_flags = [1 if cid in rel_set else 0 for cid, _ in ranked]

    # rank of first relevant (1-indexed), None if not in top-K
    first_rel = next((i + 1 for i, f in enumerate(rel_flags) if f), None)

    hit1 = rel_flags[0] == 1
    hit3 = any(rel_flags[:3])
    hit5 = any(rel_flags[:5])
    p1 = sum(rel_flags[:1]) / 1
    p3 = sum(rel_flags[:3]) / 3
    p5 = sum(rel_flags[:5]) / 5
    n_rel = len(rel_set)
    recall5 = sum(rel_flags[:5]) / n_rel
    recall10 = sum(rel_flags[:10]) / n_rel
    rr = (1.0 / first_rel) if first_rel else 0.0
    ndcg = dcg(rel_flags[:10]) / dcg([1] * min(n_rel, 10)) if n_rel else 0.0

    # L2 bookkeeping for the distribution plot
    for cid, s in ranked:
        if cid in rel_set:
            relevant_L2.append({"qid": qid, "L2": s})
            break
    for cid, s in ranked[:10]:
        if cid not in rel_set:
            distractor_L2.append({"qid": qid, "L2": s})

    results.append({
        "qid": qid, "question": question, "n_relevant": n_rel,
        "first_rel_rank": first_rel, "retrieve_ms": retrieve_ms,
        "hit1": hit1, "hit3": hit3, "hit5": hit5,
        "p1": p1, "p3": p3, "p5": p5,
        "recall5": recall5, "recall10": recall10,
        "rr10": rr, "ndcg10": ndcg,
        "top1_L2": ranked[0][1],
    })
    flag = "✓" if hit1 else ("." if hit5 else "x")
    print(f"[{qid:>5}] {flag} rank={first_rel}  ndcg={ndcg:.2f}  "
          f"{retrieve_ms:.1f}ms | {question[:50]}")

# ----------------------------------------------------------------------
# Aggregate
# ----------------------------------------------------------------------
N = len(results)
def avg(key):
    return sum(r[key] for r in results) / N

summary = {
    "N": N,
    "hit_at_1": avg("hit1"), "hit_at_3": avg("hit3"), "hit_at_5": avg("hit5"),
    "precision_at_1": avg("p1"), "precision_at_3": avg("p3"), "precision_at_5": avg("p5"),
    "recall_at_5": avg("recall5"), "recall_at_10": avg("recall10"),
    "MRR_at_10": avg("rr10"), "nDCG_at_10": avg("ndcg10"),
}

print()
print("=" * 60)
print(f"bge-m3 on RuBQRetrieval subset (N={N})")
print("=" * 60)
for k, v in summary.items():
    if k == "N":
        continue
    print(f"  {k:18s} = {v:.3f}")

ret_times = sorted(r["retrieve_ms"] for r in results)
print(f"\n  retrieve timing: p50={ret_times[N//2]:.1f}ms  "
      f"p95={ret_times[int(N*0.95)]:.1f}ms  mean={statistics.mean(ret_times):.1f}ms")

misses = [r for r in results if not r["hit5"]]
print(f"\n  misses (no relevant in top-5): {len(misses)}/{N}")

(ROOT / "eval_results" / "_dragon_metrics_bgem3.json").write_text(
    json.dumps({
        "dataset": subset["dataset"], "split": subset["split"],
        "n_corpus": subset["n_corpus"], "seed": subset["seed"],
        "embedder": emb.model, "index": "FAISS IndexFlatL2",
        "summary": summary, "per_query": results,
        "relevant_L2": relevant_L2, "distractor_L2": distractor_L2,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("\nSaved -> eval_results/_dragon_metrics_bgem3.json")

# ----------------------------------------------------------------------
# L2 distribution plot
# ----------------------------------------------------------------------
rel = sorted(x["L2"] for x in relevant_L2)
dis = sorted(x["L2"] for x in distractor_L2)
if rel and dis:
    print(f"\nRelevant L2:   n={len(rel)}  mean={statistics.mean(rel):.3f}  "
          f"p50={rel[len(rel)//2]:.3f}")
    print(f"Distractor L2: n={len(dis)}  mean={statistics.mean(dis):.3f}  "
          f"p50={dis[len(dis)//2]:.3f}")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        plt.figure(figsize=(8, 4.5))
        lo = min(rel[0], dis[0])
        hi = max(rel[-1], dis[-1])
        edges = [lo + (hi - lo) * i / 30 for i in range(31)]
        plt.hist(rel, bins=edges, alpha=0.7, color="#2c7a3a",
                 label=f"relevant (q↔rel doc), n={len(rel)}")
        plt.hist(dis, bins=edges, alpha=0.5, color="#a63a3a",
                 label=f"distractor (q↔non-rel top-10), n={len(dis)}")
        plt.xlabel("L2 distance (lower = more similar)")
        plt.ylabel("count")
        plt.title("bge-m3 on RuBQRetrieval subset — L2 distribution")
        plt.legend()
        plt.tight_layout()
        plt.savefig(ROOT / "eval_results" / "L2_distribution_dragon.png", dpi=120)
        print("Saved -> eval_results/L2_distribution_dragon.png")
    except Exception as e:
        print(f"matplotlib skipped: {e}")
