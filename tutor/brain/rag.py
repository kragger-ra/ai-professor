"""RAG (Retrieval-Augmented Generation) module for the tutor package.

Ported from src/agent/rag.py.  Key differences from the original:
  - Imports from tutor.brain.embeddings instead of agent.llm_clients.lc_clients
  - Path constants are package-local (repo_root derived from __file__)
  - timing_context replaced with contextlib.nullcontext
  - STARTUP MISMATCH FIX: after FAISS.load_local succeeds, self.docs and
    self.wordkeys are re-derived from the loaded index's own docstore so that
    docs, wordkeys, and vec_store always describe the same corpus (the on-disk
    index might have been built for a different course than the current
    filesystem course_materials/).
  - Legacy RAG_DOCS_DIR / dataloader path removed.
  - __main__ block removed.
  - No ctx_swarm / multiprocessing usage.
"""

from __future__ import annotations

import contextlib
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Dict, List, Tuple

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents.base import Document
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_text_splitters import TextSplitter

from tutor.brain.embeddings import get_embeddings_model
from tutor.util import log

# ---------------------------------------------------------------------------
# Package-local path constants
# ---------------------------------------------------------------------------

# tutor/brain/rag.py  ->  parents[0]=brain, [1]=tutor, [2]=repo_root
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]

RAG_STORE_DIR: str = str(_REPO_ROOT / "data" / "rag_vector_store")
_COURSE_MATERIALS_DIR: str = str(_REPO_ROOT / "resources" / "RAG" / "course_materials")

_COMPONENT = "rag"


# ---------------------------------------------------------------------------
# Text splitter
# ---------------------------------------------------------------------------


class CustomTripleNewLineSplitter(TextSplitter):
    """Split on triple-newlines; fall back to double-newlines for oversized chunks.

    Strips a trailing 'Источники:' section and merges tiny fragments into
    their neighbours so the FAISS index does not get polluted with near-empty
    embeddings.
    """

    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 0,
                 separator: str = "\n\n\n"):
        self.separator = separator
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split_text(self, text: str) -> list[str]:
        chunks = text.split(self.separator)
        # Drop a trailing 'Источники:' section if present
        if chunks and chunks[-1].split("\n")[0].strip() == "Источники:":
            chunks = chunks[:-1]

        # Fallback: split oversized chunks on \n\n; keep non-empty pieces
        _MIN_CHUNK = 50  # chars — merge headers / tiny fragments into neighbours
        raw: list[str] = []
        for chunk in chunks:
            chunk = chunk.strip()
            if not chunk:
                continue
            if len(chunk) > self._chunk_size:
                sub_chunks = chunk.split("\n\n")
                raw.extend(s.strip() for s in sub_chunks if s.strip())
            else:
                raw.append(chunk)

        # Merge small chunks into their neighbour to avoid tiny fragments
        result: list[str] = []
        buf = ""
        for part in raw:
            if len(part) < _MIN_CHUNK:
                buf = (buf + "\n\n" + part).strip() if buf else part
            else:
                if buf:
                    part = buf + "\n\n" + part
                    buf = ""
                result.append(part)
        if buf:
            if result:
                result[-1] = result[-1] + "\n\n" + buf
            else:
                result.append(buf)
        return result


# ---------------------------------------------------------------------------
# Directory loader
# ---------------------------------------------------------------------------


class CustomDirectoryLoader:
    """Load .txt / .md files from a set of named sub-directories."""

    def __init__(self, directory: str, doc_kinds: List[str]):
        self.dir = directory
        self.doc_kinds = doc_kinds

    def get_docs_wordkeys(self, docs: List[Document]) -> List[str]:
        wordkeys = []
        for doc in docs:
            text = doc.page_content
            if text:
                lines = text.split("\n")
                if len(lines) > 1:
                    wordkeys.append(lines[0])
        return wordkeys

    def load(self, text_splitter: TextSplitter = None) -> List[Document]:
        docs: List[Document] = []
        for kind in self.doc_kinds:
            path = os.path.join(self.dir, kind)
            if not os.path.isdir(path):
                log(_COMPONENT, f"Skipping missing directory: {path}")
                continue
            for file_glob in ("*.txt", "*.md"):
                loader = DirectoryLoader(
                    path,
                    glob=file_glob,
                    loader_cls=TextLoader,
                    loader_kwargs={"encoding": "utf-8"},
                )
                if text_splitter is None:
                    tmp = loader.load()
                else:
                    tmp = loader.load_and_split(text_splitter=text_splitter)
                for doc in tmp:
                    doc.metadata = {"kind": kind, **doc.metadata}
                docs.extend(tmp)
        return docs


