"""Reset DBs and recording artefacts before a fresh volunteer session.

Usage:
    py scripts/reset_for_volunteer.py [--keep-metrics] [--keep-profiles]

What it does:
    - backs up data/student_profiles.db and data/metrics.db
      to data/backups/{timestamp}/
    - deletes the live files so the next start gets empty DBs
    - DOES NOT touch data/rag_vector_store/, data/current_course.json,
      data/lecture_notes/, resources/RAG/* — the course stays loaded

By default both DBs are reset. Pass --keep-* to skip one of them.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
BACKUPS = DATA / "backups"

TARGETS = {
    "profiles": DATA / "student_profiles.db",
    "metrics": DATA / "metrics.db",
}


def backup_and_delete(label: str, src: Path, stamp: str) -> bool:
    if not src.exists():
        print(f"  [{label}] no file at {src} — nothing to reset")
        return False
    dst_dir = BACKUPS / stamp
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    src.unlink()
    print(f"  [{label}] backed up to {dst.relative_to(ROOT)} and deleted live file")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--keep-metrics", action="store_true",
                        help="Do not reset data/metrics.db")
    parser.add_argument("--keep-profiles", action="store_true",
                        help="Do not reset data/student_profiles.db")
    args = parser.parse_args()

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    print(f"Reset for volunteer session (backup label: {stamp})")
    DATA.mkdir(exist_ok=True)

    actions = 0
    if not args.keep_profiles:
        actions += int(backup_and_delete("profiles", TARGETS["profiles"], stamp))
    if not args.keep_metrics:
        actions += int(backup_and_delete("metrics", TARGETS["metrics"], stamp))

    if actions == 0:
        print("Nothing to reset.")
    else:
        print(f"\nDone. {actions} DB file(s) reset. Restart the tutor to recreate empty schemas.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
