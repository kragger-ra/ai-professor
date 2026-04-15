# -*- coding: utf-8 -*-
"""
Download, transcribe, and summarize a single lecture.

Usage:
    set PYTHONPATH=src
    python scripts/process_single_lecture.py --id VIDEO_ID --week WEEK [--date DATE]
"""

import argparse
import sys
import time
from datetime import date
from pathlib import Path

sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

from dotenv import load_dotenv
load_dotenv()

# Reuse all logic from process_all_lectures
from process_all_lectures import (
    AUDIO_DIR, TRANSCRIPT_DIR, RAG_DIR,
    download_audio, transcribe, summarize_lecture,
)


def main():
    parser = argparse.ArgumentParser(description="Process a single lecture")
    parser.add_argument("--id", required=True, help="YouTube video ID")
    parser.add_argument("--week", required=True, help="Week label (e.g. '11-12')")
    parser.add_argument("--date", default=str(date.today()), help="Lecture date (YYYY-MM-DD)")
    args = parser.parse_args()

    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    RAG_DIR.mkdir(parents=True, exist_ok=True)

    audio_path = AUDIO_DIR / f"lecture_w{args.week}.opus"
    transcript_path = TRANSCRIPT_DIR / f"lecture_w{args.week}.txt"
    rag_path = RAG_DIR / f"lecture_w{args.week}_full.md"

    total_t0 = time.perf_counter()

    # Phase 1: Download
    print("=" * 60)
    print(f"PHASE 1: DOWNLOADING (video {args.id})")
    print("=" * 60)
    if not download_audio(args.id, audio_path):
        print("[FATAL] Download failed")
        sys.exit(1)

    # Phase 2: Transcribe
    print("\n" + "=" * 60)
    print("PHASE 2: TRANSCRIBING (faster-whisper large-v3, CUDA)")
    print("=" * 60)
    transcript = transcribe(audio_path, transcript_path)
    if not transcript:
        print("[FATAL] Empty transcript")
        sys.exit(1)

    # Phase 3: Summarize
    print("\n" + "=" * 60)
    print("PHASE 3: SUMMARIZING (Claude Opus via AWstore)")
    print("=" * 60)
    if rag_path.exists() and rag_path.stat().st_size > 500:
        print(f"[skip] Already summarized ({rag_path.stat().st_size} bytes)")
    else:
        t0 = time.perf_counter()
        summary = summarize_lecture(transcript, args.week, args.date)
        elapsed = time.perf_counter() - t0

        if summary:
            if not summary.startswith("# "):
                summary = f"# Конспект лекции — Неделя {args.week}\n\n{summary}"
            rag_path.write_text(summary, encoding="utf-8")
            print(f"Saved: {rag_path} ({len(summary)} chars, {elapsed:.0f}s)")
        else:
            print("[ERROR] Empty summary")

    total_elapsed = time.perf_counter() - total_t0
    print("\n" + "=" * 60)
    print(f"DONE in {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print("=" * 60)


if __name__ == "__main__":
    main()
