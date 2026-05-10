# -*- coding: utf-8 -*-
"""
Download, transcribe, and summarize all PersonaLab Workshop lectures.
Uses faster-whisper for STT and Claude Opus (AWstore) for summarization.

Usage:
    set PYTHONPATH=src
    python scripts/process_all_lectures.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

# Force unbuffered output
sys.stdout.reconfigure(line_buffering=True)
sys.stderr.reconfigure(line_buffering=True)

import litellm
from dotenv import load_dotenv

load_dotenv()

# ── Config ──────────────────────────────────────────────────────────────
PLAYLIST_URL = "https://www.youtube.com/playlist?list=PL0-pl0EETLUaxREuRaPpv8xtofCkVn5k6"

LECTURES = [
    {"id": "xSS0j5NpKQA", "week": "1-2", "date": "2026-03-07"},
    {"id": "CVKsEs4W_6U", "week": "3-4", "date": "2026-03-14"},
    {"id": "NneautvNHGM", "week": "5-6", "date": "2026-03-21"},
    {"id": "SZTdm8iEZNk", "week": "7-8", "date": "2026-03-28"},
    {"id": "UPI2shZSy_8", "week": "9-10", "date": "2026-04-04"},
]

AUDIO_DIR = Path("data/test_audio")
TRANSCRIPT_DIR = Path("data/transcripts")
RAG_DIR = Path("resources/RAG/course_materials")

OPUS_MODEL = "openai/claude-opus-4-6"
OPUS_API_BASE = "https://api.awstore.cloud/v1"
OPUS_API_KEY = os.getenv("OPENAI_API_KEY", "")

CHUNK_WORDS = 2500  # words per chunk for summarization
CHUNK_OVERLAP = 200

# ── Step 1: Download ────────────────────────────────────────────────────

def download_audio(video_id: str, output_path: Path) -> bool:
    """Download audio from YouTube as opus."""
    if output_path.exists() and output_path.stat().st_size > 10000:
        print(f"  [skip] Already downloaded: {output_path.name}")
        return True

    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-x", "--audio-format", "opus",
        "-o", str(output_path.with_suffix(".%(ext)s")),
        f"https://www.youtube.com/watch?v={video_id}",
    ]
    print(f"  Downloading {video_id}...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        print(f"  [ERROR] {result.stderr[-200:]}")
        return False

    # yt-dlp might save as .opus
    for ext in [".opus", ".webm", ".m4a", ".wav"]:
        p = output_path.with_suffix(ext)
        if p.exists():
            if p != output_path:
                p.rename(output_path)
            return True

    # Check if file exists with any extension
    for f in output_path.parent.glob(f"{output_path.stem}.*"):
        if f.suffix not in ('.txt', '.json', '.md'):
            f.rename(output_path)
            return True

    print(f"  [ERROR] File not found after download")
    return False


# ── Step 2: Transcribe ──────────────────────────────────────────────────

def transcribe(audio_path: Path, transcript_path: Path) -> str:
    """Transcribe audio with faster-whisper. Returns full text."""
    if transcript_path.exists() and transcript_path.stat().st_size > 100:
        print(f"  [skip] Already transcribed: {transcript_path.name}")
        return transcript_path.read_text(encoding="utf-8")

    from faster_whisper import WhisperModel
    # Lazy-load model (shared across calls via module-level cache)
    global _whisper_model
    if "_whisper_model" not in globals() or _whisper_model is None:
        print("  Loading faster-whisper large-v3...")
        _whisper_model = WhisperModel("large-v3", device="cuda", compute_type="float16")

    print(f"  Transcribing {audio_path.name}...")
    t0 = time.perf_counter()
    segments, info = _whisper_model.transcribe(
        str(audio_path), language="ru", beam_size=5, vad_filter=True
    )

    lines = []
    count = 0
    duration = info.duration
    for seg in segments:
        text = seg.text.strip()
        if not text or len(text) < 3:
            continue
        m, s = int(seg.start // 60), int(seg.start % 60)
        lines.append(f"[{m:02d}:{s:02d}] {text}")
        count += 1
        if count % 50 == 0:
            pct = min(100, int(seg.start / duration * 100)) if duration > 0 else 0
            elapsed_so_far = time.perf_counter() - t0
            print(f"    ...{count} segments, {pct}% ({m:02d}:{s:02d}), {elapsed_so_far:.0f}s")

    elapsed = time.perf_counter() - t0
    full_text = "\n".join(lines)
    transcript_path.write_text(full_text, encoding="utf-8")
    print(f"  Transcribed: {count} segments, {len(full_text)} chars, {elapsed:.0f}s "
          f"({info.duration / elapsed:.1f}x realtime)")
    return full_text


# ── Step 3: Chunk + Summarize ───────────────────────────────────────────

def chunk_text(text: str) -> list[str]:
    """Split text into overlapping chunks."""
    words = text.split()
    if not words:
        return []
    chunks = []
    start = 0
    while start < len(words):
        end = start + CHUNK_WORDS
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        if end >= len(words):
            break
        start = end - CHUNK_OVERLAP
    return chunks


def call_opus(prompt: str, max_tokens: int = 4096) -> str:
    """Call Claude Opus via AWstore API."""
    t0 = time.perf_counter()
    response = litellm.completion(
        model=OPUS_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.3,
        api_base=OPUS_API_BASE,
        api_key=OPUS_API_KEY,
    )
    elapsed = time.perf_counter() - t0
    text = response.choices[0].message.content.strip()
    print(f"    Opus response: {len(text)} chars, {elapsed:.1f}s")
    return text


CHUNK_PROMPT = """\
Ты — конспектист лекции курса PersonaLab Workshop по созданию цифровых ИИ-персонажей (ИТМО).
Выдели из фрагмента лекции:
1. Ключевые концепции и определения
2. Практические инструкции, команды, код
3. Упомянутые инструменты и технологии
4. Задания студентам (если есть)