# ---------------------------------------------------------------------------
# RagModel
# ---------------------------------------------------------------------------


class RagModel:
    """FAISS-backed retrieval model.

    Lifecycle
    ---------
    1. __init__ tries to load a persisted FAISS index from disk.
       - If found: docs/wordkeys are derived from the index's own docstore
         (startup-mismatch fix).
       - If not found: docs are loaded from the filesystem and the index is
         built fresh.
    2. reload_from_path(name, src_dir) hot-swaps the corpus at runtime.
    """

    def __init__(self) -> None:
        start_time = time.time()
        self.index_name = "knowledge"
        self._active_subject: str | None = None
        self.vec_store_full_path = os.path.join(
            RAG_STORE_DIR, self.index_name + ".faiss"
        )
        self.course_loader = CustomDirectoryLoader(
            _COURSE_MATERIALS_DIR, ["course_materials"]
        )
        self.text_splitter = CustomTripleNewLineSplitter(
            chunk_size=1000, chunk_overlap=0
        )

        # Initialise docs from filesystem — may be overwritten by
        # load_vec_store if a persisted index already exists on disk.
        load_time_start = time.time()
        self.docs: List[Document] = []
        try:
            course_docs = self.course_loader.load(self.text_splitter)
            self.docs.extend(course_docs)
            log(_COMPONENT, f"Loaded {len(course_docs)} course material chunks from filesystem")
        except Exception as e:
            log(_COMPONENT, f"No course materials loaded from filesystem: {e}")
        self.wordkeys: List[str] = self.get_docs_wordkeys(self.docs)
        log(_COMPONENT,
            f"Document loading took {time.time() - load_time_start:.2f}s")

        try:
            self.embeddings = get_embeddings_model()
        except Exception as e:
            log(_COMPONENT,
                f"Error initialising embeddings: {e}. RAG WILL NOT WORK!")
            traceback.print_exc()
            self.embeddings = None

        # load_vec_store will overwrite self.docs / self.wordkeys when it
        # successfully loads from disk (the startup-mismatch fix).
        self.vec_store: FAISS | None = None
        self.load_vec_store()

        self.last_score = float("inf")  # L2 distance of last query (lower = better)
        self.last_sources: list = []
        self.retrivers: Dict[str, VectorStoreRetriever] = {}
        if self.vec_store is not None:
            self.retrivers[self.index_name] = self.vec_store.as_retriever(
                search_kwargs={"filter": {"kind": self.index_name}, "k": 3}
            )
            self.rag_warmup()
        else:
            log(_COMPONENT, "WARNING: vec_store is None, RAG will not work!")

        log(_COMPONENT,
            f"Total initialisation took {time.time() - start_time:.2f}s")

    # ------------------------------------------------------------------
    # Warmup
    # ------------------------------------------------------------------

    def rag_warmup(self) -> None:
        log(_COMPONENT,
            "IMPORTANT: IF CODE HANGS HERE, TRY DELETING: " + RAG_STORE_DIR)
        warmup_query = "What is this course about?"
        log(_COMPONENT, f"Warming up with query: {warmup_query!r}")
        log(_COMPONENT, "Warmup result: " + self.explain(warmup_query))
        log(_COMPONENT, "Warmup done — RAG ready!")

    # ------------------------------------------------------------------
    # Index loading / building
    # ------------------------------------------------------------------

    def load_vec_store(self, force: bool = False) -> None:
        """Load FAISS index from disk or build it from filesystem docs.

        STARTUP-MISMATCH FIX
        --------------------
        When a persisted index is found and loaded successfully, we re-derive
        self.docs and self.wordkeys from the index's own docstore instead of
        trusting the filesystem copy.  This guarantees that docs, wordkeys,
        and vec_store always describe the same corpus — the on-disk index may
        have been built for a different course than the current
        resources/RAG/course_materials/ directory.

        The freshly-built path (no on-disk index -> create_vec_store) already
        matches because docs are read from the filesystem and then embedded
        without any intermediate persistence — no fix needed there.
        """
        db_exists = False
        if not force:
            db_exists = os.path.exists(self.vec_store_full_path)
            if db_exists:
                try:
                    self.vec_store = FAISS.load_local(
                        folder_path=RAG_STORE_DIR,
                        embeddings=self.embeddings,
                        index_name=self.index_name,
                        allow_dangerous_deserialization=True,
                    )
                    # --- STARTUP-MISMATCH FIX ---
                    # Overwrite docs / wordkeys with what is actually in the
                    # index so that all three state variables are consistent.
                    self.docs = list(self.vec_store.docstore._dict.values())
                    self.wordkeys = self.get_docs_wordkeys(self.docs)
                    log(_COMPONENT,
                        f"Loaded index from disk: {len(self.docs)} chunks "
                        f"({len(self.wordkeys)} wordkeys)")
                except Exception as e:
                    log(_COMPONENT, f"Error loading vec store: {e}")
                    traceback.print_exc()
                    db_exists = False
                    self.vec_store = None

        if not db_exists:
            log(_COMPONENT, "DB not on disk — building from docs")
            self.create_vec_store()

    def create_vec_store(self) -> FAISS | None:
        """Build a new FAISS index from self.docs and persist it to disk.

        An empty docs list is a valid state (student has not loaded a course
        yet).  FAISS.from_documents raises on an empty list, so we skip it
        and set vec_store to None.
        """
        if not self.docs:
            log(_COMPONENT,
                "No documents to vectorise — RAG starts empty; "
                "say 'load course <name>' to populate it.")
            self.vec_store = None
            return self.vec_store

        t0 = time.time()
        try:
            self.vec_store = FAISS.from_documents(
                documents=self.docs, embedding=self.embeddings
            )
            log(_COMPONENT,
                f"Vectorisation took {time.time() - t0:.2f}s")
        except Exception as e:
            self.vec_store = None
            log(_COMPONENT, f"Error building vector store: {e}")
            traceback.print_exc()
            return self.vec_store

        try:
            os.makedirs(RAG_STORE_DIR, exist_ok=True)
            self.vec_store.save_local(RAG_STORE_DIR, index_name=self.index_name)
            log(_COMPONENT,
                f"Saved vector store to disk: {self.vec_store_full_path}")
        except Exception as e:
            log(_COMPONENT,
                f"Error saving vector store ({e}); "
                "RAG continues in-memory, will rebuild next launch")
        return self.vec_store

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

    def get_docs_wordkeys(self, docs: List[Document]) -> List[str]:
        """Return first line of each doc as a keyword key."""
        wordkeys = []
        for doc in docs:
            text = doc.page_content
            if text:
                lines = text.split("\n")
                if len(lines) > 1:
                    wordkeys.append(lines[0])
        return wordkeys

    def retrieve_full(self, query: str) -> List[Tuple[Document, float]]:
        """Return (document, L2-score) pairs for *query*."""
        if self.vec_store is None:
            return []
        with contextlib.nullcontext():
            return self.vec_store.similarity_search_with_score(query)

    def retrieve(self, query: str) -> List[Document]:
        """Return top-k documents for *query* via the named retriever."""
        if self.index_name not in self.retrivers:
            return []
        with contextlib.nullcontext():
            return self.retrivers[self.index_name].invoke(query)

    def explain(self, query: str) -> str:
        """Return combined page_content of the top-2 most relevant chunks.

        Side-effects:
          self.last_score  — L2 distance of top-1 result (lower = better)
          self.last_sources — list of {"score","kind","subject","source","preview"}
                              for the top-2 results (for downstream metrics)

        Returns empty string when the best score exceeds 1.5 (no good match).
        """
        NOT_FOUND_MSG = ""
        self.last_sources = []
        try:
            explanation = ""
            docs_with_scores = self.retrieve_full(query)
            scores = [score for _, score in docs_with_scores]
            best_score = min(scores) if scores else float("inf")
            self.last_score = best_score
            docs = [doc for doc, _ in docs_with_scores]

            # Record top-2 for downstream logging regardless of cutoff
            self.last_sources = [
                {
                    "score": float(s),
                    "kind": d.metadata.get("kind", "") if hasattr(d, "metadata") else "",
                    "subject": d.metadata.get("subject", "") if hasattr(d, "metadata") else "",
                    "source": d.metadata.get("source", "") if hasattr(d, "metadata") else "",
                    "preview": (d.page_content[:120] if hasattr(d, "page_content") else "").strip(),
                }
                for d, s in docs_with_scores[:2]
            ]

            if not docs or best_score > 1.5:
                return NOT_FOUND_MSG
        except Exception as e:
            log(_COMPONENT, f"RAG ERROR in explain(): {e}")
            return NOT_FOUND_MSG

        try:
            selected_docs = docs[:2]
            explanation = "\n\n".join(doc.page_content for doc in selected_docs)
            return explanation
        except Exception as e:
            log(_COMPONENT, f"RAG ERROR assembling explanation: {e}")
        return NOT_FOUND_MSG

    # ------------------------------------------------------------------
    # Hot-swap corpus
    # ------------------------------------------------------------------

    def reload_from_path(self, name: str, src_dir: str,
                         mode: str = "replace") -> int:
        """Load .md/.txt from *src_dir*, tag with subject=*name*.

        mode='replace': drop the existing FAISS index and rebuild from new
                        docs only.
        mode='append':  add new docs to the existing index (and self.docs).

        Returns the number of new chunks loaded.

        After a successful load, tries to apply course_config.yml shipped
        alongside the corpus files (via tutor.brain.course.apply_from_yaml).
        Failure is logged and swallowed so RAG still works without a config.
        """
        src_dir = os.path.abspath(src_dir)
        if not os.path.isdir(src_dir):
            raise FileNotFoundError(f"RAG source directory not found: {src_dir}")

        new_docs: List[Document] = []
        for file_glob in ("*.txt", "*.md"):
            loader = DirectoryLoader(
                src_dir,
                glob=file_glob,
                loader_cls=TextLoader,
                loader_kwargs={"encoding": "utf-8"},
                recursive=True,
            )
            tmp = loader.load_and_split(text_splitter=self.text_splitter)
            for doc in tmp:
                doc.metadata = {
                    "kind": self.index_name,
                    "subject": name,
                    **doc.metadata,
                }
            new_docs.extend(tmp)

        if not new_docs:
            raise ValueError(f"No .md or .txt files found in {src_dir}")

        if mode == "replace":
            self.docs = list(new_docs)
            # Remove on-disk index so create_vec_store rebuilds cleanly
            try:
                if os.path.isdir(RAG_STORE_DIR):
                    shutil.rmtree(RAG_STORE_DIR)
            except Exception as e:
                log(_COMPONENT, f"Could not remove old index: {e}")
            self.create_vec_store()
        elif mode == "append":
            self.docs.extend(new_docs)
            if self.vec_store is None:
                self.create_vec_store()
            else:
                self.vec_store.add_documents(new_docs)
                try:
                    os.makedirs(RAG_STORE_DIR, exist_ok=True)
                    self.vec_store.save_local(
                        RAG_STORE_DIR, index_name=self.index_name
                    )
                except Exception as e:
                    log(_COMPONENT, f"save_local after append failed: {e}")
        else:
            raise ValueError(
                f"Unknown mode: {mode!r} (expected 'replace' or 'append')"
            )

        # Refresh derived state
        self.wordkeys = self.get_docs_wordkeys(self.docs)
        if hasattr(self, "_vocabulary_cache"):
            del self._vocabulary_cache

        # Rebuild retriever so it picks up the new vec_store reference
        if self.vec_store is not None:
            self.retrivers[self.index_name] = self.vec_store.as_retriever(
                search_kwargs={"filter": {"kind": self.index_name}, "k": 3}
            )

        self._active_subject = name

        # Apply course_config.yml if present alongside the corpus
        try:
            yml_path = os.path.join(src_dir, "course_config.yml")
            if os.path.isfile(yml_path):
                from tutor.brain import course  # lazy import — optional module
                cfg = course.apply_from_yaml(yml_path)
                log(_COMPONENT,
                    f"Course config applied: {cfg.fields.get('name')!r}")
        except Exception as e:
            log(_COMPONENT, f"Failed to apply course_config.yml: {e}")

        log(_COMPONENT,
            f"reload_from_path: subject={name!r}, mode={mode!r}, "
            f"new_chunks={len(new_docs)}, total={len(self.docs)}")
        return len(new_docs)

    # ------------------------------------------------------------------
    # Vocabulary extraction
    # ------------------------------------------------------------------

    def get_vocabulary(self) -> set:
        """Extract technical terms from RAG documents for STT correction.

        Cached after first call; invalidated by reload_from_path.
        Returns a set of Latin / mixed-script terms and Russian uppercase
        abbreviations found in the loaded corpus.
        """
        if hasattr(self, "_vocabulary_cache"):
            return self._vocabulary_cache
        terms: set = set()
        for doc in self.docs:
            text = doc.page_content if hasattr(doc, "page_content") else str(doc)
            for w in text.split():
                w_clean = w.strip(".,;:!?()[]{}\"'«»—–")
                if not w_clean or len(w_clean) < 3:
                    continue
                # Latin or mixed-script technical terms
                if any(c.isascii() and c.isalpha() for c in w_clean):
                    terms.add(w_clean)
                # Russian uppercase abbreviations (3+ chars)
                elif w_clean.isupper() and len(w_clean) >= 3:
                    terms.add(w_clean)
        self._vocabulary_cache = terms
        return self._vocabulary_cache
