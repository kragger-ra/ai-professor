"""Cross-session memory — a brief thesis-level summary that survives restarts.

PHASE 6 — the professor must remember, ACROSS RESTARTS, what was discussed
with the student so it can reference earlier sessions ("в прошлый раз мы
разбирали...").

State lives in data/session_memory.json:
  summary  — a short thesis-level summary (3-6 sentences, Russian) of the
             topics covered and the student's progress / difficulties
  sessions — how many sessions have contributed to the summary
  updated  — ISO timestamp of the last refresh

Design rules:
  * NEVER crash the tutor. A missing file, corrupt JSON, or a failed LLM
    call all degrade gracefully — the old (or empty) summary is kept.
  * One LLM call per refresh: the prior summary is MERGED with the new
    session's topics into an updated short summary.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

from tutor.brain.llm import stream_response_sentences
from tutor.util import log

_COMPONENT = "memory"

# tutor/brain/session_memory.py -> parents[0]=brain, [1]=tutor, [2]=repo_root
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_MEMORY_PATH: Path = _REPO_ROOT / "data" / "session_memory.json"

# Budget for the merge call — the summary is short by contract.
_REFRESH_MAX_TOKENS = 400

# Prompt that merges the prior summary with the new session into a fresh one.
_MERGE_PROMPT = """Ты ведёшь краткий конспект занятий ИИ-профессора со студентом.

Предыдущий конспект прошлых занятий:
{prior}

Реплики последней сессии (студент и профессор):
{transcript}

Составь ОБНОВЛЁННЫЙ краткий конспект на русском языке: 3-6 предложений на уровне тезисов. Кратко перечисли темы, которые разбирались (включая прошлые), и отметь, что давалось студенту тяжело, а что — легко. Не пересказывай реплики дословно, только суть. Без маркеров списков, без вступлений — только сам конспект."""

_NO_PRIOR = "(прошлых занятий не было)"


@dataclass
class SessionMemory:
    """Persistent, thesis-level memory of past tutoring sessions."""

    summary: str = ""
    sessions: int = 0
    updated: str = ""
    path: Path = field(default=_MEMORY_PATH)

    def __post_init__(self) -> None:
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Read the JSON if present. Never crash on a missing or corrupt file."""
        try:
            if not self.path.is_file():
                log(_COMPONENT, "no prior session memory on disk")
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.summary = str(data.get("summary", "") or "")
            self.sessions = int(data.get("sessions", 0) or 0)
            self.updated = str(data.get("updated", "") or "")
            log(_COMPONENT,
                f"loaded session memory: {self.sessions} session(s), "
                f"{len(self.summary)} chars")
        except Exception as exc:
            # Corrupt or unreadable file — start clean, do not crash.
            log(_COMPONENT, f"could not load session memory: "
                            f"{type(exc).__name__}: {exc}")
            self.summary = ""
            self.sessions = 0
            self.updated = ""

    def save(self) -> None:
        """Write the JSON to disk (utf-8). Never crash on an I/O error."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "summary": self.summary,
                "sessions": self.sessions,
                "updated": self.updated,
            }
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log(_COMPONENT, f"saved session memory ({len(self.summary)} chars)")
        except Exception as exc:
            log(_COMPONENT, f"could not save session memory: "
                            f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # Refresh — merge the new session into the running summary
    # ------------------------------------------------------------------

    def refresh(self, history: list[dict]) -> None:
        """Merge the prior summary with this session's topics via ONE LLM call.

        `history` is the agent's conversation history: user turns are
        {"role","content"}, assistant turns are {"role","answer"} where
        answer.sentences is a list. On ANY error the old summary is kept.
        """
        transcript = self._render_transcript(history)
        if not transcript:
            log(_COMPONENT, "nothing to summarise — keeping prior summary")
            return
        prompt = _MERGE_PROMPT.format(
            prior=self.summary or _NO_PRIOR,
            transcript=transcript,
        )
        messages = [{"role": "user", "content": prompt}]
        try:
            sentences = list(stream_response_sentences(
                messages, max_tokens=_REFRESH_MAX_TOKENS
            ))
            new_summary = " ".join(s.strip() for s in sentences if s.strip()).strip()
        except Exception as exc:
            log(_COMPONENT, f"refresh LLM call failed — keeping prior summary: "
                            f"{type(exc).__name__}: {exc}")
            return
        if not new_summary:
            log(_COMPONENT, "refresh produced empty summary — keeping prior")
            return
        self.summary = new_summary
        self.sessions += 1
        self.updated = datetime.datetime.now().isoformat(timespec="seconds")
        log(_COMPONENT,
            f"summary refreshed (session #{self.sessions}, "
            f"{len(self.summary)} chars)")

    @staticmethod
    def _render_transcript(history: list[dict]) -> str:
        """Flatten the agent history into a plain student/professor transcript.

        Mirrors AgentThread._turn_text: user turns carry "content", assistant
        turns carry "answer" whose .sentences is a list.
        """
        lines: list[str] = []
        for h in history:
            role = h.get("role", "")
            if "content" in h:
                text = str(h.get("content", "")).strip()
                speaker = "Студент"
            else:
                ans = h.get("answer")
                sentences = getattr(ans, "sentences", None) if ans else None
                text = " ".join(sentences).strip() if sentences else ""
                speaker = "Профессор"
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Prompt section
    # ------------------------------------------------------------------

    def as_prompt_section(self) -> str:
        """The summary, ready to drop into the system prompt. Empty if none."""
        return self.summary.strip()
