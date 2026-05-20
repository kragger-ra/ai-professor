"""Build FAISS index v2 from preprocessed chunks → data/rag_vector_store_full_v2/."""
from __future__ import annotations

import json
import os
import shutil
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

from langchain_community.vectorstores import FAISS
from langchain_core.documents.base import Document
from agent.llm_clients.lc_clients import get_embeddings_model

OUT = ROOT / "data" / "rag_vector_store_full_v2"
INDEX_NAME = "knowledge"

if OUT.exists():
    print(f"[BUILD] removing existing {OUT}")
    shutil.rmtree(OUT)
OUT.mkdir(parents=True, exist_ok=True)

chunks = json.loads((ROOT / "eval_results" / "_chunks_full_v2.json").read_text(encoding="utf-8"))
print(f"[BUILD] loaded {len(chunks)} preprocessed chunks")

docs = [
    Document(
        page_content=c["content"],
        metadata={
            "kind": c["kind"],
            "subject": c["subject"],
            "source": c["source"],
            "section": c.get("section", ""),
        },
    )
    for c in chunks
]

print("[BUILD] initializing embeddings...")
emb = get_embeddings_model()
t = time.time()
vec_store = FAISS.from_documents(docs, embedding=emb)
print(f"[BUILD] FAISS.from_documents in {time.time() - t:.2f}s")
vec_store.save_local(str(OUT), index_name=INDEX_NAME)
print(f"[BUILD] saved → {OUT}/{INDEX_NAME}.faiss + .pkl")

import faiss
idx = faiss.read_index(str(OUT / f"{INDEX_NAME}.faiss"))
print(f"[BUILD] FAISS ntotal = {idx.ntotal}, dim = {idx.d}")
