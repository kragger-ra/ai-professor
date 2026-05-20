"""Re-map the 57 GT questions to v2 chunk_ids.

Since chunking changed, old GT chunk_ids are meaningless on the v2 index.
For each GT question, find the v2 chunk(s) whose content has highest
substring/token overlap with the original gt_preview (or full gt_content).

Result: each GT question gets a SET of acceptable v2 chunk_ids (multi-GT).
A retrieval hit is success if ANY of these chunks lands in top-K.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent

# Load original GT (already has 57 questions, each with gt_preview)
gt = json.loads((ROOT / "eval_results" / "_gt_questions_full.json").read_text(encoding="utf-8"))

# Old chunks (v1): use to recover full content if gt_preview is too short for matching
v1_chunks = json.loads((ROOT / "eval_results" / "_chunks_full.json").read_text(encoding="utf-8"))
v1_by_id = {c["chunk_id"]: c for c in v1_chunks}

v2_chunks = json.loads((ROOT / "eval_results" / "_chunks_full_v2.json").read_text(encoding="utf-8"))
print(f"v1 chunks: {len(v1_chunks)}, v2 chunks: {len(v2_chunks)}, GT questions: {len(gt)}")


def normalize(s: str) -> str:
    """Lower, strip punct, collapse whitespace."""
    s = s.lower()
    s = re.sub(r"[^\w\s\-/]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def jaccard_words(a: str, b: str) -> float:
    """Jaccard similarity over whitespace-tokenized words, after normalization."""
    A = set(normalize(a).split())
    B = set(normalize(b).split())
    if not A or not B:
        return 0.0
    return len(A & B) / len(A | B)


def best_v2_matches(v1_full_content: str, v2_chunks: list, top_n: int = 3,
                    min_jac: float = 0.30) -> list:
    """Return up to top_n v2 chunks ranked by Jaccard similarity to v1 GT content,
    filtered by min_jac. Source-aware: prefer chunks from the same source file."""
    scored = []
    for c2 in v2_chunks:
        jac = jaccard_words(v1_full_content, c2["content"])
        if jac >= min_jac:
            scored.append((jac, c2["chunk_id"], c2))
    scored.sort(reverse=True)
    return scored[:top_n]


remapped = []
unmapped = []
for q in gt:
    qid = q["qid"]
    # Recover full v1 content if available; otherwise fall back to preview
    v1_id = q.get("gt_chunk_id")
    v1_full = v1_by_id[v1_id]["content"] if v1_id in v1_by_id else q["gt_preview"]
    same_src = q["gt_source"]

    # Restrict candidates to same source file first; if none, broaden to all
    same_src_chunks = [c for c in v2_chunks if Path(c["source"]).name == same_src]
    matches = best_v2_matches(v1_full, same_src_chunks, top_n=3, min_jac=0.20)
    if not matches:
        # Broader fallback
        matches = best_v2_matches(v1_full, v2_chunks, top_n=3, min_jac=0.25)

    if not matches:
        unmapped.append(qid)
        print(f"[Q#{qid:>2}] UNMAPPED — no v2 chunk with jaccard >= 0.25 (src={same_src})")
        continue

    gt_ids = [m[1] for m in matches]
    top_jac = matches[0][0]
    remapped.append({
        "qid": qid,
        "from": q.get("from", "?"),
        "question": q["question"],
        "gt_chunk_ids_v2": gt_ids,                    # NEW: multi-GT support
        "gt_top_jaccard": round(top_jac, 3),
        "gt_v1_chunk_id": v1_id,
        "gt_source": same_src,
        "gt_v2_previews": [m[2]["content"][:120] for m in matches],
    })
    flag = "✓" if top_jac >= 0.5 else "~"
    print(f"[Q#{qid:>2}] {flag} jac={top_jac:.2f} ids={gt_ids} src={same_src}")

print(f"\nMapped: {len(remapped)} / {len(gt)}")
print(f"Unmapped: {unmapped}")
# Stats on top_jac
jacs = sorted(r["gt_top_jaccard"] for r in remapped)
print(f"Top-jac distribution: min={jacs[0]} p25={jacs[len(jacs)//4]} "
      f"p50={jacs[len(jacs)//2]} p75={jacs[3*len(jacs)//4]} max={jacs[-1]}")
strong = sum(1 for j in jacs if j >= 0.5)
print(f"Strong matches (jac >= 0.5): {strong}/{len(jacs)}")

(ROOT / "eval_results" / "_gt_questions_v2.json").write_text(
    json.dumps(remapped, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(f"\nSaved → eval_results/_gt_questions_v2.json")
