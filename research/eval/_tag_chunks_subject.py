"""Set metadata.subject='PersonaLab' on all 140 FAISS chunks and resave."""
from __future__ import annotations

import json
import os
import pickle
import shutil
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
STORE = ROOT / "data" / "rag_vector_store"
BACKUP = ROOT / "data" / "rag_vector_store_pre_subject_tag"

# Subject value comes from data/current_course.json
course = json.loads((ROOT / "data" / "current_course.json").read_text(encoding="utf-8"))
subject = course.get("short_name") or course.get("name") or "PersonaLab"
print(f"[TAG] target subject = '{subject}'")

# Backup first
if not BACKUP.exists():
    shutil.copytree(STORE, BACKUP)
    print(f"[TAG] backed up to {BACKUP}")
else:
    print(f"[TAG] backup already exists at {BACKUP} (skip)")

# Direct path: modify the pkl docstore in place
PKL = STORE / "knowledge.pkl"
with open(PKL, "rb") as f:
    docstore, index_to_id = pickle.load(f)

changed = 0
sample_before = None
for doc_id, doc in docstore._dict.items():
    if sample_before is None:
        sample_before = dict(doc.metadata or {})
    md = doc.metadata or {}
    if md.get("subject") != subject:
        md["subject"] = subject
        doc.metadata = md
        changed += 1
print(f"[TAG] updated subject on {changed}/{len(docstore._dict)} docs")
print(f"[TAG] sample metadata BEFORE: {sample_before}")
print(f"[TAG] sample metadata AFTER:  {dict(next(iter(docstore._dict.values())).metadata)}")

# Write back
with open(PKL, "wb") as f:
    pickle.dump((docstore, index_to_id), f)
print(f"[TAG] saved → {PKL}")

# Verify by reloading through langchain
sys.path.insert(0, str(ROOT / "src"))
# Need .env for embeddings init
for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ[k.strip()] = v.strip().strip('"').strip("'")

# Just verify subject is present in the docstore on reload (don't need embeddings server for that)
with open(PKL, "rb") as f:
    docstore2, _ = pickle.load(f)
subjects = {}
for doc in docstore2._dict.values():
    s = (doc.metadata or {}).get("subject")
    subjects[s] = subjects.get(s, 0) + 1
print(f"[VERIFY] subject distribution after save: {subjects}")
