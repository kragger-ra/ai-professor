"""In-memory store of loaded documents (artifacts) on the board side.

Each document gets a stable short id (8 hex chars derived from its absolute
path). When a document is added, the board:
  1. inserts it into the local store (so the artifacts menu can list it),
  2. emits a ``document_added`` command so the tutor injects the plain text
     into the LLM context for subsequent answers,
  3. opens a DocumentWindow showing the rendered HTML.

Removing a document undoes 1+2; existing windows are closed by the UI.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Dict, List, Optional

from board.doc_reader import Document


def _doc_id(path: str) -> str:
    return hashlib.sha1(path.encode("utf-8")).hexdigest()[:8]


@dataclass
class Artifact:
    id: str
    doc: Document


class DocumentStore:
    def __init__(self) -> None:
        self._by_id: Dict[str, Artifact] = {}
        self._order: List[str] = []

    def add(self, doc: Document) -> Artifact:
        aid = _doc_id(doc.path)
        if aid in self._by_id:
            # Re-loading the same file overwrites (file may have changed).
            self._by_id[aid] = Artifact(id=aid, doc=doc)
            return self._by_id[aid]
        art = Artifact(id=aid, doc=doc)
        self._by_id[aid] = art
        self._order.append(aid)
        return art

    def remove(self, aid: str) -> Optional[Artifact]:
        art = self._by_id.pop(aid, None)
        if art is not None and aid in self._order:
            self._order.remove(aid)
        return art

    def get(self, aid: str) -> Optional[Artifact]:
        return self._by_id.get(aid)

    def list(self) -> List[Artifact]:
        return [self._by_id[aid] for aid in self._order if aid in self._by_id]
