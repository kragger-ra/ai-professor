"""Event log for the optional board UI sidecar.

The tutor process appends JSON-line events to ``data/board_events.jsonl``.
The separate ``board`` package tails the file and renders a two-pane window.

Design rules (intentional, not defensive):
 - Never raise out of a public method. The board is optional; a missing data
   directory or a locked file MUST NOT break the tutor's answer loop.
 - Each line is one JSON object, UTF-8, ``ensure_ascii=False`` so Cyrillic
   stays readable in the file.
 - Every event is mirrored to a per-session snapshot under
   ``data/sessions/board_<id>.jsonl`` so the rolling file can be truncated
   without losing history.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from tutor.util import log

_ROLLING_MAX_BYTES = 5 * 1024 * 1024     # truncate the live file at 5 MB on new session


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
           + f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


class BoardLog:
    """Append-only JSONL writer for board events.

    A single instance is owned by AgentThread for the lifetime of the
    tutor process. Thread-safe — the agent's generation worker calls
    ``professor_said`` / ``board_item`` from a background thread.
    """

    def __init__(self, path: Path | None = None,
                 session_id: str | None = None) -> None:
        self._lock = threading.Lock()
        self._seq = 0
        self._session_id = session_id or datetime.now().strftime("%Y%m%d-%H%M%S")
        # Body-text dedupe: a "повтори" turn rephrases the same answer and
        # the LLM emits identical [BOARD-*] items. Suppress so the chalkboard
        # doesn't get the same formula/term written twice in a row.
        self._seen_board_bodies: set[str] = set()
        self._rolling = path or (
            Path(__file__).resolve().parent.parent / "data" / "board_events.jsonl"
        )
        self._snapshot = (
            self._rolling.parent / "sessions"
            / f"board_{self._session_id}.jsonl"
        )
        self._enabled = True
        try:
            self._rolling.parent.mkdir(parents=True, exist_ok=True)
            self._snapshot.parent.mkdir(parents=True, exist_ok=True)
            # Truncate the rolling file when it grows past the cap, so the
            # live tail does not have to chew through megabytes on startup.
            if self._rolling.exists() and self._rolling.stat().st_size > _ROLLING_MAX_BYTES:
                self._rolling.write_text("", encoding="utf-8")
            self._emit("session_start", course=self._guess_course())
        except Exception as exc:
            log("board", f"init failed ({type(exc).__name__}: {exc}) — disabling")
            self._enabled = False

    # ------------------------------------------------------------------
    # Public surface
    # ------------------------------------------------------------------

    def user_said(self, text: str) -> int:
        return self._emit("user_said", text=text)

    def professor_said(self, text: str) -> int:
        return self._emit("professor_said", text=text)

    def board_item(self, kind: str, body: str, *, ref_seq: int,
                   caption: str = "") -> int:
        # Normalised dedupe key: strip + collapse whitespace, lower for terms
        # only (formulas are case-sensitive in LaTeX, code is case-sensitive
        # in code). For term keys we still lower so "RAG" == "rag".
        norm = " ".join(body.split())
        key = f"{kind.lower()}::{norm.lower() if kind.lower() == 'term' else norm}"
        with self._lock:
            if key in self._seen_board_bodies:
                return -1
            self._seen_board_bodies.add(key)
        return self._emit("board_item", kind=kind, body=body,
                          ref_seq=ref_seq, caption=caption)

    def warning(self, text: str) -> int:
        return self._emit("warning", text=text)

    def stt_transcript(self, text: str) -> int:
        """STT result for transcription mode — board fills its chat input."""
        return self._emit("stt_transcript", text=text)

    def comment_added(self, comment_id: str, anchor: str, note: str) -> int:
        return self._emit("comment_added", comment_id=comment_id,
                          anchor=anchor, note=note)

    def comment_removed(self, comment_id: str) -> int:
        return self._emit("comment_removed", comment_id=comment_id)

    def course_loaded(self, name: str, short_name: str, path: str,
                      chunks: int) -> int:
        """Announce that the tutor has hot-swapped to a new RAG corpus."""
        return self._emit("course_loaded", name=name, short_name=short_name,
                          path=path, chunks=int(chunks))

    def course_load_failed(self, error: str, path: str) -> int:
        return self._emit("course_load_failed", error=error, path=path)

    def close(self) -> None:
        if not self._enabled:
            return
        try:
            self._emit("session_end")
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _emit(self, event_type: str, **fields) -> int:
        if not self._enabled:
            return -1
        with self._lock:
            self._seq += 1
            record = {
                "ts": _utcnow_iso(),
                "session": self._session_id,
                "seq": self._seq,
                "type": event_type,
                **fields,
            }
            line = json.dumps(record, ensure_ascii=False) + "\n"
            for target in (self._rolling, self._snapshot):
                try:
                    with open(target, "a", encoding="utf-8") as f:
                        f.write(line)
                        f.flush()
                        os.fsync(f.fileno())
                except Exception as exc:
                    log("board", f"write {target.name} failed: "
                                 f"{type(exc).__name__}: {exc}")
            return self._seq

    def _guess_course(self) -> str:
        """Best-effort: read course name from data/current_course.json."""
        try:
            cc = self._rolling.parent / "current_course.json"
            if cc.exists():
                with open(cc, "r", encoding="utf-8") as f:
                    return (json.load(f).get("name") or "").strip()
        except Exception:
            pass
        return ""
