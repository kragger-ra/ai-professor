"""Student profile management for adaptive conversation."""

import json
import os
import sqlite3
from datetime import datetime

from data_schema.structure_templates import REPO_DATA_PATH

DB_PATH = os.path.join(REPO_DATA_PATH, "student_profiles.db")


class StudentProfileManager:
    def __init__(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS students (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                total_interactions INTEGER DEFAULT 0,
                tech_level INTEGER DEFAULT 3,
                communication_style TEXT DEFAULT 'unknown',
                topics_of_interest TEXT DEFAULT '[]',
                known_issues TEXT DEFAULT '[]',
                personality_notes TEXT DEFAULT '',
                background TEXT DEFAULT '',
                topic_levels TEXT DEFAULT '{}'
            )
        """)
        # Migration: add topic_levels column if missing
        try:
            self.conn.execute("ALTER TABLE students ADD COLUMN topic_levels TEXT DEFAULT '{}'")
            self.conn.commit()
        except Exception:
            pass  # column already exists

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS interaction_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                student_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                student_message TEXT,
                agent_response TEXT,
                meta_analysis TEXT,
                emotion_tag TEXT
            )
        """)
        self.conn.commit()

    def has_any_student(self) -> bool:
        """True if at least one student profile exists. Used by startup greeting."""
        row = self.conn.execute("SELECT 1 FROM students LIMIT 1").fetchone()
        return row is not None

    def get_or_create_student(self, name: str) -> dict:
        row = self.conn.execute(
            "SELECT * FROM students WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        if row:
            self.conn.execute(
                "UPDATE students SET last_seen = ?, total_interactions = total_interactions + 1 WHERE name = ?",
                (datetime.now().isoformat(), row["name"]),
            )
            self.conn.commit()
            return dict(row)
        now = datetime.now().isoformat()
        self.conn.execute(
            "INSERT INTO students (name, first_seen, last_seen, total_interactions) VALUES (?, ?, ?, 1)",
            (name, now, now),
        )
        self.conn.commit()
        return dict(
            self.conn.execute(
                "SELECT * FROM students WHERE LOWER(name) = LOWER(?)", (name,)
            ).fetchone()
        )

    def update_profile(self, name: str, updates: dict):
        allowed = {
            "tech_level", "communication_style", "topics_of_interest",
            "known_issues", "personality_notes", "background", "topic_levels",
        }
        sets, vals = [], []
        for k, v in updates.items():
            if k in allowed:
                sets.append(f"{k} = ?")
                vals.append(json.dumps(v, ensure_ascii=False) if isinstance(v, (list, dict)) else str(v))
        if sets:
            vals.append(name)
            self.conn.execute(
                f"UPDATE students SET {', '.join(sets)} WHERE LOWER(name) = LOWER(?)",
                vals,
            )
            self.conn.commit()

    def append_to_list_field(self, name: str, field: str, value: str):
        """Append a value to a JSON list field (topics_of_interest, known_issues)."""
        row = self.conn.execute(
            "SELECT * FROM students WHERE LOWER(name) = LOWER(?)", (name,)
        ).fetchone()
        if not row:
            return
        current = json.loads(row[field]) if row[field] else []
        if value and value not in current:
            current.append(value)
            self.update_profile(name, {field: current})

    def log_interaction(self, student_name: str, student_msg: str,
                        agent_response: str, meta_analysis: str = "",
                        emotion: str = "neutral"):
        self.conn.execute(
            "INSERT INTO interaction_log (student_name, timestamp, student_message, "
            "agent_response, meta_analysis, emotion_tag) VALUES (?, ?, ?, ?, ?, ?)",
            (student_name, datetime.now().isoformat(), student_msg,
             agent_response, meta_analysis, emotion),
        )
        self.conn.commit()

    def get_topic_level(self, name: str, topic: str) -> int:
        """Get student level for a specific topic."""
        student = self.get_or_create_student(name)
        levels = json.loads(student.get("topic_levels") or "{}")
        return levels.get(topic.lower(), student.get("tech_level", 3))

    def update_topic_level(self, name: str, topic: str, delta: int):
        """Shift student level for a specific topic."""
        student = self.get_or_create_student(name)
        levels = json.loads(student.get("topic_levels") or "{}")
        current = levels.get(topic.lower(), student.get("tech_level", 3))
        levels[topic.lower()] = max(1, min(5, current + delta))
        self.conn.execute(
            "UPDATE students SET topic_levels = ? WHERE LOWER(name) = LOWER(?)",
            (json.dumps(levels, ensure_ascii=False), name),
        )
        self.conn.commit()

    def get_profile_for_prompt(self, name: str) -> str:
        student = self.get_or_create_student(name)
        if student["total_interactions"] <= 1:
            return f"Новый студент: {name}. Первое общение."

        parts = [f"Студент: {name}"]
        parts.append(f"Общений: {student['total_interactions']}")

        levels = {1: "начинающий", 2: "базовый", 3: "средний", 4: "продвинутый", 5: "эксперт"}
        if student["tech_level"] != 3:
            parts.append(f"Уровень: {levels.get(student['tech_level'], 'средний')}")
        if student["background"]:
            parts.append(f"Бэкграунд: {student['background']}")
        if student["communication_style"] != "unknown":
            parts.append(f"Стиль: {student['communication_style']}")
        if student["known_issues"] != "[]":
            issues = json.loads(student["known_issues"]) if isinstance(student["known_issues"], str) else []
            if issues:
                parts.append(f"Затруднения: {', '.join(issues[:3])}")
        if student["topics_of_interest"] != "[]":
            topics = json.loads(student["topics_of_interest"]) if isinstance(student["topics_of_interest"], str) else []
            if topics:
                parts.append(f"Интересы: {', '.join(topics[:5])}")
        if student["personality_notes"]:
            parts.append(f"Заметки: {student['personality_notes']}")
        topic_levels_raw = student.get("topic_levels") or "{}"
        topic_levels = json.loads(topic_levels_raw) if isinstance(topic_levels_raw, str) else {}
        if topic_levels:
            level_names = {1: "начинающий", 2: "базовый", 3: "средний", 4: "продвинутый", 5: "эксперт"}
            tl_parts = [f"{t}: {level_names.get(v, 'средний')}" for t, v in topic_levels.items()]
            parts.append(f"Уровни по темам: {', '.join(tl_parts)}")
        return ". ".join(parts)
