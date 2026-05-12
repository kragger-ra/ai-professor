import os
import sys
import time
import traceback
from typing import Dict, List, Tuple

from langchain_community.document_loaders import DirectoryLoader, TextLoader
from langchain_community.vectorstores import FAISS
from langchain_core.documents.base import Document
from langchain_core.vectorstores import VectorStoreRetriever
from langchain_text_splitters import TextSplitter

from agent.llm_clients.lc_clients import get_embeddings_model

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    os.environ["KMP_DUPLICATE_LIB_OK"] = "True"

from config_schema.general import get_secret
from data_schema.structure_templates import REPO_DATA_PATH, REPO_RESOURCE_PATH
from utils.debug import timing_context

RAG_DOCS_DIR = os.path.join(
    REPO_RESOURCE_PATH,
    "Documents",
)

RAG_COURSE_DIR = os.path.join(
    REPO_RESOURCE_PATH,
    "RAG",
)

RAG_STORE_DIR = os.path.join(REPO_DATA_PATH, "rag_vector_store")


class CustomTripleNewLineSplitter(TextSplitter):
    def __init__(self, chunk_size=1000, chunk_overlap=0, separator="\n\n\n"):
        self.separator = separator
        super().__init__(chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    def split_text(self, text: str) -> list[str]:
        # Split on exact \n\n\n first
        chunks = text.split(self.separator)
        if len(chunks) > 0 and len(chunks[-1].split("\n")) > 0:
            if chunks[-1].split("\n")[0].strip() == "Источники:":
                chunks = chunks[:-1]
        # Fallback: if a chunk is too large, split on \n\n (markdown sections)
        # Then merge adjacent small chunks to avoid embedding noise
        _MIN_CHUNK = 50  # chars — merge headers / tiny fragments into neighbours
        raw = []
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
        result = []
        buf = ""
        for part in raw:
            if len(part) < _MIN_CHUNK:
                # Small chunk — prepend to buffer, will merge with next
                buf = (buf + "\n\n" + part).strip() if buf else part
            else:
                if buf:
                    # Merge buffered small chunks with this larger chunk
                    part = buf + "\n\n" + part
                    buf = ""
                result.append(part)
        if buf:
            # Trailing small chunks — append to last result or keep standalone
            if result:
                result[-1] = result[-1] + "\n\n" + buf
            else:
                result.append(buf)
        return result


class CustomDirectoryLoader:
    def __init__(self, dir: str, doc_kinds: List[str]):
        self.dir = dir
        self.doc_kinds = doc_kinds

    def get_docs_wordkeys(self, docs):
        wordkeys = []
        for doc in docs:
            text = doc.page_content
            if text:
                text_split = text.split("\n")
                if len(text_split) > 1:
                    wordkeys.append(text_split[0])
        return wordkeys

    def load(self, text_splitter: TextSplitter = None):
        docs = []
        for kind in self.doc_kinds:
            path = os.path.join(self.dir, kind)
            if not os.path.isdir(path):
                print(f"[RAG Loader] Skipping missing directory: {path}")
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


class RagModel:
    def __init__(self):
        start_time = time.time()
        self.index_name = "knowledge"
        self._active_subject = None  # set by reload_from_path
        self.vec_store_full_path = os.path.join(
            RAG_STORE_DIR, self.index_name + ".faiss"
        )
        # self.index_filename = self.index_name + ".index"
        self.dataloader = CustomDirectoryLoader(RAG_DOCS_DIR, [self.index_name])
        self.course_loader = CustomDirectoryLoader(RAG_COURSE_DIR, ["course_materials"])
        self.text_splitter = CustomTripleNewLineSplitter(
            chunk_size=1000, chunk_overlap=0
        )

        load_time_start = time.time()
        self.docs = self.dataloader.load(self.text_splitter)
        try:
            course_docs = self.course_loader.load(self.text_splitter)
            self.docs.extend(course_docs)
            print(f"[RagModel] Loaded {len(course_docs)} course material chunks")
        except Exception as e:
            print(f"[RagModel] No course materials loaded: {e}")
        self.wordkeys = self.get_docs_wordkeys(self.docs)
        print(
            f"[RagModel Timing] Document loading took {time.time() - load_time_start:.2f} seconds"
        )

        try:
            self.embeddings = get_embeddings_model()
        except Exception as e:
            print(f"[RagModel] Error initializing embeddings: {str(e)}. RAG WILL NOT WORK!")
            traceback.print_exc()

        self.load_vec_store()

        self.last_score = float("inf")  # L2 distance of last query (lower = better)
        self.retrivers: Dict[str, VectorStoreRetriever] = {}
        if self.vec_store is not None:
            self.retrivers[self.index_name] = self.vec_store.as_retriever(
                search_kwargs={"filter": {"kind": self.index_name}, "k": 3}
            )
            self.rag_warmup()
        else:
            print("[RagModel] WARNING: vec_store is None, RAG will not work!")

        print(
            f"[RagModel Timing] Total initialization took {time.time() - start_time:.2f} seconds"
        )

    def rag_warmup(self):
        # Warmup
        print(
            "[RagModel IMPORTANT] !!! IF CODE HERE CRASH / STOPS, TRY REMOVE THIS FOLDER: "
            + RAG_STORE_DIR
        )
        warmup_query = "Что такое вайб?"
        print("[RagModel] Warming up RagModel with query " + warmup_query)
        print("[RagModel] Warmin up results: " + self.explain(warmup_query))
        print("[RagModel] Warming up done succesfully, RAG ready!")

    def load_vec_store(self, force=False):
        # process create vec store
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
                except Exception as e:
                    print(f"[RagModel] Error loading vec store: {str(e)}")
                    traceback.print_exc()
                    db_exists = False
        else:
            db_exists = False
        if not db_exists:
            print("[RagModel] DB not saved on disk: creating from docs")
            self.vec_store = self.create_vec_store()

    def create_vec_store(self):
        vectorize_time_start = time.time()
        try:
            self.vec_store = FAISS.from_documents(
                documents=self.docs, embedding=self.embeddings
            )
            print(
                f"[RagModel Timing] Vectorization took {time.time() - vectorize_time_start:.2f} seconds"
            )
        except Exception as e:
            self.vec_store = None
            print(f"[RagModel] Error building vector store: {str(e)}")
            traceback.print_exc()
            return self.vec_store

        # https://github.com/langchain-ai/langchain/discussions/4188
        try:
            os.makedirs(RAG_STORE_DIR, exist_ok=True)
            self.vec_store.save_local(RAG_STORE_DIR, index_name=self.index_name)
            print(
                "[RagModel] Saved created vector store to disk: " + self.vec_store_full_path
            )
        except Exception as e:
            print(
                f"[RagModel] Error saving vector store to disk ({str(e)}); "
                "RAG continues in-memory, will rebuild next launch"
            )
        return self.vec_store

    def get_docs_wordkeys(self, docs):
        wordkeys = []
        for doc in docs:
            text = doc.page_content
            if text:
                text_split = text.split("\n")
                if len(text_split) > 1:
                    wordkeys.append(text_split[0])
        return wordkeys

    def retrieve_full(self, query) -> List[Tuple[Document, float]]:
        if self.vec_store is None:
            return []
        with timing_context("similarity_search_with_score"):
            return self.vec_store.similarity_search_with_score(query)

    def retrieve(self, query) -> List[Document]:
        if self.index_name not in self.retrivers:
            return []
        with timing_context("retrieve"):
            return self.retrivers[self.index_name].invoke(query)

    def explain(self, query: str) -> str:
        """
        Explain a query
        returns a string of an explanation relevant for query.
        """
        NOT_FOUND_MSG = ""  # "Словарь не нужен. Ничего не нашлось."
        try:
            explanation = ""
            docs_with_scores = self.retrieve_full(query)
            scores = [score for _, score in docs_with_scores]
            # score is a distance. Minimum - closer, better
            best_score = min(scores) if scores else float("inf")
            self.last_score = best_score
            docs = [doc for doc, _ in docs_with_scores]

            if not docs or best_score > 1.5:
                return NOT_FOUND_MSG
        except Exception as e:
            print("[RAG] RAG RAG !!!RAG ERROR!!!!", e)
        try:
            # Take first 2 most relevant documents
            selected_docs = docs[:2]
            # Combine the content from selected documents
            explanation += "\n\n".join(doc.page_content for doc in selected_docs)
            return explanation
        except Exception as e:
            print("[RAG] RAG RAG !!!RAG ERROR!!!!", e)
        return NOT_FOUND_MSG


    def reload_from_path(self, name: str, src_dir: str, mode: str = "replace") -> int:
        """Load .md/.txt from src_dir, tag with subject=name, replace or append the index.

        mode='replace': drop the existing FAISS index and rebuild from new docs only.
        mode='append':  add new docs to the existing index (and self.docs).
        Returns number of new chunks loaded.
        """
        src_dir = os.path.abspath(src_dir)
        if not os.path.isdir(src_dir):
            raise FileNotFoundError(f"RAG source directory not found: {src_dir}")

        new_docs = []
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
                doc.metadata = {"kind": self.index_name, "subject": name, **doc.metadata}
            new_docs.extend(tmp)

        if not new_docs:
            raise ValueError(f"No .md or .txt files found in {src_dir}")

        if mode == "replace":
            self.docs = list(new_docs)
            # Drop on-disk index so create_vec_store rebuilds cleanly
            try:
                if os.path.isdir(RAG_STORE_DIR):
                    import shutil
                    shutil.rmtree(RAG_STORE_DIR)
            except Exception as e:
                print(f"[RagModel] Could not remove old index: {e}")
            self.create_vec_store()
        elif mode == "append":
            self.docs.extend(new_docs)
            if self.vec_store is None:
                self.create_vec_store()
            else:
                self.vec_store.add_documents(new_docs)
                try:
                    os.makedirs(RAG_STORE_DIR, exist_ok=True)
                    self.vec_store.save_local(RAG_STORE_DIR, index_name=self.index_name)
                except Exception as e:
                    print(f"[RagModel] save_local after append failed: {e}")
        else:
            raise ValueError(f"Unknown mode: {mode!r} (expected 'replace' or 'append')")

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
        # Course-level config (name/topic/teaching style) is shipped alongside
        # the .md/.txt files in course_config.yml — apply it so subsequent
        # prompts swap PersonaLab-isms for the loaded subject.
        try:
            yml_path = os.path.join(os.path.abspath(src_dir), "course_config.yml")
            if os.path.isfile(yml_path):
                from lecture import course_config
                cfg = course_config.apply_from_yaml(yml_path)
                print(f"[RAG] Course config applied: {cfg.fields.get('name')!r}")
        except Exception as e:
            print(f"[RAG] Failed to apply course_config.yml: {e}")
        print(f"[RagModel] reload_from_path: subject='{name}', mode='{mode}', "
              f"new_chunks={len(new_docs)}, total={len(self.docs)}")
        return len(new_docs)

    def get_vocabulary(self) -> set:
        """Extract technical terms from RAG documents for STT correction."""
        if hasattr(self, '_vocabulary_cache'):
            return self._vocabulary_cache
        terms = set()
        for doc in self.docs:
            text = doc.page_content if hasattr(doc, 'page_content') else str(doc)
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


if __name__ == "__main__":

    # file_path = 'NetTyanSlang.txt'
    # with open(file_path, 'r', encoding='utf-8') as file:
    #     content = file.read()
    #
    # sections = content.split('\n\n')
    #
    # dictionary = {}
    # for section in sections:
    #     lines = section.strip().split('\n')
    #     key = lines[0]
    #     value = '\n'.join(lines[1:])
    #     dictionary[key] = value

    try:
        init_start = time.time()
        rag = RagModel()
        print(rag.wordkeys)
        print(
            f"[RagModel Timing] RagModel instantiation took {time.time() - init_start:.2f} seconds"
        )

        real_query = """Ну чё перцы вайбовые погнали хавать"""
        query = real_query  # "Вайб"  #
        results = rag.retrieve_full(query)

        print(f"Query: {query}")
        for doc, score in results:
            print(f"Score: {score}")
            print(f"Content: {doc.page_content[:200]}...")
            print("-" * 50)

        print("------------------------- retriever -------------------")
        ret = rag.retrieve(query)
        print(ret)
        print("------------------------- explain -------------------")
        exp = rag.explain(query)
        print(exp)
    except Exception as e:
        print(f"Error occurred: {str(e)}")
