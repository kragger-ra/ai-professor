"""Offline smoke test for Tutor voice command regexes."""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "src"))

# Replicate the patterns from CoreAgent (no need to import the whole agent)
_LOAD_SUBJECT_RE = re.compile(
    r"(?P<verb>загрузи|подгрузи|добавь)\s+"
    r"(?:предмет|курс|тему|дисциплину)\s+"
    r"(?P<name>.+?)\s+"
    r"из\s+(?:папки\s+)?(?P<path>.+?)\s*$",
    re.IGNORECASE,
)

_TOPIC_LECTURE_RE = re.compile(
    r"(?:расскажи(?:\s+мне)?(?:\s+(?:про|о|об))?|объясни(?:\s+мне)?(?:\s+(?:про|о|об))?|"
    r"хочу\s+изучить|изучим|давай\s+(?:изучим|разберём))\s+(?P<topic>.+?)\s*$",
    re.IGNORECASE,
)

_END_LECTURE_PHRASES = (
    "завершаем пару", "заканчиваем пару", "конец пары", "закончим пару",
    "завершаем занятие", "заканчиваем занятие",
)


def check(label, regex, text, expected_groups=None):
    m = regex.search(text)
    if m:
        result = m.groupdict()
        ok = (expected_groups is None) or all(
            v.lower() == result.get(k, "").lower().strip(".!?, ") for k, v in expected_groups.items()
        )
        status = "OK" if ok else "MISMATCH"
        print(f"[{status}] {label}: '{text}' -> {result}")
        return ok
    else:
        ok = expected_groups is None
        status = "OK (no match expected)" if ok else "FAIL (no match)"
        print(f"[{status}] {label}: '{text}'")
        return ok


def main():
    print("--- Load subject ---")
    check("load happy path", _LOAD_SUBJECT_RE,
          "загрузи предмет линейная алгебра из папки D:\\subjects\\linal",
          {"verb": "загрузи", "name": "линейная алгебра", "path": "D:\\subjects\\linal"})
    check("podgru zi", _LOAD_SUBJECT_RE,
          "подгрузи курс физика из C:\\physics",
          {"verb": "подгрузи", "name": "физика", "path": "C:\\physics"})
    check("dobav (append)", _LOAD_SUBJECT_RE,
          "добавь предмет химия из папки D:\\chem",
          {"verb": "добавь", "name": "химия", "path": "D:\\chem"})
    check("not a load command", _LOAD_SUBJECT_RE,
          "расскажи мне про линейную алгебру", expected_groups=None)

    print("\n--- Topic lecture ---")
    check("topic happy", _TOPIC_LECTURE_RE,
          "расскажи мне про векторное пространство",
          {"topic": "векторное пространство"})
    check("topic short verb", _TOPIC_LECTURE_RE,
          "расскажи про матрицы",
          {"topic": "матрицы"})
    check("topic explain", _TOPIC_LECTURE_RE,
          "объясни мне про производные",
          {"topic": "производные"})
    check("topic want", _TOPIC_LECTURE_RE,
          "хочу изучить линейные операторы",
          {"topic": "линейные операторы"})

    print("\n--- End-lecture detection ---")
    cases = [
        ("завершаем пару", True),
        ("заканчиваем пару", True),
        ("конец пары", True),
        ("давай завершаем занятие на этом", True),
        ("спасибо за лекцию", False),
        ("есть вопрос", False),
    ]
    for text, expected in cases:
        ml = text.strip().lower().rstrip(".!?,")
        hit = any(p in ml for p in _END_LECTURE_PHRASES)
        status = "OK" if hit == expected else "FAIL"
        print(f"[{status}] '{text}' -> hit={hit} (expected {expected})")

    print("\n[done]")


if __name__ == "__main__":
    main()
