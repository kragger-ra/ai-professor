"""File-tail thread for board_events.jsonl.

Polls the JSONL file every 100 ms, emits a Qt signal for each parsed event.
Handles truncation / rotation: when the file shrinks, restart from offset 0.

Read in binary so a partial trailing line (writer hasn't flushed the newline
yet) is buffered, not mis-parsed.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal


class JsonlTail(QThread):
    new_event = Signal(dict)
    error = Signal(str)

    def __init__(self, path: Path, *, from_start: bool = False,
                 poll_ms: int = 100, parent=None) -> None:
        super().__init__(parent)
        self._path = Path(path)
        self._from_start = from_start
        self._poll = poll_ms / 1000.0
        self._stop_flag = False

    def run(self) -> None:
        # Wait for the file to appear (tutor may not have started yet).
        while not self._stop_flag and not self._path.exists():
            time.sleep(self._poll)
        if self._stop_flag:
            return

        try:
            offset = 0 if self._from_start else self._path.stat().st_size
        except OSError:
            offset = 0
        pending = b""

        while not self._stop_flag:
            try:
                if not self._path.exists():
                    time.sleep(self._poll)
                    continue
                size = self._path.stat().st_size
                if size < offset:
                    # File truncated (new session rotated the rolling log).
                    offset = 0
                    pending = b""
                if size > offset:
                    with open(self._path, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    offset = size
                    pending += chunk
                    parts = pending.split(b"\n")
                    pending = parts.pop()    # last item is the incomplete tail
                    for raw in parts:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw.decode("utf-8"))
                        except Exception as exc:
                            self.error.emit(f"json: {exc}")
                            continue
                        self.new_event.emit(event)
                time.sleep(self._poll)
            except Exception as exc:
                self.error.emit(f"{type(exc).__name__}: {exc}")
                time.sleep(self._poll)

    def stop_tail(self) -> None:
        self._stop_flag = True
