"""Faster-Whisper video → time-anchored transcript.

This module turns a video file into a list of ``Segment`` records
{start, end, text} that downstream code can persist as a JSON sidecar
and query by time or text. The model runs locally — no API tokens are
spent on transcription, by design.

The audio extraction goes through ``pydub`` (which already ships with
the project) and shells out to ffmpeg under the hood. The resulting
PCM is fed to Faster-Whisper one pass with segment-level timestamps;
word-level timestamps are intentionally OFF (3-5x slower with marginal
gain for the way the tutor uses them).
"""
from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

import numpy as np
from pydub import AudioSegment

from tutor.util import log


@dataclass
class Segment:
    start: float            # seconds from start of video
    end: float              # seconds from start of video
    text: str

    def as_dict(self) -> dict:
        return {"start": round(self.start, 3),
                "end": round(self.end, 3),
                "text": self.text}


# Whisper model singleton — loading the large-v3-turbo model takes ~5-15s
# and burns ~3 GB of VRAM. The tutor process already has a copy via
# CaptureThread.recognizer; for standalone CLI / first-time UI runs we
# carry our own singleton here.
_MODEL = None
_MODEL_DEVICE = ""


def _get_model(device: Optional[str] = None):
    """Lazy-load the same Faster-Whisper model the live tutor uses.

    If the caller passed an explicit ``device``, we honour it; otherwise
    the env STT_COMPUTE_DEVICE wins, falling back to ``cuda``.
    """
    global _MODEL, _MODEL_DEVICE
    if _MODEL is not None and (device is None or device == _MODEL_DEVICE):
        return _MODEL
    from tutor.audio.stt import FasterWhisperSTT  # local import: keeps the
    # module importable without faster-whisper available, useful for tests
    chosen = device or os.getenv("STT_COMPUTE_DEVICE", "cuda")
    log("video", f"loading Faster-Whisper on {chosen}...")
    _MODEL = FasterWhisperSTT(device=chosen)
    _MODEL_DEVICE = chosen
    log("video", "Faster-Whisper ready")
    return _MODEL


# ---------------------------------------------------------------------------
# Audio extraction
# ---------------------------------------------------------------------------

def _extract_pcm_wav(video_path: Path) -> bytes:
    """Extract audio from any pydub-readable video (mp4 / mkv / webm /
    mov / avi) and re-encode as 16 kHz mono PCM WAV — the format
    Faster-Whisper consumes most efficiently."""
    audio = AudioSegment.from_file(str(video_path))
    audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
    buf = io.BytesIO()
    audio.export(buf, format="wav")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Transcription
# ---------------------------------------------------------------------------

def transcribe_video(
    video_path: Path,
    *,
    language: str = "ru",
    device: Optional[str] = None,
    on_progress: Optional[Callable[[float, str], None]] = None,
) -> List[Segment]:
    """Run Whisper over the video's audio and return time-anchored segments.

    ``on_progress(fraction, partial_text)`` fires after every emitted
    segment with the current playback position normalised to [0, 1] and
    the text recognised so far. ``fraction`` is the segment END divided
    by total audio duration; ``partial_text`` is the segment that just
    closed (NOT the cumulative text — callers can accumulate themselves
    if they need it).
    """
    if not video_path.exists():
        raise FileNotFoundError(video_path)

    log("video", f"extracting audio from {video_path.name}")
    wav_bytes = _extract_pcm_wav(video_path)

    # Total duration for progress reporting.
    duration_s = len(wav_bytes) / (16000 * 2)  # 16kHz, 16-bit mono
    log("video", f"audio: {duration_s:.1f}s; transcribing...")

    recognizer = _get_model(device)
    # Faster-Whisper's transcribe yields a generator; iterate so we can
    # report progress segment-by-segment. We pass the WAV bytes through
    # an io.BytesIO so the model reads it as a file.
    beam = 1 if recognizer.device == "cpu" else 5
    segments_iter, info = recognizer.model.transcribe(
        io.BytesIO(wav_bytes),
        language=language,
        beam_size=beam,
        vad_filter=True,           # video has long silences; let Whisper skip them
        condition_on_previous_text=True,  # better continuity on long-form
    )

    out: List[Segment] = []
    for s in segments_iter:
        seg = Segment(start=float(s.start), end=float(s.end),
                      text=(s.text or "").strip())
        if seg.text:
            out.append(seg)
            if on_progress is not None and duration_s > 0:
                try:
                    on_progress(min(seg.end / duration_s, 1.0), seg.text)
                except Exception:
                    pass
    log("video",
        f"done: {len(out)} segments, "
        f"avg {duration_s / max(len(out), 1):.1f}s per segment")
    return out


# ---------------------------------------------------------------------------
# Helpers for the JSON sidecar format
# ---------------------------------------------------------------------------

def segments_to_jsonable(segments: List[Segment]) -> List[dict]:
    return [s.as_dict() for s in segments]


def segments_from_jsonable(data: List[dict]) -> List[Segment]:
    out: List[Segment] = []
    for d in data:
        try:
            out.append(Segment(
                start=float(d.get("start", 0.0)),
                end=float(d.get("end", 0.0)),
                text=str(d.get("text") or "").strip(),
            ))
        except Exception:
            continue
    return out


def segment_at(segments: List[Segment], time_s: float) -> Optional[Segment]:
    """Return the segment whose [start, end] covers ``time_s``, or the
    closest one if no exact match (handy for 'what was being said at
    5:20' queries that hit between segments)."""
    if not segments:
        return None
    for s in segments:
        if s.start <= time_s <= s.end:
            return s
    # Fallback: closest by midpoint distance.
    return min(segments, key=lambda s: abs(((s.start + s.end) / 2) - time_s))


def segments_in_range(segments: List[Segment],
                       start_s: float, end_s: float) -> List[Segment]:
    """Return segments overlapping the [start_s, end_s] window."""
    if start_s > end_s:
        start_s, end_s = end_s, start_s
    return [s for s in segments if s.end >= start_s and s.start <= end_s]
