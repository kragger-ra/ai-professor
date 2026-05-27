"""One-off helper: build the two beta-test course packs under
samples/test_courses/. Run from the repo root.

Repackages courses/<short_name>/ as a course.zip and copies the
matching methodology PDF from the developer's desktop. Intended to
be re-run when either source course changes; the result is checked
in so testers get the packs straight from git.
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path


def pack(src_dir: Path, top_folder: str, dest_zip: Path) -> None:
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(dest_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.rglob("*"):
            if f.is_dir():
                continue
            arc = (Path(top_folder) / f.relative_to(src_dir))
            zf.write(f, arcname=str(arc).replace("\\", "/"))


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    samples_root = repo / "samples" / "test_courses"

    pdf_ml = Path("C:/Users/Whiter/Desktop/dswok_ml_metrics.pdf")
    pdf_nlp = Path("C:/Users/Whiter/Desktop/dswok_dl_nlp.pdf")

    pairs = [
        ("01_classical_ml", repo / "courses" / "Классический МЛ",
         "Классический МЛ", pdf_ml),
        ("02_nlp_neural", repo / "courses" / "dswok_dl_nlp",
         "DSWoK Нейросети и NLP", pdf_nlp),
    ]

    for slot, course_dir, top, pdf in pairs:
        if not course_dir.is_dir():
            print(f"ERROR: missing course dir: {course_dir}", file=sys.stderr)
            return 1
        if not pdf.exists():
            print(f"ERROR: missing methodology PDF: {pdf}", file=sys.stderr)
            return 1
        slot_dir = samples_root / slot
        slot_dir.mkdir(parents=True, exist_ok=True)
        dest_zip = slot_dir / "course.zip"
        pack(course_dir, top, dest_zip)
        shutil.copy2(pdf, slot_dir / "methodology.pdf")
        print(f"  {slot}: course.zip ({dest_zip.stat().st_size} bytes) + "
              f"methodology.pdf ({(slot_dir / 'methodology.pdf').stat().st_size} bytes)")

    print()
    print("contents of samples/test_courses/:")
    for p in sorted(samples_root.rglob("*")):
        if p.is_file():
            rel = p.relative_to(samples_root)
            print(f"  {rel}  ({p.stat().st_size:>9} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
