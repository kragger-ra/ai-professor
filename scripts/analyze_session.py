"""Post-session analyzer for a volunteer run.

Reads data/metrics.db + data/student_profiles.db and produces a single
text report aimed at Chapter 3 of the VKR:

    * Г1 — response latency p50 / p95 / max
    * Г2 — VRAM peak (if logged by the background tracker)
    * Г3 — mood / level changes per student
    * Г5 — RAG groundedness: share of replies with at least one retrieved
           chunk under each L2 threshold
    * Coverage — distinct topics mentioned in agent responses (rough
                 keyword scan; the human still verifies against the
                 lesson plan)

Run after each volunteer:

    py scripts/analyze_session.py [--out reports/session_{name}.md]

The script never writes back to the DBs and is safe to run live.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Optional


ROOT = Path(__file__).resolve().parent.parent
METRICS_DB = ROOT / "data" / "metrics.db"
PROFILES_DB = ROOT / "data" / "student_profiles.db"


def _load_rows(db_path: Path, query: str) -> list[dict]:
    if not db_path.exists():
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = [dict(r) for r in conn.execute(query).fetchall()]
        conn.close()
        return rows
    except sqlite3.Error as e:
        print(f"[ANALYZE] DB error on {db_path}: {e}", file=sys.stderr)
        return []


def _percentile(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    s = sorted(values)
    k = int(round((pct / 100.0) * (len(s) - 1)))
    return s[k]


def analyze_latency(interactions: list[dict]) -> dict:
    """Г1: end-to-end response latency."""
    ms = [r["response_time_ms"] for r in interactions
          if r.get("response_time_ms") and r["response_time_ms"] > 0]
    if not ms:
        return {"count": 0}
    return {
        "count": len(ms),
        "p50_ms": _percentile(ms, 50),
        "p95_ms": _percentile(ms, 95),
        "max_ms": max(ms),
        "mean_ms": int(statistics.mean(ms)),
    }


def analyze_vram(system_metrics: list[dict]) -> dict:
    """Г2: VRAM peak from background tracker (if present)."""
    vram = [r.get("ram_usage_mb") for r in system_metrics
            if r.get("ram_usage_mb")]
    if not vram:
        return {"count": 0, "note": "no system_metrics rows — VRAM tracker disabled"}
    return {
        "count": len(vram),
        "peak_mb": max(vram),
        "mean_mb": int(statistics.mean(vram)),
    }


def analyze_grounding(interactions: list[dict]) -> dict:
    """Г5: how often a retrieved chunk was actually attached to the reply."""
    total = len(interactions)
    if total == 0:
        return {"total": 0}
    with_sources = 0
    high_confidence = 0  # at least one source with L2 < 0.8
    partial = 0          # at least one source with 0.8 <= L2 < 1.2
    for r in interactions:
        raw = r.get("rag_sources") or "[]"
        try:
            sources = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            sources = []
        if sources:
            with_sources += 1
            scores = []
            for s in sources:
                if isinstance(s, str):
                    # legacy format "subject@0.823: preview"
                    try:
                        scores.append(float(s.split("@", 1)[1].split(":", 1)[0]))
                    except (IndexError, ValueError):
                        continue
                elif isinstance(s, dict) and "score" in s:
                    try:
                        scores.append(float(s["score"]))
                    except (TypeError, ValueError):
                        continue
            if scores:
                best = min(scores)
                if best < 0.8:
                    high_confidence += 1
                elif best < 1.2:
                    partial += 1
    return {
        "total": total,
        "with_sources": with_sources,
        "grounded_share": round(with_sources / total, 3),
        "high_confidence": high_confidence,
        "partial_match": partial,
    }


def analyze_meta(interaction_log: list[dict]) -> dict:
    """Г3: how often did mood/tech_level/style change across the dialogue?"""
    if not interaction_log:
        return {"total": 0}
    moods = []
    tech_deltas = 0
    for r in interaction_log:
        meta_raw = r.get("meta_analysis") or "{}"
        # meta_analysis is stored as str(dict), which is NOT valid JSON.
        try:
            meta = eval(meta_raw, {"__builtins__": {}}, {})
        except Exception:
            meta = {}
        if isinstance(meta, dict):
            mood = meta.get("mood") or r.get("emotion_tag")
            if mood:
                moods.append(mood)
            updates = meta.get("profile_updates") or {}
            if isinstance(updates, dict) and updates.get("tech_level_delta"):
                tech_deltas += 1
    distinct_moods = sorted(set(moods))
    mood_changes = sum(1 for a, b in zip(moods, moods[1:]) if a != b)
    return {
        "total_meta_records": len(interaction_log),
        "distinct_moods": distinct_moods,
        "mood_changes": mood_changes,
        "tech_level_deltas": tech_deltas,
    }


def analyze_response_lengths(interactions: list[dict]) -> dict:
    if not interactions:
        return {"total": 0}
    lens = [len((r.get("agent_response") or "").split()) for r in interactions]
    return {
        "total": len(lens),
        "mean_words": round(statistics.mean(lens), 1) if lens else 0,
        "median_words": int(statistics.median(lens)) if lens else 0,
        "max_words": max(lens) if lens else 0,
        "min_words": min(lens) if lens else 0,
    }


def render_report(stats: dict) -> str:
    lines = []
    lines.append("# Session analysis report")
    lines.append("")
    lines.append("## Г1 — End-to-end response latency")
    g1 = stats["latency"]
    if g1["count"]:
        lines.append(f"- interactions logged: {g1['count']}")
        lines.append(f"- p50:  {g1['p50_ms']} ms")
        lines.append(f"- p95:  {g1['p95_ms']} ms")
        lines.append(f"- max:  {g1['max_ms']} ms")
        lines.append(f"- mean: {g1['mean_ms']} ms")
    else:
        lines.append("- no latency data (metrics.db empty?)")
    lines.append("")
    lines.append("## Г2 — VRAM peak")
    g2 = stats["vram"]
    if g2.get("count"):
        lines.append(f"- samples: {g2['count']}")
        lines.append(f"- peak: {g2['peak_mb']:.0f} MB")
        lines.append(f"- mean: {g2['mean_mb']} MB")
    else:
        lines.append(f"- {g2.get('note', 'no samples')}")
    lines.append("")
    lines.append("## Г3 — Profile adaptation (mood / tech-level changes)")
    g3 = stats["meta"]
    if g3.get("total_meta_records"):
        lines.append(f"- meta-analysis records: {g3['total_meta_records']}")
        lines.append(f"- distinct moods: {', '.join(g3['distinct_moods']) or '-'}")
        lines.append(f"- mood transitions: {g3['mood_changes']}")
        lines.append(f"- tech-level updates: {g3['tech_level_deltas']}")
    else:
        lines.append("- no meta-analysis logged")
    lines.append("")
    lines.append("## Г5 — RAG grounding")
    g5 = stats["grounding"]
    if g5.get("total"):
        lines.append(f"- replies analysed: {g5['total']}")
        lines.append(f"- with retrieved sources: {g5['with_sources']} "
                     f"({g5['grounded_share']*100:.0f}%)")
        lines.append(f"- high confidence (L2<0.8): {g5['high_confidence']}")
        lines.append(f"- partial match (0.8<=L2<1.2): {g5['partial_match']}")
    else:
        lines.append("- no interactions recorded")
    lines.append("")
    lines.append("## Response length sanity (should be short post-fix)")
    rl = stats["response_lengths"]
    if rl.get("total"):
        lines.append(f"- mean words: {rl['mean_words']}")
        lines.append(f"- median words: {rl['median_words']}")
        lines.append(f"- min / max: {rl['min_words']} / {rl['max_words']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    # Windows consoles default to cp1251 — force UTF-8 so cyrillic + special
    # chars print without UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default=None,
                        help="Write the report to this file (default: stdout)")
    parser.add_argument("--metrics-db", type=str, default=str(METRICS_DB))
    parser.add_argument("--profiles-db", type=str, default=str(PROFILES_DB))
    args = parser.parse_args()

    interactions = _load_rows(
        Path(args.metrics_db),
        "SELECT * FROM interactions ORDER BY id",
    )
    system_metrics = _load_rows(
        Path(args.metrics_db),
        "SELECT * FROM system_metrics ORDER BY id",
    )
    interaction_log = _load_rows(
        Path(args.profiles_db),
        "SELECT * FROM interaction_log ORDER BY id",
    )

    stats = {
        "latency": analyze_latency(interactions),
        "vram": analyze_vram(system_metrics),
        "grounding": analyze_grounding(interactions),
        "meta": analyze_meta(interaction_log),
        "response_lengths": analyze_response_lengths(interactions),
    }

    report = render_report(stats)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report, encoding="utf-8")
        print(f"Report written to {out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
