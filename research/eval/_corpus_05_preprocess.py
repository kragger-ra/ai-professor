"""Content-level preprocessing of the full corpus.

Strategy per file:
1. Strip clearly administrative sections (homework lists, baseline plans, deadlines).
2. Smart re-chunking with hard cap 400 chars:
   - Walk markdown by section (## / ### headers)
   - For each section, accumulate paragraphs (split by \\n\\n) into chunks
     up to 400 chars
   - If a single paragraph exceeds 400 chars, split it by sentence (.?!) and
     accumulate sentences up to 400 chars
   - Carry the nearest section header (## or ###) into metadata.section so the
     retriever can return it for context
3. Merge very small (<60 chars) fragments into their neighbor.
4. Emit Document objects ready for FAISS.from_documents.

The output is dumped to eval_results/_chunks_full_v2.json (with chunk_id by
emit order), AND the actual Documents are built into a FAISS index in
data/rag_vector_store_full_v2/ in the next step.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "resources" / "RAG" / "course_materials_full"
OUT_JSON = ROOT / "eval_results" / "_chunks_full_v2.json"

MAX_CHUNK = 400          # hard cap, chars
MIN_CHUNK = 80           # merge if smaller
SOFT_TARGET = 320        # try to land near this size

# ---------------------------------------------------------------------------
# Admin / off-topic sections to drop. Match on ## or ### header text (case-insens).
# Keep MOST of the lecture body; drop only the obvious admin/homework chunks.
# ---------------------------------------------------------------------------
DROP_SECTION_PATTERNS = [
    r"задания\s+студентам",       # homework
    r"план\s+baseline",
    r"домашнее\s+задание",
    r"deadlines?",
    r"^план\s*$",
    r"календарь",
]
_DROP_RE = re.compile("|".join(f"(?:{p})" for p in DROP_SECTION_PATTERNS), re.IGNORECASE)

_HEADER_RE = re.compile(r"^(#{2,4})\s+(.+?)\s*$", re.MULTILINE)
_SENT_END_RE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯA-ZЁ«\"'(])")


def split_into_sections(text: str):
    """Yield (header_path, body_text) tuples.

    header_path = the most recent ## (and optionally ### nested) headers joined by '/'.
    body_text = the markdown between this header and the next header at same/higher level.
    """
    headers = list(_HEADER_RE.finditer(text))
    if not headers:
        yield ("", text)
        return
    # Prepend any text before the first header
    if headers[0].start() > 0:
        pre = text[:headers[0].start()].strip()
        if pre:
            yield ("", pre)

    nested = {2: None, 3: None, 4: None}
    for i, m in enumerate(headers):
        level = len(m.group(1))
        title = m.group(2).strip()
        nested[level] = title
        # invalidate deeper levels when a higher header reset
        if level == 2:
            nested[3] = None
            nested[4] = None
        if level == 3:
            nested[4] = None
        end = headers[i + 1].start() if i + 1 < len(headers) else len(text)
        body = text[m.end():end].strip()
        path = " / ".join(t for t in (nested[2], nested[3], nested[4]) if t)
        yield (path, body)


def chunk_section(body: str) -> list[str]:
    """Cut body into 80-400 char chunks, preferring paragraph boundaries."""
    if not body:
        return []
    paras = [p.strip() for p in body.split("\n\n") if p.strip()]
    chunks = []
    buf = ""

    def flush():
        nonlocal buf
        if buf.strip():
            chunks.append(buf.strip())
        buf = ""

    for p in paras:
        # If paragraph itself > MAX_CHUNK, split by sentence
        if len(p) > MAX_CHUNK:
            flush()
            sents = _SENT_END_RE.split(p)
            sbuf = ""
            for s in sents:
                if len(sbuf) + len(s) + 1 > MAX_CHUNK and sbuf:
                    chunks.append(sbuf.strip())
                    sbuf = s
                else:
                    sbuf = (sbuf + " " + s).strip()
            if sbuf:
                chunks.append(sbuf.strip())
            continue
        # Otherwise accumulate with soft target
        if len(buf) + len(p) + 2 > MAX_CHUNK:
            flush()
            buf = p
        else:
            buf = (buf + "\n\n" + p).strip() if buf else p
            if len(buf) >= SOFT_TARGET:
                flush()
    flush()

    # Merge tiny chunks with neighbor
    if not chunks:
        return chunks
    out = [chunks[0]]
    for c in chunks[1:]:
        if len(c) < MIN_CHUNK and out:
            if len(out[-1]) + len(c) + 2 <= MAX_CHUNK + MIN_CHUNK:
                out[-1] = out[-1] + "\n\n" + c
                continue
        out.append(c)
    # Final pass: if the first chunk is itself too small, prepend to next
    if len(out) >= 2 and len(out[0]) < MIN_CHUNK:
        out[1] = out[0] + "\n\n" + out[1]
        out = out[1:]
    return out


# ---------------------------------------------------------------------------
# Walk corpus
# ---------------------------------------------------------------------------
results = []
dropped_sections = 0
dropped_chunks = 0
total_in_chars = 0
total_out_chars = 0

for f in sorted(SRC.glob("*.md")):
    raw = f.read_text(encoding="utf-8")
    total_in_chars += len(raw)
    file_chunks = 0
    for path, body in split_into_sections(raw):
        if not body:
            continue
        # Drop admin sections by header path match
        if path and _DROP_RE.search(path):
            dropped_sections += 1
            continue
        chunks = chunk_section(body)
        for ch in chunks:
            # Tag drop: very short or only-bullets stubs
            stripped = ch.strip()
            if len(stripped) < 50:
                dropped_chunks += 1
                continue
            results.append({
                "chunk_id": len(results),
                "source": str(f),
                "section": path,
                "kind": "knowledge",
                "subject": "PersonaLab",
                "content": stripped,
                "content_len": len(stripped),
            })
            file_chunks += 1
            total_out_chars += len(stripped)
    print(f"  {f.name:<30} → {file_chunks} chunks")

OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

# Stats
sizes = sorted(c["content_len"] for c in results)
from collections import Counter
src_counts = Counter(Path(c["source"]).name for c in results)
print(f"\nTotal chunks after preprocessing: {len(results)} (was 261)")
print(f"  median size = {sizes[len(sizes)//2]} (was 275)")
print(f"  mean size   = {sum(sizes)//len(sizes)} (was 356)")
print(f"  max size    = {sizes[-1]} (was 2608)")
print(f"  Dropped admin sections: {dropped_sections}")
print(f"  Dropped tiny chunks: {dropped_chunks}")
print(f"  Content reduction: {total_in_chars}→{total_out_chars} chars "
      f"({(total_out_chars/total_in_chars-1)*100:+.0f}%)")
print(f"\nChunks per source:")
for src, n in sorted(src_counts.items()):
    print(f"  {src:<30} n={n}")
print(f"\nSaved → {OUT_JSON}")
