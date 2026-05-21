"""Phase-2 smoke — the brain pipeline end to end, no audio hardware.

Injects a text question, runs the REAL meta-agent + RAG + LLM stream, and
checks the professor produces answer sentences.

Requires running services:
  - LM Studio embeddings server  (RAG retrieval)
  - OpenAI API reachable          (LLM + meta-agent)

Run (from the repo root):
    python -m tutor._smoke_phase2
"""
from __future__ import annotations

import queue
import threading
import time

from tutor.brain.agent import AgentThread
from tutor.brain.rag import RagModel
from tutor.util import log


def main() -> None:
    input_q: queue.Queue = queue.Queue()
    tts_q: queue.Queue = queue.Queue()
    interrupt = threading.Event()

    log("smoke", "loading RAG model...")
    rag = RagModel()

    agent = AgentThread(input_q, tts_q, interrupt, rag)
    agent.start()

    question = "Что такое вайб-кодинг?"
    log("smoke", f"asking: {question!r}")
    input_q.put((question, False))   # (text, was_interruption)

    # The agent puts one Answer object on tts_q per turn; its generator
    # thread fills answer.sentences as the LLM streams.
    answer = tts_q.get(timeout=45)
    deadline = time.time() + 45
    while answer.generating and time.time() < deadline:
        time.sleep(0.2)
    agent.stop()

    assert answer.sentences, "no answer sentences were produced"
    text = " ".join(answer.sentences).strip()
    log("smoke", f"answer ({len(answer.sentences)} sentence(s)): {text}")
    assert len(text) > 20, "answer suspiciously short"
    log("smoke", "=== PHASE 2 SMOKE PASSED ===")


if __name__ == "__main__":
    main()
