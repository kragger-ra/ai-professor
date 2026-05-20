"""Build a representative subset of RuBQRetrieval for the external retrieval eval.

150 queries (seeded) + their relevant passages + random distractors -> ~4000 corpus.
Saves eval_results/_dragon_subset.json.
"""
import json
import random
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from datasets import load_dataset

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "eval_results" / "_dragon_subset.json"

N_QUERIES = 150
TARGET_CORPUS = 4000
SEED = 42

print("[load] RuBQRetrieval corpus/queries/qrels ...")
corpus = load_dataset("mteb/RuBQRetrieval", "corpus")["test"]
queries = load_dataset("mteb/RuBQRetrieval", "queries")["test"]
qrels = load_dataset("mteb/RuBQRetrieval", "qrels")["test"]

# qrels: query-id -> set(corpus-id) with score > 0
q_to_rel = {}
for row in qrels:
    if int(row["score"]) > 0:
        q_to_rel.setdefault(str(row["query-id"]), set()).add(str(row["corpus-id"]))
print(f"[qrels] {len(q_to_rel)} queries have >=1 relevant doc, "
      f"{sum(len(v) for v in q_to_rel.values())} relevance judgements")

query_text = {str(q["_id"]): q["text"] for q in queries}

# Eligible queries: in qrels AND text present
eligible = sorted(qid for qid in q_to_rel if qid in query_text)
print(f"[queries] {len(eligible)} eligible")

rng = random.Random(SEED)
picked = sorted(rng.sample(eligible, min(N_QUERIES, len(eligible))))
print(f"[queries] picked {len(picked)}")

# Relevant corpus ids for picked queries
relevant_ids = set()
for qid in picked:
    relevant_ids |= q_to_rel[qid]
print(f"[corpus] {len(relevant_ids)} relevant passages across picked queries")

# Full corpus map
corpus_map = {str(c["_id"]): {"id": str(c["_id"]),
                              "title": c.get("title", "") or "",
                              "text": c["text"]} for c in corpus}

# Sanity: every relevant id must exist in corpus
missing = [cid for cid in relevant_ids if cid not in corpus_map]
if missing:
    print(f"[WARN] {len(missing)} relevant ids missing from corpus, dropping them")
    relevant_ids -= set(missing)

# Distractors: random non-relevant passages until TARGET_CORPUS
non_relevant = sorted(set(corpus_map) - relevant_ids)
n_distract = max(0, TARGET_CORPUS - len(relevant_ids))
distractors = rng.sample(non_relevant, min(n_distract, len(non_relevant)))

subset_ids = sorted(relevant_ids | set(distractors), key=lambda x: int(x))
subset_corpus = [corpus_map[cid] for cid in subset_ids]
print(f"[corpus] subset size = {len(subset_corpus)} "
      f"({len(relevant_ids)} relevant + {len(distractors)} distractors)")

# Drop queries whose relevant docs all fell out (none should, but be safe)
final_queries = []
final_qrels = {}
for qid in picked:
    rel = sorted(q_to_rel[qid] & set(subset_ids))
    if not rel:
        continue
    final_queries.append({"qid": qid, "text": query_text[qid]})
    final_qrels[qid] = rel

out = {
    "dataset": "mteb/RuBQRetrieval",
    "split": "test",
    "seed": SEED,
    "n_queries": len(final_queries),
    "n_corpus": len(subset_corpus),
    "n_relevance_judgements": sum(len(v) for v in final_qrels.values()),
    "queries": final_queries,
    "qrels": final_qrels,
    "corpus": subset_corpus,
}
OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"[save] {OUT}  ({OUT.stat().st_size/1e6:.2f} MB)")
print(f"  queries={len(final_queries)}  corpus={len(subset_corpus)}  "
      f"judgements={out['n_relevance_judgements']}  "
      f"avg rel/query={out['n_relevance_judgements']/len(final_queries):.2f}")
