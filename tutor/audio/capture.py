"""Audio capture + push-to-talk gate.

PHASE 1 — console stub. Each typed line simulates one push-to-talk turn:
the student opens the gate (which fires the interrupt so any in-progress
playback stops at once), speaks, and releases. The utterance is then handed
to the agent via `input_q`.

PHASE 2 will replace this with a real microphone + energy VAD + faster-whisper
behind the same push-to-talk gate and the same two outputs:
  - `interrupt.set()` the instant the gate opens,
  - the finished utterance string onto `input_q`.
"""
from __future__ import annotations

import queue
import threading

from tutor.util import log


class ConsoleCapture(threading.Thread):
    """Phase-1 capture stub: stdin lines -> utterances.

    Contract (kept identical for the real Phase-2 capture):
      * gate opens  -> `interrupt.set()` immediately
      * utterance ready -> `input_q.put(text)`
    """

    def __init__(self, input_q: queue.Queue, interrupt: threading.Event):
        super().__init__(name="capture", daemon=True)
        self._input_q = input_q
        self._interrupt = interrupt
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                text = input()
            except EOFError:
                break
            text = text.strip()
            if not text:
                continue
            # The gate opening IS the interrupt signal — fired before the
            # utterance is even delivered, so the professor stops talking
            # the instant the student does.
            self._interrupt.set()
            log("capture", f"gate opened -> utterance: {text!r}")
            self._input_q.put(text)

    def stop(self) -> None:
        self._running = False
