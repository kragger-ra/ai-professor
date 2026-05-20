"""Run 5 typical scenarios through the full pipeline:
RAG → meta-agent → main LLM streaming, multi-turn history preserved.

Captures per-turn: question, retrieved chunks + L2, meta-agent verdict,
TTFT, e2e, response, response_meta-style indicators.
"""
from __future__ import annotations

import json
import os
import sqlite3
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

for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

sys.path.insert(0, str(ROOT / "src"))

from agent.rag import RagModel
from agent.meta_agent import analyze_context, build_meta_instruction
from lecture import course_config
from lecture.student_profiles import StudentProfileManager


# =============================================================================
# Setup
# =============================================================================
print("[init] RAG (active 1-week index)")
rag = RagModel()
profile_mgr = StudentProfileManager()

STUDENT = "EvalStudent_2026_05_20"
print(f"[init] using student name = {STUDENT}")

# Snapshot DB state before
sp_db = ROOT / "data" / "student_profiles.db"
con = sqlite3.connect(str(sp_db))
con.row_factory = sqlite3.Row
before_students = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
before_logs = con.execute("SELECT COUNT(*) FROM interaction_log").fetchone()[0]
# Verify our test student doesn't already exist
con.execute("DELETE FROM students WHERE name = ?", (STUDENT,))
con.execute("DELETE FROM interaction_log WHERE student_name = ?", (STUDENT,))
con.commit()
print(f"[init] cleaned old test student rows")
print(f"[init] DB BEFORE: {before_students} students, {before_logs} logs")

# Build persona prompt
SYS_TEMPLATE = (ROOT / "resources" / "Prompts" / "personalities_professor.yml").read_text(encoding="utf-8")
def get_persona(manner: str = "simpler") -> str:
    key = f"professor_{manner}"
    block = SYS_TEMPLATE.split(f"{key}:", 1)[1]
    # Split on next persona key
    next_keys = ["professor_simpler:", "professor_neutral:", "professor_detailed:", "professor_summarizer:"]
    for nk in next_keys:
        if nk in block and not nk.startswith(key):
            block = block.split(nk, 1)[0]
            break
    block = "\n".join(l[2:] if l.startswith("  ") else l for l in block.splitlines())
    cfg = course_config.get_current()
    return cfg.render(block)


# OpenAI client
api_base = os.environ.get("LM_STUDIO_API_BASE").rstrip("/")
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("LM_STUDIO_MODEL_NAME", "gpt-5.4")
reasoning = os.environ.get("LM_STUDIO_REASONING_EFFORT", "none")


def build_rag_block(query: str):
    """Replicate prompt_constructor.construct_prompt RAG header logic."""
    rag_text = rag.explain(query)
    score = rag.last_score if hasattr(rag, "last_score") else float("inf")
    sources = list(rag.last_sources) if hasattr(rag, "last_sources") else []
    if not rag_text:
        return None, score, sources, ""
    if score < 0.8:
        header = "## Контекст из материалов курса (высокая релевантность):"
    elif score < 1.2:
        header = "## Контекст из материалов курса (частичное совпадение — дополни из своих знаний):"
    else:
        header = "## Контекст из материалов курса (низкая релевантность — опирайся на свои знания):"
    return rag_text, float(score), sources, f"\n\n{header}\n{rag_text}"


def call_main_llm(messages, max_tokens=400):
    """Streaming call, returns (ttft_ms, e2e_ms, full_answer, n_tokens)."""
    body = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
        "temperature": 0.6,
        "stream": True,
    }
    if reasoning:
        body["reasoning_effort"] = reasoning
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    t_call = time.time()
    t_first = None
    tokens = 0
    full = []
    try:
        r = requests.post(f"{api_base}/chat/completions", json=body, headers=headers,
                          stream=True, timeout=60)
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            data = line[6:]
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
                delta = chunk["choices"][0].get("delta", {})
                content = delta.get("content")
                if content:
                    if t_first is None:
                        t_first = time.time()
                    tokens += 1
                    full.append(content)
            except Exception:
                continue
    except Exception as e:
        print(f"[LLM] error: {e}")
        return None, None, "", 0
    e2e = (time.time() - t_call) * 1000
    ttft = (t_first - t_call) * 1000 if t_first else None
    return ttft, e2e, "".join(full).strip(), tokens


