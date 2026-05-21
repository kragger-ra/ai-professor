"""Playback — voices answer sentences.

PHASE 1 — stub. "Plays" each sentence by sleeping briefly and printing it,
so an interrupt can be observed cutting playback off mid-answer. The real
Vosk-server client + chunked audio playback + next-sentence prefetch land
in Phase 2.

Interrupt contract: when `interrupt` is set, playback stops the current
sentence within ~50 ms and drains any remaining queued sentences.
"""
from __future__ import annotations

import queue
import threading
import time

from tutor.util import log

_STUB_PLAY_SECONDS = 0.8   # pretend each sentence takes this long to voice
_POLL_SECONDS = 0.05       # how often to check the interrupt while "playing"


class PlaybackThread(threading.Thread):
    """Consumes answer sentences and voices them, honouring the interrupt."""

    def __init__(self, tts_q: queue.Queue, interrupt: threading.Event):
        super().__init__(name="playback", daemon=True)
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._running = True
        self.played = 0   # sentences voiced to completion (read by smoke test)

    def run(self) -> None:
        while self._running:
            try:
                sentence = self._tts_q.get(timeout=0.3)
            except queue.Empty:
                continue
            if self._interrupt.is_set():
                self._drain()
                continue
            self._play(sentence)

    def _play(self, sentence: str) -> None:
        """Pretend to voice one sentence; bail out fast on interrupt."""
        log("playback", f"> {sentence}")
        waited = 0.0
        while waited < _STUB_PLAY_SECONDS:
            if self._interrupt.is_set():
                log("playback", "x interrupted mid-sentence")
                self._drain()
                return
            time.sleep(_POLL_SECONDS)
            waited += _POLL_SECONDS
        self.played += 1

    def _drain(self) -> None:
        """Drop the rest of the interrupted answer."""
        dropped = 0
        while True:
            try:
                self._tts_q.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        if dropped:
            log("playback", f"dropped {dropped} queued sentence(s)")

    def stop(self) -> None:
        self._running = False
