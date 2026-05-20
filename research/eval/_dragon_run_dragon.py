"""Baseline: facebook/dragon-plus on the same RuBQRetrieval subset.

Dragon-plus is a BERT bi-encoder trained on English MS-MARCO. Run on the same
Russian subset as bge-m3 for a like-for-like comparison. Dragon scores
documents by inner product of separate query/context CLS embeddings.

Output: eval_results/_dragon_metrics_dragon.json
"""
from __future__ import annotations

import json
import math
import statistics
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import torch
from transformers import AutoModel, AutoTokenizer

ROOT = Path(__file__).resolve().parent
K = 10
BATCH = 32
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"[dragon] device={DEVICE}")

subset = json.loads((ROOT / "eval_results" / "_dragon_subset.json").read_text(encoding="utf-8"))
corpus = subset["corpus"]
queries = subset["queries"]
qrels = {qid: set(ids) for qid, ids in subset["qrels"].items()}
print(f"[subset] {len(queries)} queries, {len(corpus)} passages")

print("[dragon] loading facebook/dragon-plus encoders ...")
tok = AutoTokenizer.from_pretrained("facebook/dragon-plus-query-encoder")
q_enc = AutoModel.from_pretrained("facebook/dragon-plus-query-encoder").to(DEVICE).eval()
c_enc = AutoModel.from_pretrained("facebook/dragon-plus-context-encoder").to(DEVICE).eval()


@torch.no_grad()
def encode(texts, encoder, pair=False):
    """CLS embeddings, batched. pair=True joins title+text the Dragon way."""
    out = []
    for i in range(0, len(texts), BATCH):
        batch = texts[i:i + BATCH]
        if pair:
            inp = tok([t[0] for t in batch], [t[1] for t in batch],
                      padding=True, truncation=True, max_length=512,
                      return_tensors="pt").to(DEVICE)
        else:
            inp = tok(batch, padding=True, truncation=True, max_length=512,
                      return_tensors="pt").to(DEVICE)
        emb = encoder(**inp).last_hidden_state[:, 0, :]
        out.append(emb.cpu())
    return torch.cat(out, dim=0)


t0 = time.time()
# Dragon context input: (title, text) pair — title empty for RuBQ, so passes text
ctx_pairs = [(c["title"], c["text"]) for c in corpus]
ctx_emb = encode(ctx_pairs, c_enc, pair=True)
print(f"[dragon] encoded {len(corpus)} passages in {time.time() - t0:.1f}s")

t1 = time.time()
q_emb = encode([q["text"] for q in queries], q_enc, pair=False)
print(f"[dragon] encoded {len(queries)} queries in {time.time() - t1:.1f}s")

cids = [c["id"] for c in corpus]


def dcg(rels):
    return sum(r / math.log2(i + 2) for i, r in enumerate(rels))


results = []
for qi, q in enumerate(queries):
    qid = q["qid"]
    rel_set = qrels[qid]
    scores = q_emb[qi] @ ctx_emb.T          # inner product (Dragon native)
    top = torch.topk(scores, k=K).indices.tolist()
    ranked = [cids[j] for j in top]
    rel_flags = [1 if c in rel_set else 0 for c in ranked]

    first_rel = next((i + 1 for i, f in enumerate(rel_flags) if f), None)
    n_rel = len(rel_set)
    results.append({
        "qid": qid, "question": q["text"], "n_relevant": n_rel,
        "first_rel_rank": first_rel,
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
print(f"facebook/dragon-plus on RuBQRetrieval subset (N={N})")
print("=" * 60)
for k, v in summary.items():
    if k != "N":
        print(f"  {k:18s} = {v:.3f}")

(ROOT / "eval_results" / "_dragon_metrics_dragon.json").write_text(
    json.dumps({
        "dataset": subset["dataset"], "split": subset["split"],
        "n_corpus": subset["n_corpus"], "seed": subset["seed"],
        "model": "facebook/dragon-plus (query+context encoders)",
        "scoring": "inner product",
        "note": "Dragon-plus is English MS-MARCO trained; RuBQ is Russian.",
        "summary": summary, "per_query": results,
    }, ensure_ascii=False, indent=2),
    encoding="utf-8",
)
print("\nSaved -> eval_results/_dragon_metrics_dragon.json")
