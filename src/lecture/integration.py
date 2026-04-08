"""
Integration bridge between lecture modules and the NetTyan pipeline.

Wires WakeWordDetector, TranscriptBuffer, LectureSummarizer, and
MetricsLogger into a single facade consumed by main.py and CoreAgent.

Inter-process communication:
  STT process writes JSONL → data/lecture_notes/_live_stream.jsonl
  LectureManager (main process) reads it via a background watcher thread.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional

from data_schema.ctx_structures import CtxSwarmType
from lecture.summarizer import LectureSummarizer
from lecture.transcript_buffer import TranscriptBuffer
from lecture.wake_word import WakeWordConfig, WakeWordDetector
from metrics.logger import MetricsLogger

logger = logging.getLogger(__name__)

_LIVE_TRANSCRIPT_LOG = os.path.join("data", "lecture_notes", "_live_stream.jsonl")
_LIVE_NOTES_DIR = os.path.join("data", "lecture_notes")
_WATCHER_POLL_SEC = 10
_SUMMARIZE_THRESHOLD = 20  # summarize after this many buffered lines


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
        self._recording = False
        self._current_notes: list[str] = []
        self._start_time: str = ""
        self._watcher_thread: Optional[threading.Thread] = None

        os.makedirs(_LIVE_NOTES_DIR, exist_ok=True)

        logger.info(
            "LectureManager initialized (week=%d, db=%s)", lecture_week, db_path
        )

    # ------------------------------------------------------------------
    # STT integration (direct, for in-process use)
    # ------------------------------------------------------------------

    def process_stt_segment(self, text: str) -> Optional[str]:
        """Called from STT process on each recognized segment.

        1. Feeds segment to TranscriptBuffer (if recording)
        2. Runs through WakeWordDetector
        3. Returns extracted student query when ready, else None
        """
        self.transcript_buffer.add_segment(text)

        result = self.wake_detector.process_segment(text)
        if result.triggered and result.extracted_query:
            logger.info("Student query extracted: %s", result.extracted_query[:80])
            return result.extracted_query

        return None

    # ------------------------------------------------------------------
    # Live transcript watcher (reads JSONL written by STT process)
    # ------------------------------------------------------------------

    def _live_transcript_watcher(self) -> None:
        """Background thread: reads _live_stream.jsonl, feeds TranscriptBuffer,
        and triggers periodic chunk summarization."""
        last_position = 0
        buffer_lines: list[dict] = []

        while self._recording:
            time.sleep(_WATCHER_POLL_SEC)

            # Read new lines from JSONL
            try:
                if not os.path.exists(_LIVE_TRANSCRIPT_LOG):
                    continue
                with open(_LIVE_TRANSCRIPT_LOG, "r", encoding="utf-8") as f:
                    f.seek(last_position)
                    new_lines = f.readlines()
                    last_position = f.tell()

                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                        buffer_lines.append(entry)
                        self.transcript_buffer.add_segment(entry.get("text", ""))
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                print(f"[LECTURE] Watcher read error: {e}")

            # Periodic summarization when enough lines accumulated
            if len(buffer_lines) >= _SUMMARIZE_THRESHOLD:
                chunk_text = "\n".join(
                    f"[{e.get('time', '')}] {e.get('speaker', '')}: {e.get('text', '')}"
                    for e in buffer_lines
                )
                buffer_lines.clear()

                try:
                    partial = self.summarizer.summarize_chunks([chunk_text])
                    if partial:
                        summary_text = partial[0]
                        self._current_notes.append(summary_text)
                        # Append to live notes file
                        notes_file = os.path.join(
                            _LIVE_NOTES_DIR,
                            f"lecture_live_{self._start_time}.md",
                        )
                        with open(notes_file, "a", encoding="utf-8") as f:
                            f.write(
                                f"\n### {time.strftime('%H:%M')}\n{summary_text}\n"
                            )
                        print(f"[LECTURE] Chunk summarized: {len(summary_text)} chars")
                except Exception as e:
                    print(f"[LECTURE] Summarization error: {e}")

    # ------------------------------------------------------------------
    # Lecture lifecycle
    # ------------------------------------------------------------------

    def start_lecture(self) -> str:
        """Start transcript recording and live watcher."""
        self._recording = True
        self._current_notes = []
        self._start_time = time.strftime("%Y%m%d_%H%M")

        self.transcript_buffer.start()
        self.wake_detector.reset()

        # Clear old live log so watcher starts fresh
        if os.path.exists(_LIVE_TRANSCRIPT_LOG):
            open(_LIVE_TRANSCRIPT_LOG, "w").close()

        # Start watcher thread
        self._watcher_thread = threading.Thread(
            target=self._live_transcript_watcher, daemon=True
        )
        self._watcher_thread.start()

        return f"Recording started (week {self.lecture_week})"

    def stop_lecture(self) -> str:
        """Stop recording, run final summarization, save to RAG, return summary."""
        self._recording = False

        if not self.transcript_buffer.is_active:
            return self._last_summary or "No active recording."

        transcript_path = self.transcript_buffer.stop()
        full_text = self.transcript_buffer.get_full_text()

        # Build final summary from accumulated notes or full transcript
        if self._current_notes:
            # Merge periodic summaries into one final summary
            final_summary = self.summarizer.merge_summaries(
                self._current_notes,
                lecture_week=self.lecture_week,
            )
        elif full_text.strip():
            chunks = self.transcript_buffer.get_chunks()
            final_summary = self.summarizer.summarize(
                chunks=chunks,
                lecture_week=self.lecture_week,
            )
        else:
            return "Transcript is empty — nothing to summarize."

        # Log to metrics DB
        self.metrics.log_lecture_summary(
            lecture_week=self.lecture_week,
            summary=final_summary,
            transcript_length=len(full_text),
        )

        # Save to RAG directory for indexing
        rag_path = os.path.join(
            "resources", "RAG", "course_materials",
            f"lecture_w{self.lecture_week}_{self._start_time}.md",
        )
        os.makedirs(os.path.dirname(rag_path), exist_ok=True)
        with open(rag_path, "w", encoding="utf-8") as f:
            f.write(
                f"# Конспект лекции — Неделя {self.lecture_week}\n\n"
                f"{final_summary}"
            )
        print(f"[LECTURE] Saved to RAG: {rag_path}")

        self._last_summary = final_summary
        return final_summary

    def get_current_summary(self) -> str:
        """Current lecture notes for answering 'what's this lecture about?'."""
        if not self._current_notes:
            return "Пока ничего существенного не обсуждалось."
        return "\n\n".join(self._current_notes)

    @property
    def last_summary(self) -> str:
        return self._last_summary

    @property
    def segment_count(self) -> int:
        return self.transcript_buffer.segment_count

    @property
    def is_recording(self) -> bool:
        return self._recording

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
