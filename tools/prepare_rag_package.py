"""Prepare a RAG package for AI Professor (Tutor build).

Takes a directory of raw .md/.txt course materials and produces a self-contained
RAG package: the same files copied over, plus a `course_config.yml` describing
the course (name, topic, teaching style). The student can then voice-load the
package via "загрузи предмет X из папки Y" in the Tutor.

Usage:
    python tools/prepare_rag_package.py \\
        --source D:\\raw_kb \\
        --out D:\\my_course \\
        --course-name "Линейная алгебра" \\
        --course-topic "векторы, матрицы и линейные операторы" \\
        --short-name "LinAlg" \\
        --teaching-style "строго и формально"

No dependencies on Gradio, LM Studio, or the running agent — runs standalone.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable

try:
    import yaml  # type: ignore
except ImportError:
    print("ERROR: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

# Allow `from agent.rag import ...` when running from repo root.
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))


def _iter_text_files(src: Path) -> Iterable[Path]:
    for ext in (".md", ".txt"):
        yield from src.rglob(f"*{ext}")


def _copy_text_files(src: Path, dst: Path) -> int:
    """Recursively copy .md/.txt from src into dst, preserving subfolder layout."""
    count = 0
    for f in _iter_text_files(src):
        rel = f.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        count += 1
    return count


def _estimate_chunks(dst: Path) -> int | None:
    """Run files through the project's splitter to estimate FAISS chunk count."""
    try:
        from agent.rag import CustomTripleNewLineSplitter  # type: ignore
    except Exception as e:
        print(f"[warn] splitter not importable ({e}); skipping chunk estimate")
        return None
    splitter = CustomTripleNewLineSplitter(chunk_size=1000, chunk_overlap=0)
    total = 0
    for f in _iter_text_files(dst):
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        total += len(splitter.split_text(text))
    return total


def _write_course_config(dst: Path, args: argparse.Namespace) -> Path:
    cfg = {
        "course": {
            "name": args.course_name,
            "topic": args.course_topic,
            "short_name": args.short_name or args.course_name,
            "audience": args.audience,
        },
        "persona": {
            "teaching_style": args.teaching_style,
        },
    }
    out = dst / "course_config.yml"
    with open(out, "w", encoding="utf-8") as f:
        yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Pack raw .md/.txt files into a RAG package with course_config.yml",
    )
    ap.add_argument("--source", required=True, help="Directory with raw .md/.txt files")
    ap.add_argument("--out", required=True, help="Output directory for the RAG package")
    ap.add_argument("--course-name", required=True, help="Full course name (e.g. 'Линейная алгебра')")
    ap.add_argument("--course-topic", required=True, help="Subject scope (e.g. 'векторы и матрицы')")
    ap.add_argument("--short-name", default=None, help="Short label (defaults to course-name)")
    ap.add_argument("--teaching-style", default="дружелюбно",
                    help="One-liner style hint (e.g. 'строго', 'дружелюбно')")
    ap.add_argument("--audience", default="студент",
                    help="Intended listener label ('студент', 'аудитория')")
    ap.add_argument("--overwrite", action="store_true", help="Allow writing into a non-empty --out")
    args = ap.parse_args(argv)

    src = Path(args.source).expanduser().resolve()
    dst = Path(args.out).expanduser().resolve()

    if not src.is_dir():
        print(f"ERROR: --source not a directory: {src}", file=sys.stderr)
        return 1

    files = list(_iter_text_files(src))
    if not files:
        print(f"ERROR: no .md or .txt files under {src}", file=sys.stderr)
        return 1

    if dst.exists():
        if any(dst.iterdir()) and not args.overwrite:
            print(f"ERROR: --out is non-empty: {dst}. Use --overwrite to write anyway.",
                  file=sys.stderr)
            return 1
    else:
        dst.mkdir(parents=True, exist_ok=True)

    copied = _copy_text_files(src, dst)
    cfg_path = _write_course_config(dst, args)
    chunks = _estimate_chunks(dst)

    print(f"Source: {src}")
    print(f"Output: {dst}")
    print(f"Copied: {copied} text file(s)")
    if chunks is not None:
        print(f"Estimated FAISS chunks after split: ~{chunks}")
    print(f"Wrote: {cfg_path}")
    print()
    print("Next step (in Tutor voice):")
    print(f"  «загрузи предмет {args.short_name or args.course_name} из папки {dst}»")
    return 0


if __name__ == "__main__":
    sys.exit(main())
