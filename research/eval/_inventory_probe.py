"""Inventory probe — runs in Tutor .venv. Read-only inspection."""
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = ROOT / "data" / "metrics.db"
SP = ROOT / "data" / "student_profiles.db"
FAISS_PKL = ROOT / "data" / "rag_vector_store" / "knowledge.pkl"
COURSE_JSON = ROOT / "data" / "current_course.json"
COURSE_MAT = ROOT / "resources" / "RAG" / "course_materials"

print("=" * 60)
print("METRICS.DB")
print("=" * 60)
con = sqlite3.connect(str(DB))
cur = con.cursor()
cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
for name, sql in cur.fetchall():
    print(f"TABLE {name}")
    print(f"  {sql[:200]}")
cur.execute("SELECT COUNT(1) FROM interactions")
print("interactions_total =", cur.fetchone()[0])
cur.execute("SELECT date(timestamp), COUNT(1) FROM interactions GROUP BY date(timestamp) ORDER BY 1 DESC LIMIT 14")
print("interactions per day (last 14):")
for r in cur.fetchall():
    print("  ", r)
cur.execute("SELECT COUNT(1) FROM interactions WHERE date(timestamp) BETWEEN '2026-05-16' AND '2026-05-19'")
print("interactions in 2026-05-16..19 =", cur.fetchone()[0])
cur.execute("SELECT COUNT(1) FROM system_metrics")
print("system_metrics_total =", cur.fetchone()[0])
cur.execute("SELECT MIN(timestamp), MAX(timestamp) FROM interactions")
print("ts span:", cur.fetchone())
# Average / sample
cur.execute("SELECT AVG(response_time_ms), MIN(response_time_ms), MAX(response_time_ms) FROM interactions WHERE response_time_ms > 0")
print("response_time_ms avg/min/max =", cur.fetchone())
cur.execute("SELECT COUNT(1) FROM interactions WHERE rag_sources IS NOT NULL AND rag_sources != '' AND rag_sources != '[]'")
print("interactions_with_rag_sources =", cur.fetchone()[0])
con.close()

print()
print("=" * 60)
print("STUDENT_PROFILES.DB")
print("=" * 60)
try:
    con = sqlite3.connect(str(SP))
    cur = con.cursor()
    cur.execute("SELECT name, sql FROM sqlite_master WHERE type='table'")
    for name, sql in cur.fetchall():
        print(f"TABLE {name}")
        print(f"  {sql[:200]}")
    for tbl in ("students", "weak_blocks", "session_log", "profile_history"):
        try:
            cur.execute(f"SELECT COUNT(1) FROM {tbl}")
            print(f"{tbl}_count =", cur.fetchone()[0])
        except Exception as e:
            print(f"{tbl}: {e}")
    con.close()
except Exception as e:
    print("student_profiles.db error:", e)

print()
print("=" * 60)
print("RAG INDEX")
print("=" * 60)
print("current_course.json:", COURSE_JSON.read_text(encoding='utf-8') if COURSE_JSON.exists() else "MISSING")
print()
# Try loading the FAISS pickle to get chunk count without bringing up embeddings.
try:
    import pickle
    with open(FAISS_PKL, "rb") as f:
        data = pickle.load(f)
    # langchain FAISS pickle: tuple(docstore, index_to_id) typically
    print("knowledge.pkl loaded, type:", type(data).__name__)
    if isinstance(data, tuple):
        print("tuple len:", len(data))
        for i, x in enumerate(data):
            print(f"  [{i}] {type(x).__name__}", end="")
            try:
                if hasattr(x, "_dict"):
                    print(" docs=", len(x._dict))
                elif isinstance(x, dict):
                    print(" entries=", len(x))
                else:
                    print()
            except Exception as e:
                print(" err:", e)
        # langchain InMemoryDocstore has ._dict mapping id->Document
        if hasattr(data[0], "_dict"):
            docs = list(data[0]._dict.values())
            sizes = [len(getattr(d, "page_content", "")) for d in docs]
            subjects = {}
            kinds = {}
            for d in docs:
                m = getattr(d, "metadata", {}) or {}
                kinds[m.get("kind", "?")] = kinds.get(m.get("kind", "?"), 0) + 1
                subjects[m.get("subject", "?")] = subjects.get(m.get("subject", "?"), 0) + 1
            print(f"chunk_count = {len(docs)}")
            if sizes:
                sizes.sort()
                print(f"chunk size: min={sizes[0]} median={sizes[len(sizes)//2]} "
                      f"mean={sum(sizes)/len(sizes):.0f} max={sizes[-1]}")
            print("kinds:", kinds)
            print("subjects:", subjects)
            # First 2 doc previews
            for d in docs[:2]:
                print("---")
                print("metadata:", getattr(d, "metadata", {}))
                print("preview:", getattr(d, "page_content", "")[:200])
except Exception as e:
    print("FAISS pkl read failed:", e)

print()
print("=" * 60)
print("COURSE MATERIALS")
print("=" * 60)
if COURSE_MAT.is_dir():
    for f in sorted(COURSE_MAT.rglob("*")):
        if f.is_file():
            print(f"{f.name} {f.stat().st_size} bytes")

# Embeddings dimensionality from FAISS index file
try:
    import faiss
    idx = faiss.read_index(str(ROOT / "data" / "rag_vector_store" / "knowledge.faiss"))
    print()
    print("FAISS index dim =", idx.d, "ntotal =", idx.ntotal, "type =", type(idx).__name__)
except Exception as e:
    print("faiss probe failed:", e)
