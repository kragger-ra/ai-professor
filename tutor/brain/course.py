"""Course configuration: lets the agent adapt to any subject (universal teacher).

Single-process build: state is persisted to data/current_course.json and
cached in-process. get_current() reads the file once and returns the cached
CourseConfig until set_current() invalidates it.

A RAG package can ship a course_config.yml next to its .md/.txt files; when
the student voice-loads it, apply_from_yaml(...) persists the new course
settings to JSON.
"""

import json
import os
from pathlib import Path
from typing import Optional

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # apply_from_yaml will guard against this

# Tutor build defaults — generic, course is loaded per-session by the student.
DEFAULTS = {
    "name": "General course",
    "topic": "общие знания",
    "short_name": "Course",
    "teaching_style": "дружелюбно",
    "audience": "студент",
    "example_keywords": [],
}

# Where to persist the current course. Absolute path anchored at repo root.
_STATE_PATH = Path(__file__).resolve().parents[2] / "data" / "current_course.json"

# Single-process lazy cache: None means "not loaded yet".
_cached_cfg: Optional["CourseConfig"] = None


def set_default(defaults: dict) -> None:
    """Override module-level defaults (called by Lecture build to set PersonaLab)."""
    DEFAULTS.update(defaults)


class CourseConfig:
    """Holds course fields and renders {COURSE_*} placeholders in prompt strings."""

    def __init__(self, **fields):
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in fields.items() if v is not None})
        self.fields = merged

    def render(self, template: str) -> str:
        """Substitute {COURSE_<FIELD>} placeholders. Unknown fields are left intact."""
        if not template:
            return template
        out = template
        for k, v in self.fields.items():
            placeholder = "{COURSE_" + k.upper() + "}"
            if placeholder in out:
                out = out.replace(placeholder, str(v))
        return out

    def to_dict(self) -> dict:
        return dict(self.fields)


def apply_from_yaml(yaml_path: str) -> "CourseConfig":
    """Read a course_config.yml file (top-level keys or nested 'course'/'persona')."""
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot read course_config.yml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    fields = {}
    # Flat layout: just merge known keys.
    for k in DEFAULTS.keys():
        if k in data:
            fields[k] = data[k]
    # Nested layout (course: {...}, persona: {...}) — merge both blocks.
    for block_name in ("course", "persona"):
        block = data.get(block_name) or {}
        if isinstance(block, dict):
            for k, v in block.items():
                if k in DEFAULTS:
                    fields[k] = v
    cfg = CourseConfig(**fields)
    set_current(cfg)
    return cfg


def set_current(cfg: "CourseConfig") -> None:
    """Persist the active course config to data/current_course.json."""
    global _cached_cfg
    os.makedirs(str(_STATE_PATH.parent), exist_ok=True)
    with open(str(_STATE_PATH), "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
    # Invalidate cache so the next get_current() re-reads from disk.
    _cached_cfg = None


def set_current_path(path: str) -> None:
    """Stamp the active course's package path into the persisted state file.

    Course YAML doesn't carry the package path; the board UI needs it to
    highlight the active course in its manager list. Called by the load
    handlers after a successful rag.reload_from_path.
    """
    try:
        if _STATE_PATH.exists():
            with open(str(_STATE_PATH), "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        else:
            data = {}
        data["path"] = str(path)
        os.makedirs(str(_STATE_PATH.parent), exist_ok=True)
        with open(str(_STATE_PATH), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_current() -> "CourseConfig":
    """Return the active CourseConfig.

    Lazily reads current_course.json once on first call; returns the cached
    instance on subsequent calls. Cache is invalidated only by set_current().
    """
    global _cached_cfg
    if _cached_cfg is not None:
        return _cached_cfg
    try:
        with open(str(_STATE_PATH), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        data = {}
    _cached_cfg = CourseConfig(**(data if isinstance(data, dict) else {}))
    return _cached_cfg


def render_current(template: str) -> str:
    """Convenience: render `template` with the currently-active course config."""
    return get_current().render(template)
