"""bge-m3 on the FULL RuBQRetrieval task (56826 passages, 1692 queries).

This reproduces the actual MTEB RuBQRetrieval task setup, so the resulting
nDCG@10 is directly comparable to the public MTEB leaderboard figure for
bge-m3. Uses the production embedder (text-embedding-user-bge-m3 via LM Studio).

Output: eval_results/_dragon_metrics_bgem3_full.json
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

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, str(ROOT / "src"))

from agent.llm_clients.lc_clients import get_embeddings_model  # noqa
from datasets import load_dataset  # noqa
from langchain_community.vectorstores import FAISS  # noqa

K = 10

print("[load] full RuBQRetrieval ...")
corpus = load_dataset("mteb/RuBQRetrieval", "corpus")["test"]
queries = load_dataset("mteb/RuBQRetrieval", "queries")["test"]
qrels_ds = load_dataset("mteb/RuBQRetrieval", "qrels")["test"]

qrels = {}
for row in qrels_ds:
    if int(row["score"]) > 0:
        qrels.setdefault(str(row["query-id"]), set()).add(str(row["corpus-id"]))

query_text = {str(q["_id"]): q["text"] for q in queries}
eval_queries = [(qid, query_text[qid]) for qid in sorted(qrels) if qid in query_text]
print(f"[load] corpus={len(corpus)}  queries={len(eval_queries)}  "
      f"judgements={sum(len(v) for v in qrels.values())}")

emb = get_embeddings_model()
emb.chunk_size = 64
print(f"[embed] model={emb.model} — embedding {len(corpus)} passages "
      f"(~12 min expected) ...")

texts = [c["text"] for c in corpus]
metadatas = [{"cid": str(c["_id"])} for c in corpus]

t0 = time.time()
vec_store = FAISS.from_texts(texts, embedding=emb, metadatas=metadatas)
print(f"[embed] full index built in {time.time() - t0:.1f}s")


def dcg(rels):
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


results = []
t1 = time.time()
for n, (qid, question) in enumerate(eval_queries):
    rel_set = qrels[qid]
    docs_scores = vec_store.similarity_search_with_score(question, k=K)
    ranked = [d.metadata["cid"] for d, _ in docs_scores]
    rel_flags = [1 if c in rel_set else 0 for c in ranked]
    first_rel = next((i + 1 for i, f in enumerate(rel_flags) if f), None)
    n_rel = len(rel_set)
    results.append({
        "qid": qid,
        "hit1": rel_flags[0] == 1,
        "hit3": any(rel_flags[:3]),
        "hit5": any(rel_flags[:5]),
        "p1": sum(rel_flags[:1]) / 1,
        "p3": sum(rel_flags[:3]) / 3,
        "p5": sum(rel_flags[:5]) / 5,
        "recall5": sum(rel_flags[:5]) / n_rel,
        "recall10": sum(rel_flags[:10]) / n_rel,
        "rr10": (1.0 / first_rel) if first_rel else 0.0,
        "ndcg10": dcg(rel_flags[:10]) / dcg([1] * min(n_rel, 10)) if n_rel else 0.0,
    })
    if (n + 1) % 200 == 0:
        print(f"  ...{n + 1}/{len(eval_queries)} queries searched")
print(f"[search] {len(eval_queries)} queries in {time.time() - t1:.1f}s")

N = len(results)
def avg(k):
    return sum(r[k] for r in results) / N

summary = {
    "N": N,
    "hit_at_1": avg("hit1"), "hit_at_3": avg("hit3"), "hit_at_5": avg("hit5"),
    "precision_at_1": avg("p1"), "precision_at_3": avg("p3"), "precision_at_5": avg("p5"),
    "recall_at_5": avg("recall5"), "recall_at_10": avg("recall10"),
    "MRR_at_10": avg("rr10"), "nDCG_at_10": avg("ndcg10"),
}

print()
print("=" * 60)
print(f"bge-m3 on FULL RuBQRetrieval (N={N}, corpus={len(corpus)})")
print("=" * 60)
for k, v in summary.items():
    if k != "N":
        print(f"  {k:18s} = {v:.3f}")

(ROOT / "eval_results" / "_dragon_metrics_bgem3_full.json").write_text(
    json.dumps({
        "dataset": "mteb/RuBQRetrieval", "split": "test",
        "n_corpus": len(corpus), "n_queries": N,
        "embedder": emb.model, "index": "FAISS IndexFlatL2",
        "note": "Full MTEB RuBQRetrieval task — nDCG@10 comparable to MTEB leaderboard.",
        "summary": summary,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("\nSaved -> eval_results/_dragon_metrics_bgem3_full.json")
