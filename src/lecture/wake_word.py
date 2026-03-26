"""
Wake word detection on STT transcript level.

Detects trigger phrases in Russian STT output to activate the agent.
Uses keyword spotting (not a classical wake word engine) because
Porcupine/Snowboy don't support Russian phrases.

Config: resources/Customization/wake_words.yml
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path("resources/Customization/wake_words.yml")

# Verbs that indicate direct address (filter out "профессор Иванов доказал...")
_ADDRESS_VERBS = re.compile(
    r"(подскажи|скажи|ответь|расскажи|объясни|помоги|покажи|повтори)",
    re.IGNORECASE,
)

CAPTURE_WINDOW_SEC = 15.0


@dataclass
class WakeWordConfig:
    """Loaded from wake_words.yml."""

    exact: list[str] = field(default_factory=list)
    prefix: list[str] = field(default_factory=list)
    name: list[str] = field(default_factory=list)
    capture_window_sec: float = CAPTURE_WINDOW_SEC

    @classmethod
    def from_yaml(cls, path: Path | str = DEFAULT_CONFIG_PATH) -> "WakeWordConfig":
        path = Path(path)
        if not path.exists():
            logger.warning("Wake word config not found at %s, using defaults", path)
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        ww = data.get("wake_words", data)
        return cls(
            exact=[s.lower() for s in ww.get("exact", [])],
            prefix=[s.lower() for s in ww.get("prefix", [])],
            name=[s.lower() for s in ww.get("name", [])],
            capture_window_sec=float(ww.get("capture_window_sec", CAPTURE_WINDOW_SEC)),
        )


@dataclass
class WakeWordResult:
    """Result of wake word detection."""

    triggered: bool
    matched_phrase: Optional[str] = None
    extracted_query: Optional[str] = None


class WakeWordDetector:
    """
    Stateful detector that works on streaming STT segments.

    After a wake word is detected, all subsequent text within
    ``capture_window_sec`` is collected as the student's question.
    """

    def __init__(self, config: WakeWordConfig | None = None):
        self.config = config or WakeWordConfig.from_yaml()
        self._capturing = False
        self._capture_start: float = 0.0
        self._capture_buffer: list[str] = []
        self._last_match: Optional[str] = None

    def reset(self) -> None:
        self._capturing = False
        self._capture_start = 0.0
        self._capture_buffer.clear()
        self._last_match = None

    @property
    def is_capturing(self) -> bool:
        if self._capturing and (time.time() - self._capture_start > self.config.capture_window_sec):
            self._capturing = False
        return self._capturing

    def process_segment(self, text: str) -> WakeWordResult:
        """
        Process a single STT segment.

        Returns a WakeWordResult. When the capture window ends (or a new
        wake word is detected while capturing), ``extracted_query`` contains
        the accumulated question text.
        """
        text_stripped = text.strip()
        text_lower = text_stripped.lower()
        now = time.time()

        # If we are currently capturing question text
        if self._capturing:
            if now - self._capture_start > self.config.capture_window_sec:
                # Window expired — return collected question
                query = " ".join(self._capture_buffer)
                self._capturing = False
                self._capture_buffer.clear()
                return WakeWordResult(
                    triggered=True,
                    matched_phrase=self._last_match,
                    extracted_query=query,
                )
            # Still within window — accumulate text
            self._capture_buffer.append(text_stripped)
            return WakeWordResult(triggered=False)

        # Try to detect a wake word
        match = self._detect(text_lower, text_stripped)
        if match is not None:
            matched_phrase, remainder = match
            self._last_match = matched_phrase
            self._capturing = True
            self._capture_start = now
            self._capture_buffer.clear()
            if remainder:
                self._capture_buffer.append(remainder)
            logger.info("Wake word detected: '%s'", matched_phrase)
            return WakeWordResult(triggered=False)

        return WakeWordResult(triggered=False)

    def force_finish(self) -> WakeWordResult:
        """Force-finish the capture window (e.g. on silence timeout)."""
        if not self._capturing:
            return WakeWordResult(triggered=False)
        query = " ".join(self._capture_buffer)
        self._capturing = False
        self._capture_buffer.clear()
        return WakeWordResult(
            triggered=True,
            matched_phrase=self._last_match,
            extracted_query=query,
        )

    # ------------------------------------------------------------------
    def _detect(self, text_lower: str, text_original: str) -> Optional[tuple[str, str]]:
        """
        Try to match wake word patterns.

        Returns ``(matched_phrase, remainder_text)`` or ``None``.
        """
        # 1. Exact match
        for phrase in self.config.exact:
            if phrase in text_lower:
                idx = text_lower.index(phrase) + len(phrase)
                remainder = text_original[idx:].strip()
                return (phrase, remainder)

        # 2. Prefix match (e.g. "профессор, <question>")
        for prefix in self.config.prefix:
            if text_lower.startswith(prefix):
                remainder = text_original[len(prefix):].strip()
                return (prefix, remainder)

        # 3. Name match
        for name in self.config.name:
            if name in text_lower:
                # Verify it's a direct address, not a mention in lecture context.
                # Check if there's an address verb nearby or the name is at the
                # start of the segment.
                name_idx = text_lower.index(name)
                context_after = text_lower[name_idx + len(name):]
                if name_idx == 0 or _ADDRESS_VERBS.search(context_after):
                    remainder = text_original[name_idx + len(name):].strip(" ,")
                    return (name, remainder)

        return None
