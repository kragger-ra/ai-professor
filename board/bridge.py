"""QObject exposed to the webviews via QWebChannel.

JS calls bridge methods like ``bridge.read_aloud(text)`` and ``bridge.insert_into_chat(text)``.
Each slot just forwards to BoardCommander (writes to commands.jsonl) or
emits a Qt signal the MainWindow listens to (for in-process UI actions
like populating the chat input field).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot


class BoardBridge(QObject):
    # Emitted when JS wants the chat input field populated (RMB → "Вставить в чат").
    insert_into_chat_requested = Signal(str)
    # Emitted when JS triggers any action; MainWindow renders a small chip
    # in the chat pane so the user sees what they just asked for. The label
    # is one of "read", "read_formula", "explain", "insert".
    intent_emitted = Signal(str, str)
    # Emitted when JS asks for a note on a selected fragment — MainWindow
    # opens a Qt dialog for the note text (free-form, multi-line).
    comment_requested = Signal(str)

    def __init__(self, commander, parent=None) -> None:
        super().__init__(parent)
        self._commander = commander

    # ------------------------------------------------------------------
    # Slots callable from JavaScript through QWebChannel.
    # ------------------------------------------------------------------

    @Slot(str)
    def read_aloud(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._commander.read_aloud(text)
            self.intent_emitted.emit("read", text)

    @Slot(str)
    def read_formula(self, latex: str) -> None:
        latex = (latex or "").strip()
        if latex:
            self._commander.read_formula(latex)
            self.intent_emitted.emit("read_formula", latex)

    @Slot(str)
    def explain(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self._commander.explain(text)
            self.intent_emitted.emit("explain", text)

    @Slot(str)
    def insert_into_chat(self, text: str) -> None:
        text = (text or "").strip()
        if text:
            self.insert_into_chat_requested.emit(text)
            self.intent_emitted.emit("insert", text)

    @Slot(bool)
    def set_tts_muted(self, muted: bool) -> None:
        self._commander.tts_mute(bool(muted))

    @Slot(str)
    def request_comment(self, anchor: str) -> None:
        anchor = (anchor or "").strip()
        if anchor:
            self.comment_requested.emit(anchor)

    @Slot(str)
    def remove_comment(self, comment_id: str) -> None:
        comment_id = (comment_id or "").strip()
        if comment_id:
            self._commander.remove_comment(comment_id)
