"""Verify lecture-vs-Q&A routing + concept-lookup extraction."""
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
    k = k.strip(); v = v.strip().strip('"').strip("'")
    if k and k not in os.environ:
        os.environ[k] = v

from agent.core_agent import CoreAgent  # noqa: E402

LECTURE_OK = [
    "Расскажи про память агента",
    "Профессор, расскажи мне про память агента",
    "Расскажи мне ещё раз про память агентов",
    "Объясни мне про саммари",
    "Можешь рассказать про rank",
    "Давай разберём память агента",
    "Хочу изучить prompt constructor",
]

# These were WRONGLY routed to lecture before the fix — must now miss.
QA_OK = [
    "Что такое summary?",
    "Что такое rank",
    "Что значит summary",
    "Объясни summary",        # bare 'объясни X' (no про) → Q&A
    "Объясни мне саммари",    # bare 'объясни мне X' (no про) → Q&A
    "Опиши rank",
    "Коротко про summary",   # this one matches concept-lookup, falls to Q&A path
    "Что это за rank",
]

NEITHER = [
    "Угу",
    "Понятно",
    "Стоп",
    "Профессор, привет",
]


def is_lecture(msg):
    return CoreAgent._TOPIC_LECTURE_RE.search(msg.strip()) is not None


def is_concept_lookup(msg):
    """Reuse the extractor directly."""
    obj = CoreAgent.__new__(CoreAgent)
    return bool(obj._extract_concept_term(msg))


print("=== Should route as LECTURE ===")
for m in LECTURE_OK:
    ok = is_lecture(m)
    mark = "OK " if ok else "FAIL"
    print(f"  [{mark}] {m!r}")

print()
print("=== Should NOT route as LECTURE (Q&A path) ===")
for m in QA_OK:
    is_lec = is_lecture(m)
    cl = is_concept_lookup(m)
    mark = "OK " if not is_lec else "FAIL-routed-as-lecture"
    note = " (concept-lookup)" if cl else ""
    print(f"  [{mark}] {m!r}{note}")

print()
print("=== Neither lecture nor concept-lookup ===")
for m in NEITHER:
    is_lec = is_lecture(m)
    cl = is_concept_lookup(m)
    bad = is_lec or cl
    mark = "OK " if not bad else "FAIL"
    print(f"  [{mark}] {m!r}")

print()
print("=== Concept term extraction (for narrow-focus inject) ===")
obj = CoreAgent.__new__(CoreAgent)
for m in QA_OK:
    term = obj._extract_concept_term(m)
    print(f"  {m!r}  ->  term={term!r}")
