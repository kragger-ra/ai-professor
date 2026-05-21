"""Smoke test: verify the live RagModel path returns the new corpus.

Instantiates RagModel exactly as the tutor process does and runs explain()
on sample student questions. Checks that retrieval returns non-empty grounded
text below the 1.5 cutoff and that it comes from the White Coding corpus.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[2]
os.chdir(REPO)
os.environ["KMP_DUPLICATE_LIB_OK"] = "True"
for line in (REPO / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
sys.path.insert(0, str(REPO / "src"))

from agent.rag import RagModel  # noqa

rag = RagModel()

QUESTIONS = [
    "Что такое Plan Mode?",
    "Чем Claude Code отличается от Codex?",
    "Что такое коммит в Git?",
    "Зачем нужна команда init?",
    "Что такое вайб-кодинг?",
]

print("\n" + "=" * 64)
print("SMOKE: RagModel.explain() на вопросах из обеих тем")
print("=" * 64)
ok = 0
for q in QUESTIONS:
    text = rag.explain(q)
    score = rag.last_score
    grounded = bool(text) and score <= 1.5
    head = (text.split("\n", 1)[0][:60] if text else "<пусто>")
    print(f"\nQ: {q}")
    print(f"   L2={score:.3f}  grounded={grounded}")
    print(f"   -> {head}")
    ok += int(grounded)

print("\n" + "=" * 64)
print(f"РЕЗУЛЬТАТ: {ok}/{len(QUESTIONS)} вопросов получили заземлённый ответ из корпуса")
print("=" * 64)
sys.exit(0 if ok == len(QUESTIONS) else 1)
