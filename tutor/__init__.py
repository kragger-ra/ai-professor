"""AI Professor — Tutor v2.

A single-process, linear voice pipeline for a 1-on-1 AI tutor. Replaces the
legacy 4-process / multiprocessing.Manager architecture inherited from the
NetTyan streaming agent. See tutor/README.md for the phase plan.
"""
from pathlib import Path as _Path

try:
    from dotenv import load_dotenv as _load_dotenv
    # Load .env BEFORE any submodule reads env vars at import time
    # (llm.py / meta.py / prompt.py read config at module level).
    _load_dotenv(_Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass
