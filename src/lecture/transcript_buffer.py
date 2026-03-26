"""
Transcript buffer for lecture recording.

Accumulates STT output during a lecture for post-lecture summarization.
Persists raw transcript to disk and provides chunking for LLM processing.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_TRANSCRIPTS_DIR = Path("data/transcripts")
DEFAULT_CHUNK_TOKENS = 3000
DEFAULT_CHUNK_OVERLAP = 200


class TranscriptBuffer:
    """
    Thread-safe buffer that accumulates STT text during a lecture.

    Usage::

        buf = TranscriptBuffer(lecture_week=3)
        buf.start()
        # ... called from STT callback:
        buf.add_segment("текст из whisper")
        # ... after lecture ends:
        buf.stop()
        chunks = buf.get_chunks()
    """

    def __init__(
        self,
        lecture_week: int = 1,
        transcripts_dir: Path | str = DEFAULT_TRANSCRIPTS_DIR,
        chunk_tokens: int = DEFAULT_CHUNK_TOKENS,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self.lecture_week = lecture_week
        self.transcripts_dir = Path(transcripts_dir)
        self.chunk_tokens = chunk_tokens
        self.chunk_overlap = chunk_overlap

        self._segments: list[tuple[datetime, str]] = []
        self._lock = threading.Lock()
        self._active = False
        self._start_time: Optional[datetime] = None

        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    @property
    def is_active(self) -> bool:
        return self._active

    @property
    def segment_count(self) -> int:
        return len(self._segments)

    def start(self) -> None:
        """Start a new recording session."""
        with self._lock:
            self._segments.clear()
            self._active = True
            self._start_time = datetime.now()
            logger.info("Transcript buffer started (week %d)", self.lecture_week)

    def stop(self) -> Path:
        """
        Stop recording and persist the raw transcript to disk.

        Returns the path to the saved transcript file.
        """
        with self._lock:
            self._active = False

        path = self._save_to_disk()
        logger.info(
            "Transcript buffer stopped. %d segments saved to %s",
            len(self._segments),
            path,
        )
        return path

    def add_segment(self, text: str) -> None:
        """Add an STT segment (called from STT callback)."""
        text = text.strip()
        if not text:
            return
        with self._lock:
            if not self._active:
                return
            self._segments.append((datetime.now(), text))

    def get_full_text(self) -> str:
        """Return the full accumulated transcript as a single string."""
        with self._lock:
            return "\n".join(seg[1] for seg in self._segments)

    def get_chunks(self) -> list[str]:
        """
        Split the transcript into chunks suitable for LLM summarization.

        Uses approximate word-based splitting (1 token ~ 1 word for Russian
        with some margin). Chunks overlap by ``chunk_overlap`` words.
        """
        full_text = self.get_full_text()
        words = full_text.split()
        if not words:
            return []

        chunks: list[str] = []
        start = 0
        while start < len(words):
            end = start + self.chunk_tokens
            chunk = " ".join(words[start:end])
            chunks.append(chunk)
            start = end - self.chunk_overlap
            if start < 0:
                start = 0
            if end >= len(words):
                break

        logger.info(
            "Transcript split into %d chunks (%d words total)",
            len(chunks),
            len(words),
        )
        return chunks

    def get_timestamped_segments(self) -> list[tuple[datetime, str]]:
        """Return all segments with timestamps."""
        with self._lock:
            return list(self._segments)

    def _save_to_disk(self) -> Path:
        """Persist raw transcript to a text file."""
        date_str = (self._start_time or datetime.now()).strftime("%Y-%m-%d_%H-%M")
        filename = f"lecture_w{self.lecture_week}_{date_str}.txt"
        path = self.transcripts_dir / filename

        with self._lock:
            lines = [
                f"[{ts.strftime('%H:%M:%S')}] {text}"
                for ts, text in self._segments
            ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return path