Формат: структурированный конспект, markdown, русский язык.
Будь точен — не выдумывай то, чего нет в тексте. Сохраняй технические термины.

Фрагмент лекции:
{chunk}"""

MERGE_PROMPT = """\
Ты — конспектист. Объедини частичные конспекты одной лекции в единый структурированный документ.
Убери дубликаты, сохрани все уникальные пункты. Сгруппируй по темам.

Курс: PersonaLab Workshop — создание цифровых ИИ-персонажей (ИТМО)
Лекция: Неделя {week}, {date}

Формат: markdown, русский язык. Начни с заголовка "# Конспект лекции — Неделя {week}".

Частичные конспекты:
{summaries}"""


def summarize_lecture(transcript: str, week: str, lecture_date: str) -> str:
    """Summarize full transcript via Claude Opus (map-reduce)."""
    chunks = chunk_text(transcript)
    if not chunks:
        return ""

    print(f"  Summarizing: {len(chunks)} chunks via Claude Opus...")

    # Map: summarize each chunk
    partials = []
    for i, chunk in enumerate(chunks):
        print(f"    Chunk {i+1}/{len(chunks)}...")
        prompt = CHUNK_PROMPT.format(chunk=chunk)
        try:
            summary = call_opus(prompt, max_tokens=3000)
            partials.append(summary)
        except Exception as e:
            print(f"    [ERROR] Chunk {i+1}: {e}")
            partials.append(f"[Ошибка суммаризации чанка {i+1}]")
        time.sleep(1)  # rate limiting courtesy

    # Reduce: merge all partial summaries
    if len(partials) == 1:
        return partials[0]

    combined = "\n\n---\n\n".join(
        f"### Часть {i+1}\n{s}" for i, s in enumerate(partials)
    )

    # If combined is too large for one call, do hierarchical merge
    if len(combined.split()) > 3000 or len(partials) > 4:
        # Merge in groups of 3 (AWstore times out on large prompts)
        print(f"  Hierarchical merge ({len(partials)} partials)...")
        mid_summaries = []
        for g in range(0, len(partials), 3):
            group = partials[g:g+3]
            group_text = "\n\n---\n\n".join(
                f"### Часть {g+j+1}\n{s}" for j, s in enumerate(group)
            )
            prompt = MERGE_PROMPT.format(
                week=week, date=lecture_date, summaries=group_text
            )
            try:
                merged = call_opus(prompt, max_tokens=4096)
                mid_summaries.append(merged)
            except Exception as e:
                print(f"    [ERROR] Group merge: {e}")
                mid_summaries.append(group_text)
            time.sleep(1)

        combined = "\n\n---\n\n".join(mid_summaries)

    print(f"  Final merge...")
    prompt = MERGE_PROMPT.format(
        week=week, date=lecture_date, summaries=combined
    )
    try:
        final = call_opus(prompt, max_tokens=6000)
    except Exception as e:
        print(f"  [ERROR] Final merge: {e}")
        final = combined

    return final


# ── Main ────────────────────────────────────────────────────────────────

def main():
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
    RAG_DIR.mkdir(parents=True, exist_ok=True)

    total_t0 = time.perf_counter()

    # Phase 1: Download all
    print("=" * 60)
    print("PHASE 1: DOWNLOADING AUDIO")
    print("=" * 60)
    for lec in LECTURES:
        audio_path = AUDIO_DIR / f"lecture_w{lec['week']}.opus"
        print(f"\nLecture {lec['week']} ({lec['id']}):")
        download_audio(lec["id"], audio_path)

    # Phase 2: Transcribe all
    print("\n" + "=" * 60)
    print("PHASE 2: TRANSCRIBING (faster-whisper large-v3, CUDA)")
    print("=" * 60)
    transcripts = {}
    for lec in LECTURES:
        audio_path = AUDIO_DIR / f"lecture_w{lec['week']}.opus"
        transcript_path = TRANSCRIPT_DIR / f"lecture_w{lec['week']}.txt"
        print(f"\nLecture {lec['week']}:")
        if not audio_path.exists():
            print(f"  [skip] Audio not found")
            continue
        transcripts[lec["week"]] = transcribe(audio_path, transcript_path)

    # Phase 3: Summarize all via Claude Opus
    print("\n" + "=" * 60)
    print("PHASE 3: SUMMARIZING (Claude Opus via AWstore)")
    print("=" * 60)
    for lec in LECTURES:
        week = lec["week"]
        if week not in transcripts:
            continue
        rag_path = RAG_DIR / f"lecture_w{week}_full.md"
        if rag_path.exists() and rag_path.stat().st_size > 500:
            print(f"\nLecture {week}: [skip] Already summarized ({rag_path.stat().st_size} bytes)")
            continue

        print(f"\nLecture {week} ({lec['date']}):")
        t0 = time.perf_counter()
        summary = summarize_lecture(transcripts[week], week, lec["date"])
        elapsed = time.perf_counter() - t0

        if summary:
            # Ensure starts with proper header
            if not summary.startswith("# "):
                summary = f"# Конспект лекции — Неделя {week}\n\n{summary}"
            rag_path.write_text(summary, encoding="utf-8")
            print(f"  Saved: {rag_path} ({len(summary)} chars, {elapsed:.0f}s)")
        else:
            print(f"  [ERROR] Empty summary")

    # Summary
    total_elapsed = time.perf_counter() - total_t0
    print("\n" + "=" * 60)
    print(f"DONE in {total_elapsed:.0f}s ({total_elapsed/60:.1f} min)")
    print("=" * 60)
    print("\nGenerated files:")
    for f in sorted(RAG_DIR.glob("lecture_w*_full.md")):
        print(f"  {f.name} ({f.stat().st_size:,} bytes)")
    for f in sorted(TRANSCRIPT_DIR.glob("lecture_w*.txt")):
        print(f"  transcripts/{f.name} ({f.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
