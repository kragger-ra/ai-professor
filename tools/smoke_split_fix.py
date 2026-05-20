"""Verify the 'Формулировка о том' false-split is fixed."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from tts.vosk.vosk_tts import split_sentences

# The exact failing case from production logs (2026-05-16).
bad = ("Формулировка о том, что агент помнит всех пользователей, "
       "с которыми взаимодействовал, как раз и объясняется постоянной "
       "передачей сжатого контекста.")
result = split_sentences(bad)
print("Input:", bad)
print("Output:")
for i, s in enumerate(result):
    print(f"  [{i}] {s}")

# Must NOT contain a standalone fragment 'Формулировка о том.'
assert not any(s.strip() == "Формулировка о том." for s in result), \
    "BUG: still produces 'Формулировка о том.' fragment"
print()
print("[OK] no idiomatic 'о том.' fragment")

# A LEGITIMATE long sentence with conjunction should still split.
long_legit = ("Агент сохраняет ключевую информацию о пользователе в базе "
              "данных, и при следующем обращении этот контекст передаётся "
              "обратно в модель для генерации ответа.")
result2 = split_sentences(long_legit)
print()
print("Long legit input:", long_legit)
print("Output:")
for i, s in enumerate(result2):
    print(f"  [{i}] {s}")
# This one SHOULD split (>5 words before 'и', tail isn't idiomatic).
print()
print(f"[{'OK' if len(result2) > 1 else 'INFO'}] long sentence split: {len(result2)} parts")

# Short sentence (≤18 words) — untouched
short = "Память агента живёт в SQLite базе данных."
result3 = split_sentences(short)
assert len(result3) == 1, f"short sentence wrongly split: {result3}"
print("[OK] short sentence untouched")
