"""Phase-4 smoke — depth-3 nesting cap + parked questions.

Drives the REAL agent through three nested interrupts (depth 1 -> 2 -> 3),
then attempts a 4th. The 4th must be REFUSED: the stack stays at depth 3,
the fixed cap phrase is spoken, and the refused question is parked.

Requires LM Studio (RAG embeddings) + OpenAI API reachable.

Run (from the repo root):
    python -m tutor._smoke_phase4
"""
from __future__ import annotations

import queue
import threading
import time

from tutor.brain.agent import _CAP_PHRASE, AgentThread
from tutor.brain.rag import RagModel
from tutor.util import log
from tutor._smoke_phase3 import StubPlayback, _wait


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

    def nest(question: str, expect_depth: int, interrupting: bool) -> None:
        """Ask a question, wait for it to nest to expect_depth, voice one
        sentence, then interrupt it — leaving it 'in progress'."""
        input_q.put((question, interrupting))
        _wait(lambda: agent._stack.depth == expect_depth, 45,
              f"stack depth {expect_depth}")
        cur = agent._stack.current
        _wait(lambda: cur.voiced_index >= 1, 45, "answer voiced >= 1")
        interrupt.set()
        time.sleep(1.5)                  # simulated STT latency

    # 1-3. drive the stack down to the depth-3 cap
    log("smoke", "STEP 1 — ask A (depth 1)")
    nest("Что такое вайб-кодинг?", 1, interrupting=False)
    log("smoke", "STEP 2 — interrupt -> B (depth 2)")
    nest("А что такое Plan Mode?", 2, interrupting=True)
    log("smoke", "STEP 3 — interrupt -> C (depth 3)")
    nest("А что такое Git?", 3, interrupting=True)
    answer_c = agent._stack.current

    # 4. the 4th nesting level must be refused
    log("smoke", "STEP 4 — interrupt -> D (4th level — must be refused)")
    d_question = "А что такое код-ревью?"
    input_q.put((d_question, True))   # 4th-level interruption
    _wait(
        lambda: any(_CAP_PHRASE in " ".join(x.sentences) for x in stub.received),
        25, "cap phrase spoken",
    )
    time.sleep(0.5)
    agent.stop()
    stub.stop()

    # --- assertions ------------------------------------------------------
    assert agent._stack.depth == 3, \
        f"4th level was pushed! depth={agent._stack.depth}"
    assert agent._stack.current is answer_c, \
        "current answer changed — the 4th question was not refused"
    parked = agent._stack.take_deferred()
    assert parked == d_question, f"4th question not parked: {parked!r}"

    log("smoke", "depth held at 3, cap phrase spoken, 4th question parked")
    log("smoke", "=== PHASE 4 SMOKE PASSED ===")


if __name__ == "__main__":
    main()
