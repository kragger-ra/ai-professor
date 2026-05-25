"""Tutor-side mirror of the board's loaded documents.

The board uploads docs and sends ``document_added`` / ``document_removed``
commands. CommandsTail hands them to this store. The agent reads
``as_prompt_section()`` and appends it to the system prompt so the LLM
can answer questions grounded in the user's open documents.

Per-doc truncation cap: the LLM context window is finite — for OpenAI
gpt-5 the model is happy with hundreds of thousands of tokens, but we
still cap each doc at ~6000 characters to keep prompt size bounded.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

PER_DOC_CHARS = 6000


@dataclass
class StoredDoc:
    id: str
    name: str
    kind: str
    text: str


class DocumentStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_id: Dict[str, StoredDoc] = {}
        self._order: List[str] = []

    def add(self, doc_id: str, name: str, kind: str, text: str) -> None:
        with self._lock:
            if doc_id in self._by_id:
                self._by_id[doc_id] = StoredDoc(doc_id, name, kind, text)
                return
            self._by_id[doc_id] = StoredDoc(doc_id, name, kind, text)
            self._order.append(doc_id)

    def remove(self, doc_id: str) -> Optional[StoredDoc]:
        with self._lock:
            d = self._by_id.pop(doc_id, None)
            if d is not None and doc_id in self._order:
                self._order.remove(doc_id)
            return d

    def clear(self) -> None:
        with self._lock:
            self._by_id.clear()
            self._order.clear()

    def list(self) -> List[StoredDoc]:
        with self._lock:
            return [self._by_id[i] for i in self._order if i in self._by_id]

    def as_prompt_section(self) -> str:
        """Render the current docs as a Markdown-flavoured prompt section.

        Empty string when nothing is loaded — caller appends unconditionally.
        """
        docs = self.list()
        if not docs:
            return ""
        parts: List[str] = [
            "## Открытые документы студента",
            "(Студент сейчас работает с этими материалами в нашем приложении. "
            "Когда отвечаешь, опирайся на них и можешь прямо ссылаться: "
            "«в первом документе…», «на второй странице методички…».)",
        ]
        for i, d in enumerate(docs, 1):
            body = d.text.strip()
            if len(body) > PER_DOC_CHARS:
                body = body[:PER_DOC_CHARS] + "\n\n[…документ обрезан…]"
            parts.append(f"### Документ {i}: {d.name} ({d.kind})\n{body}")
        return "\n\n".join(parts)
