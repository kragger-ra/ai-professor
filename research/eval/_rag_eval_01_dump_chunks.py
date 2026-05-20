"""Dump all FAISS chunks to a JSON file for GT annotation."""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
PKL = ROOT / "data" / "rag_vector_store" / "knowledge.pkl"

with open(PKL, "rb") as f:
    data = pickle.load(f)

docstore, index_to_id = data
print(f"docstore type: {type(docstore).__name__}, entries: {len(docstore._dict)}")
print(f"index_to_id type: {type(index_to_id).__name__}, entries: {len(index_to_id)}")

chunks = []
# Iterate in FAISS index order so chunk_id == FAISS position
for i in sorted(index_to_id.keys()):
    doc_id = index_to_id[i]
    doc = docstore._dict[doc_id]
    chunks.append({
        "chunk_id": i,                       # FAISS index position (used for GT matching)
        "doc_id": doc_id,                    # internal langchain UUID
        "source": (doc.metadata or {}).get("source", ""),
        "kind": (doc.metadata or {}).get("kind", ""),
        "subject": (doc.metadata or {}).get("subject", ""),
        "content": doc.page_content,
        "content_len": len(doc.page_content),
    })

(ROOT / "eval_results" / "_chunks.json").write_text(
    json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8"
)

# Source distribution
from collections import Counter
src_dist = Counter(c["source"].split("\\")[-1] for c in chunks)
print("\nChunks per source file:")
for src, n in src_dist.most_common():
    print(f"  {n:3d}  {src}")

# Size stats
sizes = sorted(c["content_len"] for c in chunks)
print(f"\nSize stats: min={sizes[0]}, median={sizes[len(sizes)//2]}, "
      f"mean={sum(sizes)/len(sizes):.0f}, max={sizes[-1]}")

print(f"\nDumped to eval_results/_chunks.json ({len(chunks)} chunks)")
