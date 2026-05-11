"""Shared BDD fixtures for AI-Professor (Lecture build)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

LECTURE_ROOT = Path(__file__).resolve().parents[2]
SRC = LECTURE_ROOT / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_cwd(monkeypatch, tmp_path: Path):
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_course_config_cache():
    from lecture import course_config as cc
    cc._cached_cfg = None
    cc._cached_mtime = 0.0
    cc._cached_at = 0.0
    yield
    cc._cached_cfg = None
    cc._cached_mtime = 0.0
    cc._cached_at = 0.0


@pytest.fixture
def context():
    return {}
