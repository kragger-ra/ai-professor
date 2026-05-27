"""Filler cues — short pre-rendered audio played while the agent thinks.

Goal: cover the silence gap between "user finished talking" and "first TTS
sentence plays". That gap is meta-agent + RAG + LLM-first-token + Vosk
synthesis — typically 1-3 seconds. A short cue ("Так..." / "Минутку.")
played the instant the question arrives makes the wait feel responsive.

Cues are rendered ONCE at startup via Vosk and kept in memory as raw PCM.
At runtime the agent picks a cue and pushes it onto the TTS queue; the
playback thread plays it like a regular Answer, but without calling Vosk.
"""
from __future__ import annotations

import random
import threading
from dataclasses import dataclass
from typing import List, Optional

import numpy as np

from tutor.util import log

# Short, neutral fillers — must NOT carry meaning that could mislead. Avoid
# anything that sounds like a real answer ("конечно", "хорошо") so a student
# who interrupts before the real answer arrives isn't confused.
DEFAULT_FILLERS: List[str] = [
    "Так...",
    "Минутку.",
    "Сейчас.",
    "Хм, секунду.",
    "Дайте подумать.",
    "Так, смотрите.",
    "Ага.",
]


@dataclass
class FillerCue:
    """Pre-rendered short audio cue, played as a queue item."""
    audio: np.ndarray
    sr: int
    text: str


class FillerLibrary:
    """Renders a fixed set of filler phrases via Vosk on first warm_up()."""

    def __init__(self, phrases: Optional[List[str]] = None):
        self._phrases = list(phrases) if phrases else list(DEFAULT_FILLERS)
        self._cues: List[FillerCue] = []
        self._last_idx: int = -1
        self._lock = threading.Lock()
        self._warmed = False

    def warm_up(self) -> None:
        """Synthesize every phrase once; safe to call multiple times."""
        with self._lock:
            if self._warmed:
                return
            self._warmed = True
        # Vosk import is local so a missing TTS server doesn't break import.
        from tutor.tts.vosk_client import vosk_tts_sentence
        rendered: List[FillerCue] = []
        for text in self._phrases:
            try:
                audio, sr = vosk_tts_sentence(text, "neutral")
            except Exception as exc:
                log("filler", f"render failed for {text!r}: "
                              f"{type(exc).__name__}: {exc}")
                continue
            if audio is None or len(audio) == 0:
                log("filler", f"render returned empty audio for {text!r}")
                continue
            rendered.append(FillerCue(audio=audio, sr=sr, text=text))
        with self._lock:
            self._cues = rendered
        log("filler", f"warmed {len(rendered)}/{len(self._phrases)} cues")

    def pick(self) -> Optional[FillerCue]:
        """Return one cue, avoiding an immediate repeat. None if not warmed."""
        with self._lock:
            cues = self._cues
            if not cues:
                return None
            n = len(cues)
            idx = random.randrange(n)
            if idx == self._last_idx and n > 1:
                idx = (idx + 1) % n
            self._last_idx = idx
            return cues[idx]
