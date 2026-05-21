"""Phase-3 smoke — interrupt + resume on the answer stack.

Drives the REAL agent (real meta + RAG + LLM) with a STUB playback that
voices Answer objects by advancing voiced_index — no audio hardware.

Scenario:
    ask A  ->  interrupt mid-answer  ->  ask sub-question B
           ->  say "продолжай"  ->  A resumes from where it stopped.

Asserts: A continues past the cut, it is the SAME Answer object (resume
made no new LLM call), and the stack pushed (depth 2) then popped (depth 1).

Requires LM Studio (RAG embeddings) + OpenAI API reachable.

Run (from the repo root):
    python -m tutor._smoke_phase3
"""
from __future__ import annotations

import queue
import threading
import time

from tutor.brain.agent import AgentThread
from tutor.brain.rag import RagModel
from tutor.util import log


class StubPlayback(threading.Thread):
    """Voices Answer objects by advancing voiced_index — no real audio."""

    def __init__(self, tts_q, interrupt, per_sentence: float = 1.0):
        super().__init__(name="stub-playback", daemon=True)
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._per = per_sentence
        self._running = True
        self.received: list = []     # Answers seen, in order

    def run(self) -> None:
        while self._running:
            try:
                ans = self._tts_q.get(timeout=0.2)
            except queue.Empty:
                continue
            if self._interrupt.is_set():
                continue
            self.received.append(ans)
            while self._running and not self._interrupt.is_set():
                if ans.voiced_index < len(ans.sentences):
                    # "voice" one sentence — sleep in small steps so even a
                    # brief interrupt pulse is caught (like the real watcher).
                    waited = 0.0
                    while waited < self._per and not self._interrupt.is_set():
                        time.sleep(0.05)
                        waited += 0.05
                    if self._interrupt.is_set():
                        break                        # cut — do not advance
                    ans.mark_voiced(1)
                elif ans.generating:
                    time.sleep(0.05)
                else:
                    break

    def stop(self) -> None:
        self._running = False


def _wait(cond, timeout: float, what: str) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cond():
            return
        time.sleep(0.1)
    raise AssertionError(f"timeout waiting for: {what}")


def main() -> None:
    input_q: queue.Queue = queue.Queue()
    tts_q: queue.Queue = queue.Queue()
    interrupt = threading.Event()

    log("smoke", "loading RAG model...")
    rag = RagModel()
    agent = AgentThread(input_q, tts_q, interrupt, rag)
    stub = StubPlayback(tts_q, interrupt, per_sentence=1.0)
    agent.start()
    stub.start()

    # 1. ask A
    log("smoke", "STEP 1 — ask A")
    input_q.put(("Что такое вайб-кодинг?", False))
    _wait(lambda: agent._stack.depth >= 1, 30, "A on the stack")
    answer_a = agent._stack.current

    # 2. let ~1 sentence of A voice, then interrupt
    _wait(lambda: answer_a.voiced_index >= 1, 30, "A voiced >= 1 sentence")
    assert not answer_a.fully_voiced, "A finished before we could interrupt"
    cut_at = answer_a.voiced_index
    log("smoke", f"STEP 2 — interrupt A after {cut_at} sentence(s)")

    # 3. interrupt, then — after a simulated STT delay — ask sub-question B.
    #    The delay keeps the interrupt set realistically long: in the real
    #    system it stays set from speech onset until STT delivers the text.
    interrupt.set()
    time.sleep(1.5)
    input_q.put(("А что такое Plan Mode?", True))   # interruption
    _wait(lambda: agent._stack.depth >= 2, 30, "B nested on the stack")
    answer_b = agent._stack.current
    assert answer_b is not answer_a, "B should be a new Answer"
    log("smoke", "STEP 3 — B nested, stack depth 2")

    # 4. let B finish voicing
    _wait(lambda: answer_b.fully_voiced, 45, "B fully voiced")
    log("smoke", "STEP 4 — B fully voiced")

    # 5. resume
    log("smoke", "STEP 5 — say 'продолжай'")
    input_q.put(("продолжай", False))
    _wait(lambda: agent._stack.depth == 1, 20, "stack popped back to A")
    _wait(lambda: answer_a.fully_voiced, 30, "A resumed to completion")

    agent.stop()
    stub.stop()

    # --- assertions ------------------------------------------------------
    assert agent._stack.current is answer_a, "A must be current after resume"
    assert answer_a.voiced_index > cut_at, "A did not continue past the cut"
    assert answer_a.fully_voiced, "A not fully voiced after resume"
    a_count = sum(1 for x in stub.received if x is answer_a)
    assert a_count >= 2, f"A must reach playback twice (initial + resume), got {a_count}"
    assert answer_b in stub.received, "B never reached playback"

    log("smoke", f"A: voiced {cut_at} -> interrupt -> resumed -> "
                 f"{answer_a.voiced_index} (same object, no LLM call)")
    log("smoke", "=== PHASE 3 SMOKE PASSED ===")


if __name__ == "__main__":
    main()
