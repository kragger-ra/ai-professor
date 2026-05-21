"""Single-student profile — stable identity that survives restarts.

PHASE 6 — the setup is local and single-user, so there is exactly ONE
profile (data/student_profile.json). It holds WHO the student is — name and
background — captured from their introduction. WHAT was discussed lives
separately in SessionMemory; the two together are the persistent state of
the one student, and reset_memory.bat clears both.

Never crashes the tutor: a missing or corrupt file degrades to an empty
profile.
"""
from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from pathlib import Path

from tutor.util import log

_COMPONENT = "profile"

# tutor/brain/profile.py -> parents[0]=brain, [1]=tutor, [2]=repo_root
_REPO_ROOT: Path = Path(__file__).resolve().parents[2]
_PROFILE_PATH: Path = _REPO_ROOT / "data" / "student_profile.json"


@dataclass
class StudentProfile:
    """Persistent identity of the one local student."""

    name: str = ""
    background: str = ""
    first_seen: str = ""
    updated: str = ""
    path: Path = field(default=_PROFILE_PATH)

    def __post_init__(self) -> None:
        self.load()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load(self) -> None:
        """Read the JSON if present. Never crash on a missing or corrupt file."""
        try:
            if not self.path.is_file():
                log(_COMPONENT, "no prior student profile on disk")
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.name = str(data.get("name", "") or "")
            self.background = str(data.get("background", "") or "")
            self.first_seen = str(data.get("first_seen", "") or "")
            self.updated = str(data.get("updated", "") or "")
            log(_COMPONENT, f"loaded profile: name={self.name!r}")
        except Exception as exc:
            log(_COMPONENT, f"could not load profile: "
                            f"{type(exc).__name__}: {exc}")
            self.name = ""
            self.background = ""
            self.first_seen = ""
            self.updated = ""

    def save(self) -> None:
        """Write the JSON to disk (utf-8). Never crash on an I/O error."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "name": self.name,
                "background": self.background,
                "first_seen": self.first_seen,
                "updated": self.updated,
            }
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            log(_COMPONENT, f"saved profile (name={self.name!r})")
        except Exception as exc:
            log(_COMPONENT, f"could not save profile: "
                            f"{type(exc).__name__}: {exc}")

    # ------------------------------------------------------------------
    # Updates
    # ------------------------------------------------------------------

    def note_intro(self, name: str = "", background: str = "") -> bool:
        """Record name / background from the student's introduction.

        Returns True if anything new was learned. An existing value is never
        overwritten with an empty one.
        """
        changed = False
        if name and name != self.name:
            self.name = name
            changed = True
        if background and background != self.background:
            self.background = background
            changed = True
        if changed:
            now = datetime.datetime.now().isoformat(timespec="seconds")
            if not self.first_seen:
                self.first_seen = now
            self.updated = now
        return changed

    # ------------------------------------------------------------------
    # Prompt section
    # ------------------------------------------------------------------

    def as_prompt_section(self) -> str:
        """Profile text for the system prompt. Empty if nothing is known."""
        parts: list[str] = []
        if self.name:
            parts.append(f"Имя студента: {self.name}.")
        if self.background:
            parts.append(f"О студенте: {self.background}.")
        return " ".join(parts)
