"""Build the FAISS index for the White Coding course corpus.

Loads courses/whitecoding/*.md with the same splitter the app uses
(CustomTripleNewLineSplitter), embeds with bge-m3 via LM Studio, and writes
data/rag_vector_store/knowledge.{faiss,pkl}. Chunks are tagged kind='knowledge'
(so the retriever's filter matches) and subject='Вайб-кодинг'.
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]   # AI-Professor-Tutor/
os.chdir(REPO)
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"

# Load .env so EMBEDDINGS_* are visible.
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

sys.path.insert(0, str(REPO / "src"))

from langchain_community.document_loaders import DirectoryLoader, TextLoader  # noqa
from langchain_community.vectorstores import FAISS  # noqa
from agent.rag import CustomTripleNewLineSplitter  # noqa
from agent.llm_clients.lc_clients import get_embeddings_model  # noqa

SRC_DIR = REPO / "courses" / "whitecoding"
STORE_DIR = REPO / "data" / "rag_vector_store"
INDEX_NAME = "knowledge"
SUBJECT = "Вайб-кодинг"

print(f"[build] source : {SRC_DIR}")
print(f"[build] store  : {STORE_DIR}")

splitter = CustomTripleNewLineSplitter(chunk_size=1000, chunk_overlap=0)

docs = []
for glob in ("*.md", "*.txt"):
    loader = DirectoryLoader(
        str(SRC_DIR), glob=glob, loader_cls=TextLoader,
        loader_kwargs={"encoding": "utf-8"},
    )
    for doc in loader.load_and_split(text_splitter=splitter):
        doc.metadata = {"kind": INDEX_NAME, "subject": SUBJECT, **doc.metadata}
        docs.append(doc)

print(f"[build] loaded {len(docs)} chunks")
sizes = sorted(len(d.page_content) for d in docs)
print(f"[build] chunk size: min={sizes[0]} median={sizes[len(sizes)//2]} "
      f"mean={sum(sizes)//len(sizes)} max={sizes[-1]}")
from collections import Counter
per_src = Counter(Path(d.metadata.get("source", "?")).name for d in docs)
for src, n in per_src.most_common():
    print(f"         {n:3d}  {src}")

t0 = time.time()
emb = get_embeddings_model()
vec = FAISS.from_documents(documents=docs, embedding=emb)
print(f"[build] vectorized in {time.time() - t0:.1f}s")

if STORE_DIR.exists():
    shutil.rmtree(STORE_DIR)
STORE_DIR.mkdir(parents=True, exist_ok=True)
vec.save_local(str(STORE_DIR), index_name=INDEX_NAME)
print(f"[build] saved -> {STORE_DIR / (INDEX_NAME + '.faiss')}")
print(f"[build] DONE: {len(docs)} chunks indexed")
