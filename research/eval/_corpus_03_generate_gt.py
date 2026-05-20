"""Generate GT questions for the full corpus.

Strategy: reuse existing 27 questions (their content is from old canonical/supp/w02/w03
which are unchanged in the new index — chunk_id maps via content match in retrieval),
PLUS generate new questions from the new weeks (01, 04, 05-06, 07-08, 09-10, 11-12).

Old questions stay valid because retrieval matches GT by content equality, and the
content of those 4 old files is byte-identical in the new index.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

NEW_WEEKS = {
    "week01_lecture.md": 5,
    "week04_lecture.md": 5,
    "week05-06_lecture.md": 5,
    "week07-08_lecture.md": 5,
    "week09-10_lecture.md": 5,
    "week11-12_lecture.md": 5,
}
# 30 new + 27 old = 57

chunks = json.loads((ROOT / "eval_results" / "_chunks_full.json").read_text(encoding="utf-8"))
print(f"Loaded {len(chunks)} chunks from new index")

def src_name(c):
    return Path(c["source"]).name

by_source = defaultdict(list)
for c in chunks:
    by_source[src_name(c)].append(c)

def is_content_chunk(c):
    t = c["content"].strip()
    if len(t) < 150:
        return False
    body = [ln for ln in t.split("\n") if ln.strip() and not ln.strip().startswith("#")]
    return len(body) >= 2

picked = []
for src, n in NEW_WEEKS.items():
    candidates = [c for c in by_source[src] if is_content_chunk(c)]
    if not candidates:
        print(f"  [WARN] no content chunks in {src} (have {len(by_source[src])} thin)")
        candidates = by_source[src]
    step = max(1, len(candidates) // n)
    chosen = candidates[::step][:n]
    if len(chosen) < n:
        rest = [c for c in candidates if c not in chosen]
        chosen += rest[: n - len(chosen)]
    picked.extend(chosen)
    print(f"[PICK] {src}: {len(candidates)} candidates → {len(chosen)} picked")
print(f"\nTotal new picks = {len(picked)}")

# OpenAI client
api_base = os.environ.get("LM_STUDIO_API_BASE", "https://api.openai.com/v1").rstrip("/")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")
reasoning = os.environ.get("LM_STUDIO_REASONING_EFFORT", "none")

GEN_PROMPT = """Прочитай фрагмент учебного материала курса «PersonaLab Workshop» (тема: создание цифрового персонажа на базе LLM + STT + TTS + RAG).

ФРАГМЕНТ:
{chunk}

Сгенерируй ОДИН вопрос, который мог бы задать студент тьютору в голосовом разговоре. Жёсткие правила:
- Ответ на вопрос должен лежать в этом фрагменте.
- Студент говорит вслух — вопрос звучит естественно, разговорно, 1-2 предложения, без формальностей.
- НЕ копируй редкие/специфичные термины и формулировки из фрагмента дословно — перефразируй так, как студент реально спросил бы.
- Если фрагмент описывает X — спрашивай «что такое X / как работает X / зачем X», а не «процитируй мне определение X».
- Не задавай мета-вопросы вроде «о чём этот фрагмент».
- Вопрос на русском.

Ответь ОДНОЙ строкой — самим вопросом, без префиксов, без кавычек, без пояснений."""

results = []
qid = 28  # continuing after old 27
for c in picked:
    chunk_text = c["content"][:1400]
    body = {
        "model": model,
        "messages": [{"role": "user", "content": GEN_PROMPT.format(chunk=chunk_text)}],
        "max_completion_tokens": 100,
        "temperature": 0.7,
        "stream": False,
    }
    if reasoning:
        body["reasoning_effort"] = reasoning
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t = time.time()
    try:
        r = requests.post(f"{api_base}/chat/completions", json=body, headers=headers, timeout=30)
        r.raise_for_status()
        q_text = r.json()["choices"][0]["message"]["content"].strip()
        q_text = q_text.strip('«»"\'`-—– ')
        q_text = re.sub(r"^[\d.)]+\s*", "", q_text)
    except Exception as e:
        print(f"[Q#{qid}] ERROR: {e}")
        qid += 1
        continue
    dt = time.time() - t
    results.append({
        "qid": qid,
        "question": q_text,
        "gt_chunk_id": c["chunk_id"],
        "gt_source": src_name(c),
        "gt_preview": c["content"][:200],
        "from": "new",
    })
    print(f"[Q#{qid:>2}] ({dt:.1f}s) [{src_name(c)}] {q_text}")
    qid += 1

# Merge with old 27. Need to remap their gt_chunk_id to NEW index by content match.
old_gt = json.loads((ROOT / "eval_results" / "_gt_questions.json").read_text(encoding="utf-8"))
old_chunks = json.loads((ROOT / "eval_results" / "_chunks.json").read_text(encoding="utf-8"))
old_id_to_content = {c["chunk_id"]: c["content"] for c in old_chunks}
new_content_to_id = {c["content"]: c["chunk_id"] for c in chunks}

remapped = 0
unmapped = 0
old_remapped = []
for q in old_gt:
    old_content = old_id_to_content.get(q["gt_chunk_id"])
    if old_content is None:
        unmapped += 1
        continue
    new_id = new_content_to_id.get(old_content)
    if new_id is None:
        unmapped += 1
        print(f"[OLD Q#{q['qid']}] WARN: content not found in new index, dropping")
        continue
    remapped += 1
    old_remapped.append({
        "qid": q["qid"],
        "question": q["question"],
        "gt_chunk_id": new_id,
        "gt_source": q["gt_source"],
        "gt_preview": q["gt_preview"],
        "from": "old",
    })
print(f"\nRemapped old: {remapped}, unmapped: {unmapped}")

full_gt = old_remapped + results
print(f"Total GT questions: {len(full_gt)}")
(ROOT / "eval_results" / "_gt_questions_full.json").write_text(
    json.dumps(full_gt, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"Saved → eval_results/_gt_questions_full.json")
