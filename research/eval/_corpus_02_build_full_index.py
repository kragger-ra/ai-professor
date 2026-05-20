"""Build a FAISS index from the full corpus into data/rag_vector_store_full/
without touching the existing data/rag_vector_store/.
"""
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

# Load .env
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, str(ROOT / "src"))

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import FAISS

from agent.llm_clients.lc_clients import get_embeddings_model
from agent.rag import CustomTripleNewLineSplitter

SRC = ROOT / "resources" / "RAG" / "course_materials_full"
OUT = ROOT / "data" / "rag_vector_store_full"
INDEX_NAME = "knowledge"

if OUT.exists():
    print(f"[BUILD] removing existing {OUT}")
    shutil.rmtree(OUT)
OUT.mkdir(parents=True, exist_ok=True)

# Load all .md files using the SAME loader + splitter as the live system
print(f"[BUILD] loading from {SRC}")
splitter = CustomTripleNewLineSplitter(chunk_size=1000, chunk_overlap=0)
docs = []
for f in sorted(SRC.glob("*.md")):
    loader = TextLoader(str(f), encoding="utf-8")
    raw = loader.load()
    chunks = splitter.split_text(raw[0].page_content)
    print(f"  {f.name}: {len(chunks)} chunks (raw_len={len(raw[0].page_content)})")
    for ch in chunks:
        from langchain_core.documents.base import Document
        docs.append(Document(
            page_content=ch,
            metadata={"kind": INDEX_NAME, "subject": "PersonaLab", "source": str(f)},
        ))
print(f"[BUILD] total chunks = {len(docs)}")

# Build FAISS index
print("[BUILD] initializing embeddings (bge-m3 via LM Studio)...")
emb = get_embeddings_model()
t = time.time()
vec_store = FAISS.from_documents(docs, embedding=emb)
print(f"[BUILD] FAISS.from_documents done in {time.time() - t:.2f}s")
vec_store.save_local(str(OUT), index_name=INDEX_NAME)
print(f"[BUILD] saved → {OUT}/{INDEX_NAME}.faiss + .pkl")

# Stats
import faiss
idx = faiss.read_index(str(OUT / f"{INDEX_NAME}.faiss"))
print(f"[BUILD] FAISS ntotal = {idx.ntotal}, dim = {idx.d}")

# Per-source distribution
from collections import Counter
src_dist = Counter(Path(d.metadata["source"]).name for d in docs)
print("\nChunks per source:")
for name, n in src_dist.most_common():
    print(f"  {n:>3}  {name}")

# Size stats
sizes = sorted(len(d.page_content) for d in docs)
print(f"\nChunk sizes: min={sizes[0]} median={sizes[len(sizes)//2]} "
      f"mean={sum(sizes)//len(sizes)} max={sizes[-1]}")

# Save dump for GT generation later (analogous to _chunks.json)
chunks_dump = []
for i, d in enumerate(docs):
    chunks_dump.append({
        "chunk_id": i,
        "source": d.metadata["source"],
        "kind": d.metadata["kind"],
        "subject": d.metadata["subject"],
        "content": d.page_content,
        "content_len": len(d.page_content),
    })
(ROOT / "eval_results" / "_chunks_full.json").write_text(
    json.dumps(chunks_dump, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\n[BUILD] dumped chunks → eval_results/_chunks_full.json")
