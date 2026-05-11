"""Course configuration for the Lecture build (audience mode).

Same shape as Tutor's course_config — but defaults preserve PersonaLab
Workshop so existing lectures keep working without an explicit course_config.yml.

Tutor's voice-loaded RAG packages typically replace these defaults at runtime
by writing to `data/current_course.json` (see Tutor build for the writer flow).
For the Lecture build the defaults stay PersonaLab because the audience scenario
ships with PersonaLab materials in resources/RAG/course_materials/.
"""

import json
import os
import threading
import time
from typing import Optional

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None

# Lecture build defaults — PersonaLab Workshop, the original course.
DEFAULTS = {
    "name": "PersonaLab Workshop",
    "topic": "цифровых персонажей",
    "short_name": "PersonaLab",
    "teaching_style": "дружелюбно",
    "audience": "аудитория",
    "example_keywords": ["NetTyan"],
}

_STATE_PATH = os.path.join("data", "current_course.json")
_RELOAD_INTERVAL_S = 1.0

_cache_lock = threading.Lock()
_cached_cfg: Optional["CourseConfig"] = None
_cached_mtime: float = 0.0
_cached_at: float = 0.0


def set_default(defaults: dict) -> None:
    DEFAULTS.update(defaults)


class CourseConfig:
    def __init__(self, **fields):
        merged = dict(DEFAULTS)
        merged.update({k: v for k, v in fields.items() if v is not None})
        self.fields = merged

    def render(self, template: str) -> str:
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
    if yaml is None:
        raise RuntimeError("PyYAML not installed; cannot read course_config.yml")
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    fields = {}
    for k in DEFAULTS.keys():
        if k in data:
            fields[k] = data[k]
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
    os.makedirs(os.path.dirname(_STATE_PATH) or ".", exist_ok=True)
    with open(_STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg.to_dict(), f, ensure_ascii=False, indent=2)
    global _cached_at
    with _cache_lock:
        _cached_at = 0.0


def get_current() -> CourseConfig:
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
    return get_current().render(template)
