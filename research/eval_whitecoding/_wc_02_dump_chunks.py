"""Dump all FAISS chunks (in index order) to JSON for GT annotation."""
from __future__ import annotations

import json
import pickle
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
PKL = REPO / "data" / "rag_vector_store" / "knowledge.pkl"
OUT = Path(__file__).resolve().parent / "_chunks.json"

with open(PKL, "rb") as f:
    docstore, index_to_id = pickle.load(f)

chunks = []
for i in sorted(index_to_id.keys()):
    doc = docstore._dict[index_to_id[i]]
    chunks.append({
        "chunk_id": i,
        "source": Path((doc.metadata or {}).get("source", "")).name,
        "subject": (doc.metadata or {}).get("subject", ""),
        "first_line": doc.page_content.split("\n", 1)[0][:80],
        "content": doc.page_content,
        "content_len": len(doc.page_content),
    })

OUT.write_text(json.dumps(chunks, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"dumped {len(chunks)} chunks -> {OUT}")
for c in chunks:
    print(f"  [{c['chunk_id']:2d}] {c['source']:28s} {c['content_len']:4d}  {c['first_line']}")
