"""One-shot RAG rebuild: read all .md from resources/RAG/course_materials/
and rebuild the FAISS index. Run after adding new files to course_materials
without starting the full tutor.
"""
import sys
import os
sys.path.insert(0, 'src')

from dotenv import load_dotenv
load_dotenv()

from agent.rag import RagModel, RAG_COURSE_DIR

print(f"[REBUILD] RAG_COURSE_DIR = {RAG_COURSE_DIR}")
src = os.path.join(RAG_COURSE_DIR, 'course_materials')
print(f"[REBUILD] source dir   = {src}")
print(f"[REBUILD] files in src:")
for f in sorted(os.listdir(src)):
    full = os.path.join(src, f)
    if os.path.isfile(full):
        print(f"  {f}  ({os.path.getsize(full)} bytes)")

print("[REBUILD] constructing RagModel...")
rm = RagModel()

print("[REBUILD] calling reload_from_path(replace)...")
n = rm.reload_from_path('PersonaLab Workshop', src, mode='replace')
print(f"[REBUILD] done — {n} chunks loaded total: {len(rm.docs)}")
print(f"[REBUILD] FAISS saved to data/rag_vector_store/")
