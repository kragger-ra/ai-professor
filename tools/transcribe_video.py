"""CLI: transcribe a video file with Faster-Whisper and store the result.

Run:
    python -m tools.transcribe_video path/to/video.mp4
    python -m tools.transcribe_video lecture.mp4 --language ru --device cuda

The video is copied into ``data/videos/<id>/`` and the time-anchored
transcript saved as ``transcript.json``. Re-running on the same file is
idempotent — the video_id is derived from path + mtime.

This CLI exists so the tester can prepare videos in batch from the
shell without spinning up the board UI. The board's «Видеоматериалы»
menu eventually wraps the same pipeline behind a progress dialog.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(
        prog="transcribe_video",
        description="Faster-Whisper video transcription → JSON sidecar",
    )
    p.add_argument("video", type=Path, help="Path to the video file")
    p.add_argument("--language", default="ru", help="Whisper language code (default: ru)")
    p.add_argument("--device", default=None,
                   help="cpu / cuda (default: env STT_COMPUTE_DEVICE or cuda)")
    p.add_argument("--note", default="",
                   help="Optional short description stored alongside the transcript")
    p.add_argument("--no-copy", action="store_true",
                   help="Don't copy the video into the store; just reference it in place")
    args = p.parse_args()

    if not args.video.exists():
        print(f"error: file not found: {args.video}", file=sys.stderr)
        return 1

    # Local imports — let argparse fail fast on bad args without loading
    # the (heavy) Whisper model.
    from tutor.audio.video_transcribe import transcribe_video
    from tutor.video_store import VideoStore

    last_progress_print = 0.0

    def _progress(fraction: float, text: str) -> None:
        nonlocal last_progress_print
        now = time.monotonic()
        if now - last_progress_print < 1.0 and fraction < 1.0:
            return
        last_progress_print = now
        bar_w = 30
        filled = int(bar_w * fraction)
        bar = "#" * filled + "-" * (bar_w - filled)
        sys.stdout.write(f"\r  [{bar}] {fraction*100:5.1f}%  {text[:60]}")
        sys.stdout.flush()

    print(f"transcribing: {args.video}")
    try:
        segments = transcribe_video(
            args.video, language=args.language, device=args.device,
            on_progress=_progress,
        )
    except Exception as exc:
        sys.stdout.write("\n")
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    sys.stdout.write("\n")

    store = VideoStore()
    entry = store.register_transcribed(
        args.video, segments,
        note=args.note,
        copy_into_store=not args.no_copy,
    )
    print(f"OK: {len(segments)} segments, {entry.duration_s:.1f}s total")
    print(f"  video_id:   {entry.video_id}")
    print(f"  stored at:  {entry.stored_path}")
    print(f"  transcript: {entry.transcript_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
