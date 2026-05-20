"""For misses, dump GT vs actual top-1 side-by-side to see if 'wrong' is really wrong."""
from __future__ import annotations

import json
import os
import sys
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

from agent.rag import RagModel
rag = RagModel()

metrics = json.loads((ROOT / "eval_results" / "_retrieval_metrics.json").read_text(encoding="utf-8"))
chunks = json.loads((ROOT / "eval_results" / "_chunks.json").read_text(encoding="utf-8"))
chunk_by_content = {c["content"]: c for c in chunks}

results = metrics["per_query"]

# Re-run retrieval for non-top1 cases and compare
for r in results:
    if r["top1"]:
        continue  # Only look at cases where top-1 was wrong
    q = r["question"]
    gt_id = r["gt_chunk_id"]
    gt_content = next(c["content"] for c in chunks if c["chunk_id"] == gt_id)

    docs_scores = rag.vec_store.similarity_search_with_score(q, k=5)
    print()
    print("=" * 80)
    print(f"Q#{r['qid']} [rank={r['rank']}, src={r['gt_source']}]")
    print(f"Q: {q}")
    print("---  GT chunk (what we wanted):")
    print(f"  L2 vs GT: (rank {r['rank']})")
    print(f"  {gt_content[:300]}")
    print("---  Top-1 (what retriever actually returned):")
    top1_doc, top1_score = docs_scores[0]
    top1_chunk = chunk_by_content.get(top1_doc.page_content, {})
    print(f"  L2={top1_score:.3f}  src={top1_chunk.get('source', '?').split(chr(92))[-1]}")
    print(f"  {top1_doc.page_content[:300]}")
