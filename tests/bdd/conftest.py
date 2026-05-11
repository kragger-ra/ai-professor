"""Shared BDD fixtures for AI-Professor-Tutor.

Each scenario runs in an isolated temporary CWD so writes to
`data/current_course.json` etc. don't bleed between tests.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

# Make `from lecture.* import ...` and `from agent.* import ...` work
TUTOR_ROOT = Path(__file__).resolve().parents[2]
SRC = TUTOR_ROOT / "src"
sys.path.insert(0, str(SRC))


@pytest.fixture
def tmp_cwd(monkeypatch, tmp_path: Path):
    """Run each scenario in a clean cwd; cleanup happens via tmp_path."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_course_config_cache():
    """course_config module caches the loaded config — reset between scenarios."""
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
    """Free-form dict for Given/When/Then to thread state through steps."""
    return {}
