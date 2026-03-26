"""
Post-lecture summarization pipeline.

Takes transcript chunks from TranscriptBuffer, summarizes each via LLM,
then merges partial summaries into a final lecture summary.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date
from pathlib import Path
from typing import Optional

from litellm import completion

logger = logging.getLogger(__name__)

SUMMARIES_DIR = Path("resources/RAG/lecture_summaries")

CHUNK_SUMMARY_PROMPT = """\
Ты — конспектист лекции по созданию ИИ-персонажей (PersonaLab Workshop).
Выдели из фрагмента лекции:
1. Ключевые концепции и определения
2. Практические инструкции и команды
3. Упомянутые инструменты и технологии
4. Задания студентам

Формат: структурированный конспект, русский язык.
Будь точен — не выдумывай то, чего нет в тексте.

Фрагмент лекции:
{chunk}
"""

MERGE_PROMPT = """\
Ты — конспектист. Объедини несколько частичных конспектов одной лекции \
в единый структурированный конспект. Убери дубликаты, сохрани все уникальные \
пункты. Формат: markdown, русский язык.

Неделя: {week}
Дата: {date}

Частичные конспекты:
{summaries}
"""


class LectureSummarizer:
    """
    Summarizes lecture transcript using map-reduce pattern.

    1. Each chunk → LLM → partial summary  (map)
    2. All partial summaries → LLM → final summary  (reduce)
    """

    def __init__(
        self,
        model: Optional[str] = None,
        summaries_dir: Path | str = SUMMARIES_DIR,
        max_tokens: int = 2048,
    ):
        self.model = model or os.getenv("CORE_LLM_MODEL_NAME", "mistral/pixtral-large-latest")
        self.summaries_dir = Path(summaries_dir)
        self.summaries_dir.mkdir(parents=True, exist_ok=True)
        self.max_tokens = max_tokens

    def summarize_chunks(self, chunks: list[str]) -> list[str]:
        """Summarize each chunk independently (map phase)."""
        partial_summaries: list[str] = []
        for i, chunk in enumerate(chunks):
            logger.info("Summarizing chunk %d/%d...", i + 1, len(chunks))
            prompt = CHUNK_SUMMARY_PROMPT.format(chunk=chunk)
            try:
                response = completion(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    max_tokens=self.max_tokens,
                )
                summary = response.choices[0].message.content.strip()
                partial_summaries.append(summary)
            except Exception:
                logger.exception("Failed to summarize chunk %d", i + 1)
                partial_summaries.append(f"[Ошибка суммаризации чанка {i + 1}]")
        return partial_summaries

    def merge_summaries(
        self,
        partial_summaries: list[str],
        lecture_week: int,
        lecture_date: Optional[date] = None,
    ) -> str:
        """Merge partial summaries into one final summary (reduce phase)."""
        lecture_date = lecture_date or date.today()
        combined = "\n\n---\n\n".join(
            f"### Часть {i + 1}\n{s}" for i, s in enumerate(partial_summaries)
        )
        prompt = MERGE_PROMPT.format(
            week=lecture_week,
            date=lecture_date.isoformat(),
            summaries=combined,
        )
        try:
            response = completion(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=self.max_tokens * 2,
            )
            return response.choices[0].message.content.strip()
        except Exception:
            logger.exception("Failed to merge summaries")
            return combined

    def summarize(
        self,
        chunks: list[str],
        lecture_week: int,
        lecture_date: Optional[date] = None,
        save: bool = True,
    ) -> str:
        """
        Full summarization pipeline: map chunks → reduce → save.

        Returns the final summary text.
        """
        if not chunks:
            logger.warning("No chunks to summarize")
            return ""

        lecture_date = lecture_date or date.today()

        # Map
        partial = self.summarize_chunks(chunks)

        # Reduce (skip if only one chunk)
        if len(partial) == 1:
            final_summary = partial[0]
        else:
            final_summary = self.merge_summaries(partial, lecture_week, lecture_date)

        # Save
        if save:
            path = self._save(final_summary, lecture_week, lecture_date)
            logger.info("Summary saved to %s", path)

        return final_summary

    def _save(self, summary: str, lecture_week: int, lecture_date: date) -> Path:
        """Save summary as markdown file."""
        filename = f"week{lecture_week}_{lecture_date.isoformat()}.md"
        path = self.summaries_dir / filename
        header = f"# Конспект лекции — Неделя {lecture_week} ({lecture_date.isoformat()})\n\n"
        path.write_text(header + summary, encoding="utf-8")

        # Also save metadata as JSON sidecar
        meta_path = path.with_suffix(".json")
        meta = {
            "lecture_week": lecture_week,
            "date": lecture_date.isoformat(),
            "model": self.model,
            "num_chunks": 0,  # filled by caller if needed
        }
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
