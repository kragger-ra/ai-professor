"""Pull historical Q's from metrics.db, sample 20 across days/topics."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "metrics.db"

con = sqlite3.connect(str(DB))
con.row_factory = sqlite3.Row
cur = con.cursor()

cur.execute("""
    SELECT id, timestamp, student_query, agent_response, response_time_ms, rag_sources
    FROM interactions
    WHERE student_query IS NOT NULL AND TRIM(student_query) != ''
      AND agent_response IS NOT NULL AND TRIM(agent_response) != ''
    ORDER BY id
""")
all_rows = [dict(r) for r in cur.fetchall()]
print(f"Total non-empty interactions: {len(all_rows)}")

# Filter: skip very short bot responses (greetings, ack) and very short student queries (single word)
def is_substantive(row):
    q = row["student_query"].strip()
    a = row["agent_response"].strip()
    if len(q.split()) < 3:
        return False
    if len(a.split()) < 8:
        return False
    # Drop obvious system / non-question turns
    junk_starts = ("привет", "здравствуй", "слушаю", "хорошо", "понял")
    if q.lower().startswith(junk_starts) and len(q.split()) < 5:
        return False
    return True

filtered = [r for r in all_rows if is_substantive(r)]
print(f"Substantive: {len(filtered)}")

# Stratified sample: 20 items spread across the timeline
# Sort by id, take every Nth
step = max(1, len(filtered) // 20)
sample = filtered[::step][:20]
if len(sample) < 20:
    # backfill from the rest
    rest = [r for r in filtered if r not in sample]
    sample += rest[: 20 - len(sample)]
print(f"Sampled: {len(sample)}")

# Print sample preview
for r in sample:
    q = r["student_query"][:60]
    a = r["agent_response"][:60]
    ts = r["timestamp"]
    print(f"  #{r['id']:>3}  {ts}  Q: {q}  →  A: {a}")

out = ROOT / "eval_results" / "_faithfulness_sample.json"
out.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"\nSaved → {out}")
con.close()
