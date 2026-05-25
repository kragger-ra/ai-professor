"""Tail ``data/board_commands.jsonl`` and dispatch board → tutor commands.

The board sidecar writes one JSON object per line; we poll the file, parse
each new line, and call the matching handler. Like ``BoardLog``, this is
no-throw: if the file is missing or malformed we log and keep going.

Command schema (one per line, UTF-8):

  {"type":"chat_input", "text":"..."}                # typed input from chat
  {"type":"tts_mute",   "muted":true|false}          # toggle TTS playback
  {"type":"read_aloud", "text":"..."}                # voice this text now
  {"type":"explain",    "text":"..."}                # ask LLM to explain
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Callable, Dict, Optional

from tutor.util import log

_DEFAULT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "board_commands.jsonl"
)


class CommandsTail(threading.Thread):
    """Polls the commands JSONL and routes each event to a handler.

    Handlers receive the full dict so they can read any extra fields. A
    handler raising must NEVER stop the tail thread — exceptions are caught
    and logged.
    """

    def __init__(self, handlers: Dict[str, Callable[[dict], None]],
                 path: Optional[Path] = None, poll_s: float = 0.2) -> None:
        super().__init__(name="cmd-tail", daemon=True)
        self._handlers = handlers
        self._path = Path(path or _DEFAULT_PATH)
        self._poll = poll_s
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        # Start at end-of-file so old commands from a prior session aren't
        # replayed when the tutor restarts.
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            offset = self._path.stat().st_size if self._path.exists() else 0
        except Exception:
            offset = 0
        pending = b""
        while not self._stop:
            try:
                if not self._path.exists():
                    time.sleep(self._poll)
                    continue
                size = self._path.stat().st_size
                if size < offset:
                    offset = 0
                    pending = b""
                if size > offset:
                    with open(self._path, "rb") as f:
                        f.seek(offset)
                        chunk = f.read(size - offset)
                    offset = size
                    pending += chunk
                    parts = pending.split(b"\n")
                    pending = parts.pop()
                    for raw in parts:
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            cmd = json.loads(raw.decode("utf-8"))
                        except Exception as exc:
                            log("cmd-tail", f"json parse: {exc}")
                            continue
                        self._dispatch(cmd)
                time.sleep(self._poll)
            except Exception as exc:
                log("cmd-tail", f"loop: {type(exc).__name__}: {exc}")
                time.sleep(self._poll)

    def _dispatch(self, cmd: dict) -> None:
        ctype = cmd.get("type")
        handler = self._handlers.get(ctype) if ctype else None
        if handler is None:
            log("cmd-tail", f"no handler for type={ctype!r}")
            return
        try:
            handler(cmd)
        except Exception as exc:
            log("cmd-tail",
                f"handler {ctype} crashed: {type(exc).__name__}: {exc}")