def run_turn(history, user_msg, manner="simpler", note=""):
    """Process one user turn through the full pipeline; return turn dict."""
    print(f"\n  USER: {user_msg}")

    # RAG
    rag_text, l2_score, sources, rag_block = build_rag_block(user_msg)
    print(f"  [RAG] L2={l2_score:.3f}  sources={len(sources)}")

    # Meta-agent (uses last N messages from history)
    last_msgs = []
    for h in history[-5:]:
        if h["role"] in ("user", "assistant"):
            tag = "Студент:" if h["role"] == "user" else "Тьютор:"
            last_msgs.append(f"{tag} {h['content'][:200]}")
    student_profile = profile_mgr.get_profile_for_prompt(STUDENT)
    meta = analyze_context(student_profile, last_msgs, user_msg)
    meta_inst = build_meta_instruction(meta, student_known=True)
    print(f"  [META] mood={meta.get('mood')} level={meta.get('level')} "
          f"needs_analogy={meta.get('needs_analogy')} stt_garbled={meta.get('stt_garbled')} "
          f"ref={meta.get('ref')} stuck_on={meta.get('stuck_on')} style_hint={meta.get('style_hint')}")

    # Build system prompt
    persona = get_persona(manner)
    profile_section = "\n\n## Профиль студента:\n" + student_profile if student_profile else ""
    meta_section = "\n\n## Стиль текущего ответа:\n" + meta_inst if meta_inst else ""
    full_sys = persona + (rag_block or "") + profile_section + meta_section

    # Compose messages = [system, ...history..., user]
    messages = [{"role": "system", "content": full_sys}]
    for h in history:
        if h["role"] in ("user", "assistant"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": user_msg})

    ttft, e2e, answer, tokens = call_main_llm(messages)
    print(f"  [LLM] TTFT={ttft:.0f}ms e2e={e2e:.0f}ms tokens={tokens}")
    print(f"  ASSISTANT: {answer[:200]}{'...' if len(answer) > 200 else ''}")

    # Log to DB
    profile_mgr.log_interaction(
        STUDENT, user_msg, answer,
        meta_analysis=json.dumps(meta, ensure_ascii=False),
        emotion="neutral",
    )

    return {
        "user": user_msg,
        "assistant": answer,
        "rag": {
            "L2_top1": l2_score,
            "sources": sources,
            "rag_text_len": len(rag_text or ""),
        },
        "meta": meta,
        "manner": manner,
        "timing": {"ttft_ms": ttft, "e2e_ms": e2e, "tokens": tokens},
        "note": note,
    }


# =============================================================================
# Scenarios
# =============================================================================
all_results = {}

# Create the student first
profile_mgr.get_or_create_student(STUDENT)

# US-1 — Самостоятельная подготовка (одноходовой)
print("\n" + "=" * 70)
print("US-1 — Самостоятельная подготовка")
print("=" * 70)
history = []
turn = run_turn(history, "Объясни мне разницу между summary и rank в архитектуре агента.")
history.append({"role": "user", "content": turn["user"]})
history.append({"role": "assistant", "content": turn["assistant"]})
all_results["US-1"] = {"description": "Самостоятельная подготовка — одноходовой технический вопрос",
                        "turns": [turn]}

# US-2 — Разбор термина
print("\n" + "=" * 70)
print("US-2 — Разбор термина")
print("=" * 70)
history = []
turn = run_turn(history, "Что такое prefill?")
history.append({"role": "user", "content": turn["user"]})
history.append({"role": "assistant", "content": turn["assistant"]})
all_results["US-2"] = {"description": "Разбор термина — короткий вопрос о понятии",
                        "turns": [turn]}

# US-3 — Эскалация / off-topic
print("\n" + "=" * 70)
print("US-3 — Эскалация (off-topic)")
print("=" * 70)
history = []
# Off-topic: cooking recipe — clearly outside PersonaLab Workshop scope
turn = run_turn(history, "Расскажи рецепт борща.")
history.append({"role": "user", "content": turn["user"]})
history.append({"role": "assistant", "content": turn["assistant"]})
all_results["US-3"] = {"description": "Эскалация / off-topic — должна получить мягкий отказ",
                        "turns": [turn]}

# US-4 — Многоходовой диалог
print("\n" + "=" * 70)
print("US-4 — Многоходовой диалог")
print("=" * 70)
history = []
turn1 = run_turn(history, "Я не понял, как работает Like Tool.")
history.append({"role": "user", "content": turn1["user"]})
history.append({"role": "assistant", "content": turn1["assistant"]})
turn2 = run_turn(history, "А что будет, если ранг уже на максимуме?")
history.append({"role": "user", "content": turn2["user"]})
history.append({"role": "assistant", "content": turn2["assistant"]})
all_results["US-4"] = {"description": "Многоходовой — контекст переносится во второй ход",
                        "turns": [turn1, turn2]}

# US-5 — Адаптация на «не понимаю»
print("\n" + "=" * 70)
print("US-5 — Адаптация на «не понимаю»")
print("=" * 70)
history = []
# First with neutral manner (more technical), then student requests simpler
turn1 = run_turn(history, "Объясни про tool_status.", manner="neutral")
history.append({"role": "user", "content": turn1["user"]})
history.append({"role": "assistant", "content": turn1["assistant"]})
turn2 = run_turn(history, "Слишком сложно, проще.", manner="simpler",
                 note="style switched simpler ← neutral after explicit ask")
history.append({"role": "user", "content": turn2["user"]})
history.append({"role": "assistant", "content": turn2["assistant"]})
all_results["US-5"] = {"description": "Адаптация — простой режим включается после «слишком сложно»",
                        "turns": [turn1, turn2]}

# DB snapshot AFTER
after_students = con.execute("SELECT COUNT(*) FROM students").fetchone()[0]
after_logs = con.execute("SELECT COUNT(*) FROM interaction_log WHERE student_name = ?",
                          (STUDENT,)).fetchone()[0]
student_row = dict(con.execute("SELECT * FROM students WHERE name = ?", (STUDENT,)).fetchone())
print(f"\n[final] DB AFTER: {after_students} students, +{after_logs} logs for {STUDENT}")
print(f"[final] student row: {student_row}")

all_results["_db_snapshot"] = {
    "before": {"students": before_students, "test_student_logs": 0},
    "after": {"students": after_students, "test_student_logs": after_logs},
    "test_student_row": student_row,
}

out = ROOT / "eval_results" / "_scenarios_run.json"
out.write_text(json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
               encoding="utf-8")
print(f"\nSaved → {out}")
con.close()
