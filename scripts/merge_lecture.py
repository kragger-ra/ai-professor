# -*- coding: utf-8 -*-
"""
Re-run only the summarization phase for an already-transcribed lecture.

Usage:
    set PYTHONPATH=src
    python scripts/merge_lecture.py --week 11-12 --date 2026-04-11
"""

import argparse
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

from process_all_lectures import (
    TRANSCRIPT_DIR, RAG_DIR, summarize_lecture,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--week", required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--force", action="store_true", help="Overwrite existing summary")
    args = parser.parse_args()

    transcript_path = TRANSCRIPT_DIR / f"lecture_w{args.week}.txt"
    rag_path = RAG_DIR / f"lecture_w{args.week}_full.md"

    if not transcript_path.exists():
        print(f"[FATAL] Transcript not found: {transcript_path}")
        sys.exit(1)

    if rag_path.exists() and rag_path.stat().st_size > 500 and not args.force:
        print(f"[skip] Already exists ({rag_path.stat().st_size} bytes). Use --force to overwrite.")
        return

    transcript = transcript_path.read_text(encoding="utf-8")
    print(f"Transcript: {len(transcript)} chars")

    t0 = time.perf_counter()
    summary = summarize_lecture(transcript, args.week, args.date)
    elapsed = time.perf_counter() - t0

    if summary:
        if not summary.startswith("# "):
            summary = f"# Конспект лекции — Неделя {args.week}\n\n{summary}"
        rag_path.write_text(summary, encoding="utf-8")
        print(f"\nSaved: {rag_path} ({len(summary)} chars, {elapsed:.0f}s)")
    else:
        print(f"\n[ERROR] Empty summary after {elapsed:.0f}s")


if __name__ == "__main__":
    main()
