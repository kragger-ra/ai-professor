"""The agent — the brain of the tutor.

PHASE 1 — stub. It turns each utterance into a fixed multi-sentence answer
so the playback path has something interruptible to drive. The real pipeline
lands incrementally:
  - Phase 2: meta-agent (pre-flight) + RAG + prompt + streaming LLM, and the
             `Answer` object that decouples generation from voicing.
  - Phase 3-4: the interrupt-aware answer stack (nesting, resume).
  - Phase 5: command router, checker / mini-lecture, adaptive register.
"""
from __future__ import annotations

import queue
import threading

from tutor.util import log


class AgentThread(threading.Thread):
    """Consumes student utterances, produces answer sentences for playback."""

    def __init__(self, input_q: queue.Queue, tts_q: queue.Queue,
                 interrupt: threading.Event):
        super().__init__(name="agent", daemon=True)
        self._input_q = input_q
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                utterance = self._input_q.get(timeout=0.3)
            except queue.Empty:
                continue
            # A new utterance is being handled: the interrupt the gate raised
            # has done its job (playback already stopped + drained). Clear it
            # so the sentences of THIS answer are allowed to play.
            self._interrupt.clear()
            log("agent", f"handling: {utterance!r}")
            self._answer(utterance)

    def _answer(self, utterance: str) -> None:
        """Phase-1 stub answer: five canned sentences pushed to playback.

        Phase 2 replaces this with: meta-agent + RAG -> prompt -> streaming
        LLM filling an `Answer` object sentence by sentence.
        """
        for i in range(1, 6):
            if self._interrupt.is_set():
                log("agent", "interrupted — stop generating")
                return
            self._tts_q.put(f"Ответ на «{utterance}», предложение {i}.")
        log("agent", "answer fully queued")

    def stop(self) -> None:
        self._running = False
