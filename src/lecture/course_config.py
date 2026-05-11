"""Course configuration: lets the agent adapt to any subject (universal teacher).

The agent runs in a forked process; module-level singletons are not visible to
the child. State is persisted to `data/current_course.json` and reloaded lazily
on mtime change in every reader.

A RAG package can ship a `course_config.yml` next to its .md/.txt files; when
the student voice-loads it, `RagModel.reload_from_path` calls
`apply_from_yaml(...)` which persists the new course settings to JSON.
"""

import json
import os
import threading
import time
from typing import Optional

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None  # CLI utility and prompt_constructor will guard against this

# Tutor build defaults — generic, course is loaded per-session by the student.
DEFAULTS = {
    "name": "General course",
    "topic": "общие знания",
    "short_name": "Course",
    "teaching_style": "дружелюбно",
    "audience": "студент",
    "example_keywords": [],
}

# Where to persist the current course between processes.
_STATE_PATH = os.path.join("data", "current_course.json")
# Reader-side TTL: re-stat the file at most once per second.
_RELOAD_INTERVAL_S = 1.0

_cache_lock = threading.Lock()
_cached_cfg: Optional["CourseConfig"] = None
_cached_mtime: float = 0.0
_cached_at: float = 0.0


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


def set_current(cfg: CourseConfig) -> None:
    """Persist the active course config to data/current_course.json."""
    os.makedirs(os.path.dirname(_STATE_PATH) or ".", exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
    # Invalidate this process's cache so the next get_current() picks up the write.
    global _cached_at
    with _cache_lock:
        _cached_at = 0.0


def get_current() -> CourseConfig:
    """Return the active CourseConfig, reloading from disk if the file changed.

    Cross-process safe: every reader process re-stats current_course.json with
    a short TTL and rereads only when mtime advances.
    """
    global _cached_cfg, _cached_mtime, _cached_at
    now = time.monotonic()
    with _cache_lock:
        if _cached_cfg is not None and (now - _cached_at) < _RELOAD_INTERVAL_S:
            return _cached_cfg
        try:
            st = os.stat(_STATE_PATH)
        except OSError:
            _cached_at = now
            if _cached_cfg is None:
                _cached_cfg = CourseConfig()
            return _cached_cfg
        if _cached_cfg is not None and st.st_mtime == _cached_mtime:
            _cached_at = now
            return _cached_cfg
        try:
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            data = {}
        _cached_cfg = CourseConfig(**(data if isinstance(data, dict) else {}))
        _cached_mtime = st.st_mtime
        _cached_at = now
        return _cached_cfg


def render_current(template: str) -> str:
    """Convenience: render `template` with the currently-active course config."""
    return get_current().render(template)
