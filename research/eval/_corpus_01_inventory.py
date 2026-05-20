"""Tech cleanup + inventory of corpus files for full RAG expansion."""
from __future__ import annotations

import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent
TGT = ROOT / "resources" / "RAG" / "course_materials_full"

files = sorted(TGT.glob("*.md"))
rows = []
for f in files:
    raw = f.read_bytes()
    had_bom = raw.startswith(b"\xef\xbb\xbf")
    if had_bom:
        raw = raw[3:]
    text = raw.decode("utf-8", errors="replace")
    before_len = len(text)
    # collapse 3+ blank lines to 2 (one empty line)
    text2 = re.sub(r"\n{3,}", "\n\n", text)
    # strip "Page X of Y" footers (rare, but safe)
    text2 = re.sub(r"^\s*Page \d+ of \d+\s*$\n?", "", text2, flags=re.MULTILINE)
    # normalize CRLF → LF
    text2 = text2.replace("\r\n", "\n").replace("\r", "\n")
    after_len = len(text2)
    if text2 != text or had_bom:
        f.write_bytes(text2.encode("utf-8"))
    paras = [p for p in text2.split("\n\n") if p.strip()]
    headers = [ln for ln in text2.splitlines() if ln.strip().startswith("#")]
    rows.append({
        "file": f.name,
        "size_bytes": after_len,
        "paragraphs": len(paras),
        "headers": len(headers),
        "had_bom": had_bom,
        "cleaned_chars": before_len - after_len,
        "content_check": "OK" if (len(paras) >= 10 and len(headers) >= 3) else "THIN",
    })

# Write inventory
INV = ROOT / "eval_results" / "_corpus_inventory.md"
lines = ["# Corpus inventory — full PersonaLab Workshop\n",
         f"**Generated:** 2026-05-19  ",
         f"**Source files:** {len(rows)}  ",
         f"**Location:** `resources/RAG/course_materials_full/`\n",
         "| File | bytes | paragraphs | headers | BOM | cleaned | content |",
         "|---|---|---|---|---|---|---|"]
for r in rows:
    lines.append(f"| {r['file']} | {r['size_bytes']:,} | {r['paragraphs']} | {r['headers']} | "
                 f"{'yes' if r['had_bom'] else '—'} | {r['cleaned_chars']} chars | {r['content_check']} |")

lines.append("\n## Sources\n")
lines.append("- `00_personalab_canonical.md` — каноничный обзор курса (academic register), из Tutor")
lines.append("- `supplemental_aprobacia.md` — дополнительный материал к памяти и инструментам, из Tutor")
lines.append("- `week01_lecture.md` — week 1, из `N:/exam/AI-Professor/resources/RAG/course_materials/`")
lines.append("- `week02_lecture.md`, `week03_lecture.md`, `week04_lecture.md` — weeks 2-4, weekly summaries")
lines.append("- `week05-06_lecture.md` … `week11-12_lecture.md` — оригинальные lecture_wN-M_full.md (две недели в файле)")
lines.append("\n## Не включены (и почему)")
lines.append("- `lecture_w1-2_full.md` / `lecture_w3-4_full.md` — дублируются с weekly summaries weeks 1-4")
lines.append("- `example_nettyan_personality.md` — это prompt-шаблон персоны, не лекция")
lines.append("- `lecture_summaries/week*_2026-04-08.md` — дублирующие dated копии")
INV.write_text("\n".join(lines), encoding="utf-8")
print("\n".join(lines))
print(f"\n[OK] inventory → {INV}")
print(f"[OK] total chars in corpus: {sum(r['size_bytes'] for r in rows):,}")
