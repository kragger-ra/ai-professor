"""Generate 30 GT questions via gpt-5.4, one per representative chunk."""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

# Load .env
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

chunks = json.loads((ROOT / "eval_results" / "_chunks.json").read_text(encoding="utf-8"))

# ----------------------------------------------------------------------
# Pick representative chunks: spread across 4 sources, prefer mid-size + meaty
# ----------------------------------------------------------------------
from collections import defaultdict
by_source = defaultdict(list)
for c in chunks:
    name = c["source"].split("\\")[-1]
    by_source[name].append(c)

PICK_PER_SOURCE = {
    "00_personalab_canonical.md": 8,
    "supplemental_aprobacia.md": 6,
    "week2_lecture.md": 8,
    "week3_lecture.md": 8,
}
# total = 30

def is_content_chunk(c):
    """Skip thin / header-only chunks."""
    text = c["content"].strip()
    if len(text) < 150:
        return False
    # Count meaningful lines (non-header, non-bullet-only)
    body_lines = [
        ln for ln in text.split("\n")
        if ln.strip() and not ln.strip().startswith("#")
    ]
    return len(body_lines) >= 2

picked = []
for src, n in PICK_PER_SOURCE.items():
    candidates = [c for c in by_source[src] if is_content_chunk(c)]
    if not candidates:
        candidates = by_source[src]
    # uniform stride
    step = max(1, len(candidates) // n)
    chosen = candidates[::step][:n]
    if len(chosen) < n:
        # backfill if stride too sparse
        rest = [c for c in candidates if c not in chosen]
        chosen += rest[: n - len(chosen)]
    picked.extend(chosen)
    print(f"[PICK] {src}: {len(candidates)} candidates -> {len(chosen)} picked")

print(f"\nTotal picked = {len(picked)}")

# ----------------------------------------------------------------------
# Generate questions via gpt-5.4
# ----------------------------------------------------------------------
api_base = os.environ.get("LM_STUDIO_API_BASE", "https://api.openai.com/v1").rstrip("/")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")

GEN_PROMPT = """Прочитай фрагмент учебного материала курса «PersonaLab Workshop» (тема: создание цифрового персонажа на базе LLM + STT + TTS + RAG).

ФРАГМЕНТ:
{chunk}

Сгенерируй ОДИН вопрос, который мог бы задать студент тьютору в голосовом разговоре. Жёсткие правила:
- Ответ на вопрос должен лежать в этом фрагменте.
- Студент говорит вслух — вопрос звучит естественно, разговорно, 1-2 предложения, без формальностей.
- НЕ копируй редкие/специфичные термины и формулировки из фрагмента дословно — перефразируй так, как студент реально спросил бы. Например, если в фрагменте «инкапсулированная инициализационная инъекция», студент скажет «как туда передаются параметры на старте?», а не повторит термин.
- Если фрагмент описывает X — спрашивай «что такое X / как работает X / зачем X», а не «процитируй мне определение X».
- Не задавай мета-вопросы вроде «о чём этот фрагмент».
- Вопрос на русском.

Ответь ОДНОЙ строкой — самим вопросом, без префиксов, без кавычек, без пояснений."""

results = []
for i, c in enumerate(picked):
    chunk_text = c["content"][:1400]  # cap to keep prompt tidy
    body = {
        "model": model,
        "messages": [{"role": "user", "content": GEN_PROMPT.format(chunk=chunk_text)}],
        "max_completion_tokens": 100,
        "temperature": 0.7,
        "stream": False,
    }
    if os.environ.get("LM_STUDIO_REASONING_EFFORT"):
        body["reasoning_effort"] = os.environ["LM_STUDIO_REASONING_EFFORT"]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t = time.time()
    try:
        r = requests.post(f"{api_base}/chat/completions", json=body, headers=headers, timeout=30)
        r.raise_for_status()
        q_text = r.json()["choices"][0]["message"]["content"].strip()
        # Strip wrapping quotes / leading dashes
        q_text = q_text.strip('«»"\'`-—– ')
        q_text = re.sub(r"^[\d.)]+\s*", "", q_text)
        dt = time.time() - t
        results.append({
            "qid": i + 1,
            "question": q_text,
            "gt_chunk_id": c["chunk_id"],
            "gt_source": c["source"].split("\\")[-1],
            "gt_preview": c["content"][:200],
        })
        print(f"[Q#{i+1:>2}] ({dt:.1f}s) [{c['source'].split(chr(92))[-1]}] {q_text}")
    except Exception as e:
        print(f"[Q#{i+1}] ERROR: {e}")

(ROOT / "eval_results" / "_gt_questions.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\nSaved {len(results)} GT questions to eval_results/_gt_questions.json")
