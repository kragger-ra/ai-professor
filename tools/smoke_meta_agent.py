"""Smoke for the slimmed meta-agent against gpt-5.4-nano.

Runs 5 mini-scenarios and prints the meta JSON + rendered instruction.
Costs <$0.005 total.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

env_path = ROOT / ".env"
for line in env_path.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, _, v = line.partition("=")
    k = k.strip()
    v = v.strip().strip('"').strip("'")
    if k and k not in os.environ:
        os.environ[k] = v

print(f"META_BACKEND={os.environ.get('META_BACKEND')!r}")
print(f"META_LOCAL_MODEL={os.environ.get('META_LOCAL_MODEL')!r}")
print()

from agent.meta_agent import analyze_context, build_meta_instruction  # noqa: E402

scenarios = [
    {
        "name": "calm tech question",
        "profile": "name=Алексей; background=backend dev; tech_level=4",
        "history": [
            "Студент: расскажи про память агента",
            "Профессор: память агента хранит контекст диалога...",
        ],
        "current": "А как настраивается размер контекста?",
    },
    {
        "name": "confused student, repeated 'не понимаю'",
        "profile": "name=Маша; tech_level=2",
        "history": [
            "Студент: что такое эмбеддинги?",
            "Профессор: это векторное представление...",
            "Студент: не понимаю",
            "Профессор: давай иначе — представь что слова это точки в пространстве",
        ],
        "current": "всё равно не понимаю, объясни проще",
    },
    {
        "name": "anaphoric reference",
        "profile": "name=Иван",
        "history": [
            "Профессор: ranker - инструмент сортировки документов по релевантности",
            "Студент: понятно",
        ],
        "current": "А это работает с любым запросом?",
    },
    {
        "name": "STT garble",
        "profile": "name=Тест",
        "history": ["Профессор: что хотел спросить?"],
        "current": "ну вот это самое модельмент или как там стайл",
    },
    {
        "name": "stuck on concept",
        "profile": "name=Олег",
        "history": [
            "Студент: что такое RAG?",
            "Профессор: retrieval-augmented generation...",
            "Студент: то есть это поиск? не пойму",
            "Профессор: это поиск плюс генерация ответа",
            "Студент: а зачем тогда генерация",
        ],
        "current": "вот этот RAG я не понимаю зачем нужен",
    },
]

for sc in scenarios:
    print("=" * 60)
    print(f"Scenario: {sc['name']}")
    print(f"Current: {sc['current']!r}")
    result = analyze_context(sc["profile"], sc["history"], sc["current"])
    instr = build_meta_instruction(result, student_known=True)
    print(f"Instruction: {instr}")
    print()
