"""
Offline lecture recording processor.

Pipeline: video/audio file -> ffmpeg (extract audio) -> faster-whisper STT
-> TranscriptBuffer (chunking) -> LectureSummarizer -> saved summary + transcript.

Usage::

    python -m lecture.process_recording recording.mp4 --week 3
    python -m lecture.process_recording lecture.wav --week 1 --device cpu
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

# Allow running as: python src/lecture/process_recording.py
_SRC_DIR = Path(__file__).resolve().parent.parent
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from lecture.transcript_buffer import TranscriptBuffer
from lecture.summarizer import LectureSummarizer

logger = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".wma"}
VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".ts", ".flv"}


def extract_audio(input_path: Path, output_path: Path) -> Path:
    """Extract audio from video file using ffmpeg. Returns path to wav."""
    logger.info("Extracting audio from %s ...", input_path)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",                    # no video
        "-acodec", "pcm_s16le",   # 16-bit PCM
        "-ar", "16000",           # 16 kHz (optimal for Whisper)
        "-ac", "1",               # mono
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{result.stderr}")
    logger.info("Audio extracted to %s", output_path)
    return output_path


def transcribe(
    audio_path: Path,
    device: str = "cuda",
    model_name: str | None = None,
) -> list[dict]:
    """
    Transcribe audio file with faster-whisper.

    Returns list of segments: [{"start": float, "end": float, "text": str}, ...]
    """
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "faster-whisper is not installed. "
            "Install it: pip install faster-whisper~=1.2.0"
        )
        sys.exit(1)

    model_name = model_name or os.getenv(
        "FASTER_WHISPER_MODEL_NAME",
        "dvislobokov/faster-whisper-large-v3-turbo-russian",
    )
    logger.info("Loading Whisper model '%s' on %s ...", model_name, device)
    model = WhisperModel(model_name, device=device)

    logger.info("Transcribing %s ...", audio_path)
    segments_iter, info = model.transcribe(
        str(audio_path),
        language="ru",
        multilingual=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments = []
    for seg in segments_iter:
        segments.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })

    duration_min = info.duration / 60 if info.duration else 0
    logger.info(
        "Transcription complete: %d segments, %.1f min audio",
        len(segments), duration_min,
    )
    return segments


def segments_to_buffer(
    segments: list[dict],
    lecture_week: int,
    transcripts_dir: Path,
) -> TranscriptBuffer:
    """Feed whisper segments into TranscriptBuffer."""
    buf = TranscriptBuffer(
        lecture_week=lecture_week,
        transcripts_dir=transcripts_dir,
    )
    buf.start()
    for seg in segments:
        # Inject timestamp as datetime offset from epoch (for ordering)
        buf.add_segment(seg["text"])
    return buf


def save_timestamped_transcript(
    segments: list[dict],
    output_path: Path,
) -> Path:
    """Save transcript with timestamps as SRT-like text."""
    lines = []
    for seg in segments:
        start = str(timedelta(seconds=int(seg["start"])))
        end = str(timedelta(seconds=int(seg["end"])))
        lines.append(f"[{start} -> {end}] {seg['text']}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Timestamped transcript saved to %s", output_path)
    return output_path


def process_recording(
    input_file: str | Path,
    lecture_week: int = 1,
    device: str = "cuda",
    whisper_model: str | None = None,
    transcripts_dir: str | Path = "data/transcripts",
    skip_summary: bool = False,
) -> dict:
    """
    Full processing pipeline.

    Returns dict with paths to generated files:
        {"transcript": Path, "timestamped": Path, "summary": Path | None}
    """
    input_path = Path(input_file)
    transcripts_dir = Path(transcripts_dir)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    suffix = input_path.suffix.lower()
    results: dict = {}

    # Step 1: Extract audio if video
    audio_path = input_path
    tmp_wav = None
    if suffix in VIDEO_EXTENSIONS:
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        tmp_wav.close()
        audio_path = extract_audio(input_path, Path(tmp_wav.name))
    elif suffix not in AUDIO_EXTENSIONS:
        logger.warning("Unknown file extension '%s', trying as audio", suffix)

    try:
        # Step 2: Transcribe
        segments = transcribe(audio_path, device=device, model_name=whisper_model)

        if not segments:
            logger.warning("No speech detected in %s", input_path)
            return {"transcript": None, "timestamped": None, "summary": None}

        # Step 3: Save timestamped transcript
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        ts_path = transcripts_dir / f"lecture_w{lecture_week}_{date_str}_timestamped.txt"
        save_timestamped_transcript(segments, ts_path)
        results["timestamped"] = ts_path

        # Step 4: Buffer and chunk
        buf = segments_to_buffer(segments, lecture_week, transcripts_dir)
        raw_path = buf.stop()
        results["transcript"] = raw_path
        chunks = buf.get_chunks()
        logger.info("Got %d chunks for summarization", len(chunks))

        # Step 5: Summarize
        if skip_summary or not chunks:
            results["summary"] = None
        else:
            summarizer = LectureSummarizer()
            summary = summarizer.summarize(
                chunks=chunks,
                lecture_week=lecture_week,
                save=True,
            )
            summary_path = (
                Path(summarizer.summaries_dir)
                / f"week{lecture_week}_{datetime.now().date().isoformat()}.md"
            )
            results["summary"] = summary_path
            print(f"\n{'='*60}")
            print(f"SUMMARY (week {lecture_week}):")
            print(f"{'='*60}")
            print(summary[:2000])
            if len(summary) > 2000:
                print(f"... ({len(summary)} chars total)")

    finally:
        # Cleanup temp audio
        if tmp_wav is not None:
            try:
                os.unlink(tmp_wav.name)
            except OSError:
                pass

    return results


def main():
    parser = argparse.ArgumentParser(
        description="Process lecture recording: STT + summarization",
    )
    parser.add_argument(
        "input_file",
        help="Path to video or audio file",
    )
    parser.add_argument(
        "--week", "-w",
        type=int, default=1,
        help="Lecture week number (default: 1)",
    )
    parser.add_argument(
        "--device", "-d",
        default="cuda",
        choices=["cuda", "cpu"],
        help="Compute device for Whisper (default: cuda)",
    )
    parser.add_argument(
        "--model", "-m",
        default=None,
        help="Whisper model name (default: from env or dvislobokov/faster-whisper-large-v3-turbo-russian)",
    )
    parser.add_argument(
        "--transcripts-dir",
        default="data/transcripts",
        help="Directory for transcripts (default: data/transcripts)",
    )
    parser.add_argument(
        "--no-summary",
        action="store_true",
        help="Skip LLM summarization (only transcribe)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    results = process_recording(
        input_file=args.input_file,
        lecture_week=args.week,
        device=args.device,
        whisper_model=args.model,
        transcripts_dir=args.transcripts_dir,
        skip_summary=args.no_summary,
    )

    print(f"\nResults:")
    for key, path in results.items():
        status = str(path) if path else "skipped"
        print(f"  {key}: {status}")


if __name__ == "__main__":
    main()
