"""Tiny shared helpers for the tutor-v2 pipeline."""
from __future__ import annotations

import time

_T0 = time.time()


def log(component: str, msg: str) -> None:
    """Uniform one-line log: [+elapsed] [component] message.

    Plain prints (single process, single stdout) — no logging framework,
    no per-process log files. Readable and good enough for a linear app.
    """
    print(f"[+{time.time() - _T0:7.1f}s] [{component:>9}] {msg}", flush=True)
