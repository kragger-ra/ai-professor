"""Filesystem scanner for prepared RAG course packages.

A course package is any directory that contains ``course_config.yml`` next
to one or more ``.md`` / ``.txt`` files. The scanner walks a small set of
well-known roots (``courses/``, ``samples/``, ``data/courses/``) and
returns one entry per package found.

Pure Python — no Qt imports. Used by both the Course Manager dock and the
toolbar Quick-switcher.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

try:
    import yaml  # type: ignore
except ImportError:
    yaml = None


_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_ROOTS = ("courses", "samples", "data/courses")
_TEXT_EXTS = (".md", ".markdown", ".txt")


@dataclass(frozen=True)
class CourseEntry:
    path: str             # absolute path to the package directory
    short_name: str       # for voice-loading & switcher label
    name: str             # full course name (display)
    files_count: int      # number of .md/.txt files inside the package
    mtime: float          # course_config.yml mtime (sortable)


def read_course_yaml(yml_path: Path) -> dict:
    """Best-effort read; returns {} on any failure."""
    if yaml is None:
        return {}
    try:
        with open(yml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _short_name_from(cfg: dict, dirname: str) -> str:
    course = cfg.get("course") or {}
    if isinstance(course, dict):
        for k in ("short_name", "name"):
            v = course.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    for k in ("short_name", "name"):
        v = cfg.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return dirname


def _full_name_from(cfg: dict, dirname: str) -> str:
    course = cfg.get("course") or {}
    if isinstance(course, dict):
        v = course.get("name")
        if isinstance(v, str) and v.strip():
            return v.strip()
    v = cfg.get("name")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return dirname


def _count_text_files(directory: Path) -> int:
    n = 0
    for ext in _TEXT_EXTS:
        n += sum(1 for _ in directory.rglob(f"*{ext}"))
    return n


def scan_courses(
    roots: Iterable[str] = _DEFAULT_ROOTS,
    *,
    repo_root: Path | None = None,
) -> list[CourseEntry]:
    """Return one ``CourseEntry`` per detected package, sorted by mtime DESC."""
    base = repo_root or _REPO_ROOT
    seen: set[str] = set()
    out: list[CourseEntry] = []
    for root in roots:
        root_path = (base / root).resolve()
        if not root_path.is_dir():
            continue
        for yml in root_path.rglob("course_config.yml"):
            pkg_dir = yml.parent
            key = str(pkg_dir.resolve())
            if key in seen:
                continue
            seen.add(key)
            cfg = read_course_yaml(yml)
            try:
                mtime = yml.stat().st_mtime
            except OSError:
                mtime = 0.0
            out.append(CourseEntry(
                path=key,
                short_name=_short_name_from(cfg, pkg_dir.name),
                name=_full_name_from(cfg, pkg_dir.name),
                files_count=_count_text_files(pkg_dir),
                mtime=mtime,
            ))
    out.sort(key=lambda e: e.mtime, reverse=True)
    return out
