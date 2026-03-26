"""
Integration bridge between lecture modules and the NetTyan pipeline.

Wires WakeWordDetector, TranscriptBuffer, LectureSummarizer, and
MetricsLogger into a single facade consumed by main.py and CoreAgent.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from data_schema.ctx_structures import CtxSwarmType
from lecture.summarizer import LectureSummarizer
from lecture.transcript_buffer import TranscriptBuffer
from lecture.wake_word import WakeWordConfig, WakeWordDetector
from metrics.logger import MetricsLogger

logger = logging.getLogger(__name__)


class LectureManager:
    """Manages wake word detection, transcript buffering, and metrics."""

    def __init__(self, ctx_swarm: CtxSwarmType):
        self.ctx_swarm = ctx_swarm

        lecture_week = int(os.getenv("LECTURE_WEEK", "1"))
        transcripts_dir = os.getenv("TRANSCRIPTS_DIR", "data/transcripts")
        summaries_dir = os.getenv("SUMMARIES_DIR", "resources/RAG/lecture_summaries")
        db_path = os.getenv("METRICS_DB_PATH", "data/metrics.db")
        ww_config_path = os.getenv(
            "WAKE_WORDS_CONFIG", "resources/Customization/wake_words.yml"
        )

        self.lecture_week = lecture_week

        ww_config = WakeWordConfig.from_yaml(Path(ww_config_path))
        self.wake_detector = WakeWordDetector(config=ww_config)

        self.transcript_buffer = TranscriptBuffer(
            lecture_week=lecture_week,
            transcripts_dir=Path(transcripts_dir),
        )

        self.summarizer = LectureSummarizer(summaries_dir=Path(summaries_dir))
        self.metrics = MetricsLogger(db_path=Path(db_path))

        self._last_summary: str = ""

        logger.info(
            "LectureManager initialized (week=%d, db=%s)", lecture_week, db_path
        )

    # ------------------------------------------------------------------
    # STT integration
    # ------------------------------------------------------------------

    def process_stt_segment(self, text: str) -> Optional[str]:
        """Called from STT process on each recognized segment.

        1. Feeds segment to TranscriptBuffer (if recording)
        2. Runs through WakeWordDetector
        3. Returns extracted student query when ready, else None
        """
        # 1. Buffer the raw transcript
        self.transcript_buffer.add_segment(text)

        # 2. Wake word detection
        result = self.wake_detector.process_segment(text)
        if result.triggered and result.extracted_query:
            logger.info("Student query extracted: %s", result.extracted_query[:80])
            return result.extracted_query

        return None

    # ------------------------------------------------------------------
    # Lecture lifecycle
    # ------------------------------------------------------------------

    def start_lecture(self) -> str:
        """Start transcript recording."""
        self.transcript_buffer.start()
        self.wake_detector.reset()
        return f"Recording started (week {self.lecture_week})"

    def stop_lecture(self) -> str:
        """Stop recording, run summarization, log to metrics, return summary."""
        if not self.transcript_buffer.is_active:
            return self._last_summary or "No active recording."

        transcript_path = self.transcript_buffer.stop()
        full_text = self.transcript_buffer.get_full_text()

        if not full_text.strip():
            return "Transcript is empty — nothing to summarize."

        chunks = self.transcript_buffer.get_chunks()
        logger.info("Summarizing %d chunks...", len(chunks))

        summary = self.summarizer.summarize(
            chunks=chunks,
            lecture_week=self.lecture_week,
        )

        # Log to metrics DB
        self.metrics.log_lecture_summary(
            lecture_week=self.lecture_week,
            summary=summary,
            transcript_length=len(full_text),
        )

        self._last_summary = summary
        return summary

    @property
    def last_summary(self) -> str:
        return self._last_summary

    @property
    def segment_count(self) -> int:
        return self.transcript_buffer.segment_count

    @property
    def is_recording(self) -> bool:
        return self.transcript_buffer.is_active

    # ------------------------------------------------------------------
    # Metrics proxy
    # ------------------------------------------------------------------

    def log_interaction(
        self,
        query: str,
        response: str,
        response_time_ms: int,
        rag_sources: Optional[list[str]] = None,
        emotion: str = "neutral",
    ) -> int:
        """Proxy to MetricsLogger.log_interaction."""
        return self.metrics.log_interaction(
            student_query=query,
            agent_response=response,
            response_time_ms=response_time_ms,
            lecture_week=self.lecture_week,
            rag_sources=rag_sources,
            emotion=emotion,
        )
