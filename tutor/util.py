"""Tiny shared helpers for the tutor-v2 pipeline."""
from __future__ import annotations

import time
from pathlib import Path

_T0 = time.time()
# Every log line is mirrored here so a run can be inspected even when the
# console output is lost (chcp quirks, redirected windows, etc.).
_LOG_FILE = Path(__file__).resolve().parent.parent / "tutor_v2.log"
try:
    _LOG_FILE.write_text("", encoding="utf-8")   # fresh log per process start
except Exception:
    pass


def log(component: str, msg: str) -> None:
    """Uniform one-line log — to stdout AND to tutor_v2.log."""
    line = f"[+{time.time() - _T0:7.1f}s] [{component:>9}] {msg}"
    print(line, flush=True)
    try:
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass
