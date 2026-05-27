"""Board → tutor command writer.

Appends one JSON object per line to ``data/board_commands.jsonl``. The
tutor's ``CommandsTail`` polls this file. Failures are swallowed so a
missing tutor doesn't break the board UI.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path


def _utcnow_iso() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


class BoardCommander:
    def __init__(self, path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._path = path or (
            Path(__file__).resolve().parent.parent
            / "data" / "board_commands.jsonl"
        )
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Public surface — one method per command type
    # ------------------------------------------------------------------

    def chat_input(self, text: str) -> None:
        self._emit("chat_input", text=text)

    def read_aloud(self, text: str) -> None:
        self._emit("read_aloud", text=text)

    def read_formula(self, latex: str) -> None:
        self._emit("read_formula", latex=latex)

    def explain(self, text: str) -> None:
        self._emit("explain", text=text)

    def tts_mute(self, muted: bool) -> None:
        self._emit("tts_mute", muted=bool(muted))

    def stt_mode(self, mode: str) -> None:
        self._emit("stt_mode", mode=mode)

    def stt_paused(self, paused: bool) -> None:
        self._emit("stt_paused", paused=bool(paused))

    def document_added(self, doc_id: str, name: str, kind: str,
                       text: str) -> None:
        """Tell the tutor that a new doc is now part of the context."""
        self._emit("document_added", id=doc_id, name=name, kind=kind, text=text)

    def document_removed(self, doc_id: str) -> None:
        self._emit("document_removed", id=doc_id)

    def add_comment(self, comment_id: str, anchor: str, note: str) -> None:
        self._emit("add_comment", comment_id=comment_id,
                   anchor=anchor, note=note)

    def remove_comment(self, comment_id: str) -> None:
        self._emit("remove_comment", comment_id=comment_id)

    def load_course(self, path: str) -> None:
        """Ask the tutor to hot-swap the active RAG corpus to this package."""
        self._emit("load_course", path=str(path))

    def audio_mode(self, mode: str) -> None:
        """Persist the audio mode (``local`` / ``meeting``).

        Mode takes effect on the NEXT tutor restart — the audio threads
        hold their devices open from boot. The tutor writes
        ``data/audio_mode.txt`` so the choice survives across runs.
        """
        self._emit("audio_mode", mode=mode)

    # ------------------------------------------------------------------

    def _emit(self, ctype: str, **fields) -> None:
        record = {"ts": _utcnow_iso(), "type": ctype, **fields}
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            try:
                with open(self._path, "a", encoding="utf-8") as f:
                    f.write(line)
                    f.flush()
                    os.fsync(f.fileno())
            except Exception:
                pass    # tutor not running — drop silently
