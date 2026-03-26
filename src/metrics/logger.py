"""
SQLite metrics logger for VKR validation.

Logs all agent interactions, lecture summaries, and system performance
metrics to a local SQLite database.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/metrics.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS interactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    lecture_week INTEGER,
    student_query TEXT,
    agent_response TEXT,
    response_time_ms INTEGER,
    rag_sources TEXT,
    emotion TEXT,
    was_helpful INTEGER
);

CREATE TABLE IF NOT EXISTS lecture_summaries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    lecture_week INTEGER,
    date DATE,
    transcript_length INTEGER,
    summary TEXT,
    topics_covered TEXT
);

CREATE TABLE IF NOT EXISTS system_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    stt_latency_ms INTEGER,
    llm_latency_ms INTEGER,
    tts_latency_ms INTEGER,
    gpu_util_percent REAL,
    ram_usage_mb REAL
);
"""


class MetricsLogger:
    """
    Thread-safe SQLite logger.

    All write methods are safe to call from any thread.
    The database and tables are created automatically on first use.
    """

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn") or self._local.conn is None:
            self._local.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._local.conn.row_factory = sqlite3.Row
        return self._local.conn

    @contextmanager
    def _cursor(self):
        conn = self._get_conn()
        cur = conn.cursor()
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    def _init_db(self) -> None:
        with self._cursor() as cur:
            cur.executescript(_SCHEMA)
        logger.info("Metrics DB initialized at %s", self.db_path)

    # ------------------------------------------------------------------
    # Interactions
    # ------------------------------------------------------------------

    def log_interaction(
        self,
        student_query: str,
        agent_response: str,
        response_time_ms: int,
        lecture_week: int = 1,
        rag_sources: Optional[list[str]] = None,
        emotion: str = "neutral",
    ) -> int:
        """Log a student-agent interaction. Returns the row ID."""
        sources_json = json.dumps(rag_sources or [], ensure_ascii=False)
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO interactions
                    (lecture_week, student_query, agent_response,
                     response_time_ms, rag_sources, emotion)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (lecture_week, student_query, agent_response,
                 response_time_ms, sources_json, emotion),
            )
            return cur.lastrowid

    def mark_helpful(self, interaction_id: int, helpful: bool) -> None:
        """Mark an interaction as helpful or not (student feedback)."""
        with self._cursor() as cur:
            cur.execute(
                "UPDATE interactions SET was_helpful = ? WHERE id = ?",
                (1 if helpful else 0, interaction_id),
            )

    # ------------------------------------------------------------------
    # Lecture summaries
    # ------------------------------------------------------------------

    def log_lecture_summary(
        self,
        lecture_week: int,
        summary: str,
        transcript_length: int,
        topics_covered: Optional[list[str]] = None,
        lecture_date: Optional[date] = None,
    ) -> int:
        """Log a lecture summary. Returns the row ID."""
        lecture_date = lecture_date or date.today()
        topics_json = json.dumps(topics_covered or [], ensure_ascii=False)
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO lecture_summaries
                    (lecture_week, date, transcript_length, summary, topics_covered)
                VALUES (?, ?, ?, ?, ?)
                """,
                (lecture_week, lecture_date.isoformat(), transcript_length,
                 summary, topics_json),
            )
            return cur.lastrowid

    # ------------------------------------------------------------------
    # System metrics
    # ------------------------------------------------------------------

    def log_system_metrics(
        self,
        stt_latency_ms: int = 0,
        llm_latency_ms: int = 0,
        tts_latency_ms: int = 0,
        gpu_util_percent: float = 0.0,
        ram_usage_mb: float = 0.0,
    ) -> int:
        """Log a system performance snapshot. Returns the row ID."""
        with self._cursor() as cur:
            cur.execute(
                """
                INSERT INTO system_metrics
                    (stt_latency_ms, llm_latency_ms, tts_latency_ms,
                     gpu_util_percent, ram_usage_mb)
                VALUES (?, ?, ?, ?, ?)
                """,
                (stt_latency_ms, llm_latency_ms, tts_latency_ms,
                 gpu_util_percent, ram_usage_mb),
            )
            return cur.lastrowid

    # ------------------------------------------------------------------
    # Queries (for Gradio dashboard)
    # ------------------------------------------------------------------

    def get_interaction_count(self, lecture_week: Optional[int] = None) -> int:
        with self._cursor() as cur:
            if lecture_week is not None:
                cur.execute(
                    "SELECT COUNT(*) FROM interactions WHERE lecture_week = ?",
                    (lecture_week,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM interactions")
            return cur.fetchone()[0]

    def get_avg_response_time(self, lecture_week: Optional[int] = None) -> float:
        with self._cursor() as cur:
            if lecture_week is not None:
                cur.execute(
                    "SELECT AVG(response_time_ms) FROM interactions WHERE lecture_week = ?",
                    (lecture_week,),
                )
            else:
                cur.execute("SELECT AVG(response_time_ms) FROM interactions")
            result = cur.fetchone()[0]
            return result or 0.0

    def get_weekly_stats(self) -> list[dict]:
        """Get per-week aggregated stats for the dashboard."""
        with self._cursor() as cur:
            cur.execute("""
                SELECT
                    lecture_week,
                    COUNT(*) as total_questions,
                    AVG(response_time_ms) as avg_response_ms,
                    SUM(CASE WHEN was_helpful = 1 THEN 1 ELSE 0 END) as helpful_count,
                    SUM(CASE WHEN was_helpful = 0 THEN 1 ELSE 0 END) as not_helpful_count
                FROM interactions
                GROUP BY lecture_week
                ORDER BY lecture_week
            """)
            return [dict(row) for row in cur.fetchall()]

    def get_recent_interactions(self, limit: int = 20) -> list[dict]:
        with self._cursor() as cur:
            cur.execute(
                "SELECT * FROM interactions ORDER BY id DESC LIMIT ?",
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]

    def close(self) -> None:
        if hasattr(self._local, "conn") and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
