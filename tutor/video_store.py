"""Storage layer for transcribed videos — a registry of (video file +
time-anchored transcript + metadata) triples that the agent can query.

Layout on disk:

  data/videos/registry.json            — index of all known videos
  data/videos/<video_id>/video.<ext>   — the original media file
  data/videos/<video_id>/transcript.json
  data/videos/<video_id>/meta.json

The video_id is a hex hash of the absolute source path + mtime, so
re-loading the same file is idempotent. ``transcript.json`` is a list
of ``{start, end, text}`` records produced by
``tutor.audio.video_transcribe.transcribe_video``.

The store is read-only from the agent's perspective: it lists what's
been transcribed and exposes per-video segment access by time and by
text. Writes happen via ``register_transcribed`` after a transcription
job completes.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from tutor.audio.video_transcribe import (
    Segment, segment_at, segments_from_jsonable, segments_in_range,
    segments_to_jsonable,
)
from tutor.util import log

_REPO_ROOT = Path(__file__).resolve().parent.parent
_VIDEOS_DIR = _REPO_ROOT / "data" / "videos"
_REGISTRY_PATH = _VIDEOS_DIR / "registry.json"


@dataclass
class VideoEntry:
    video_id: str
    name: str                       # display name (file name, sans path)
    source_path: str                # absolute path of the original media
    stored_path: str                # absolute path inside data/videos/<id>/
    transcript_path: str            # absolute path to transcript.json
    duration_s: float = 0.0
    segments_count: int = 0
    note: str = ""                  # user-supplied or LLM-generated summary
    # Lazy: segments themselves are loaded on demand to keep the registry slim
    _segments: Optional[List[Segment]] = field(default=None, repr=False)

    def as_dict(self) -> dict:
        return {
            "video_id": self.video_id,
            "name": self.name,
            "source_path": self.source_path,
            "stored_path": self.stored_path,
            "transcript_path": self.transcript_path,
            "duration_s": round(self.duration_s, 3),
            "segments_count": self.segments_count,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VideoEntry":
        return cls(
            video_id=str(d.get("video_id", "")),
            name=str(d.get("name", "")),
            source_path=str(d.get("source_path", "")),
            stored_path=str(d.get("stored_path", "")),
            transcript_path=str(d.get("transcript_path", "")),
            duration_s=float(d.get("duration_s", 0.0) or 0.0),
            segments_count=int(d.get("segments_count", 0) or 0),
            note=str(d.get("note", "")),
        )

    def segments(self) -> List[Segment]:
        if self._segments is not None:
            return self._segments
        try:
            data = json.loads(Path(self.transcript_path).read_text(encoding="utf-8"))
            self._segments = segments_from_jsonable(data)
        except Exception as exc:
            log("video", f"transcript load failed for {self.name}: {exc}")
            self._segments = []
        return self._segments


def _video_id_for(path: Path) -> str:
    """Stable id from absolute path + mtime — repeated transcription of
    the same file produces the same id (and overwrites the stored copy)."""
    try:
        st = path.stat()
        key = f"{path.resolve()}::{int(st.st_mtime)}"
    except OSError:
        key = str(path.resolve())
    return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


class VideoStore:
    """Process-shared registry of transcribed videos. Persisted to
    ``data/videos/registry.json``; thread-safe via an internal lock."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: dict[str, VideoEntry] = {}
        _VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
        self._load()

    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not _REGISTRY_PATH.exists():
            return
        try:
            data = json.loads(_REGISTRY_PATH.read_text(encoding="utf-8"))
            for d in data.get("videos", []):
                entry = VideoEntry.from_dict(d)
                if entry.video_id:
                    self._entries[entry.video_id] = entry
        except Exception as exc:
            log("video", f"registry load failed: {exc}")

    def _save(self) -> None:
        try:
            _REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            payload = {"videos": [e.as_dict() for e in self._entries.values()]}
            _REGISTRY_PATH.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            log("video", f"registry save failed: {exc}")

    # ------------------------------------------------------------------
    # Mutators
    # ------------------------------------------------------------------

    def register_transcribed(self, source_path: Path,
                             segments: List[Segment],
                             *, note: str = "",
                             copy_into_store: bool = True) -> VideoEntry:
        """Persist a freshly-transcribed video to the store.

        ``copy_into_store=True`` (default) copies the source media file
        into ``data/videos/<id>/`` so the store is self-contained; pass
        False to leave the source where it is (the entry then just
        references the original path)."""
        source_path = Path(source_path).resolve()
        vid = _video_id_for(source_path)
        video_dir = _VIDEOS_DIR / vid
        video_dir.mkdir(parents=True, exist_ok=True)

        if copy_into_store:
            target = video_dir / f"video{source_path.suffix.lower()}"
            try:
                if not target.exists() or target.stat().st_size != source_path.stat().st_size:
                    shutil.copy2(source_path, target)
            except Exception as exc:
                log("video", f"copy into store failed: {exc} — referencing in place")
                target = source_path
        else:
            target = source_path

        transcript_path = video_dir / "transcript.json"
        transcript_path.write_text(
            json.dumps(segments_to_jsonable(segments),
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        duration = segments[-1].end if segments else 0.0
        meta_path = video_dir / "meta.json"
        meta = {
            "name": source_path.name,
            "source_path": str(source_path),
            "duration_s": round(duration, 3),
            "segments_count": len(segments),
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2),
                             encoding="utf-8")

        entry = VideoEntry(
            video_id=vid,
            name=source_path.name,
            source_path=str(source_path),
            stored_path=str(target),
            transcript_path=str(transcript_path),
            duration_s=duration,
            segments_count=len(segments),
            note=note,
        )
        with self._lock:
            self._entries[vid] = entry
            self._save()
        return entry

    def remove(self, video_id: str, *, delete_files: bool = False) -> Optional[VideoEntry]:
        with self._lock:
            entry = self._entries.pop(video_id, None)
            self._save()
        if entry and delete_files:
            video_dir = _VIDEOS_DIR / video_id
            try:
                shutil.rmtree(video_dir)
            except Exception:
                pass
        return entry

    def set_note(self, video_id: str, note: str) -> None:
        with self._lock:
            entry = self._entries.get(video_id)
            if entry is not None:
                entry.note = note
                self._save()

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def list(self) -> List[VideoEntry]:
        with self._lock:
            return list(self._entries.values())

    def get(self, video_id: str) -> Optional[VideoEntry]:
        with self._lock:
            return self._entries.get(video_id)

    def find_by_name(self, query: str) -> List[VideoEntry]:
        q = query.strip().lower()
        if not q:
            return []
        with self._lock:
            return [e for e in self._entries.values()
                    if q in e.name.lower() or q in e.note.lower()]

    # ------------------------------------------------------------------
    # Query helpers — exposed so the agent can answer 'what was at 5:20'
    # ------------------------------------------------------------------

    @staticmethod
    def segment_at_time(entry: VideoEntry, time_s: float) -> Optional[Segment]:
        return segment_at(entry.segments(), time_s)

    @staticmethod
    def segments_in_range(entry: VideoEntry,
                          start_s: float, end_s: float) -> List[Segment]:
        return segments_in_range(entry.segments(), start_s, end_s)

    @staticmethod
    def search_text(entry: VideoEntry, query: str,
                    max_hits: int = 10) -> List[Segment]:
        """Naive substring search over segment text. Good enough for short
        queries against a tens-of-minutes lecture; for thousand-of-segments
        archives swap in BM25 later."""
        q = query.strip().lower()
        if not q:
            return []
        hits = [s for s in entry.segments() if q in s.text.lower()]
        return hits[:max_hits]
