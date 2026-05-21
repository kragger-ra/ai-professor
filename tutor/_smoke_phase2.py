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
    input_q.put(question)

    # Collect answer sentences: wait up to 45s; a 1.5s gap after the first
    # sentence means the answer is complete.
    sentences: list = []
    deadline = time.time() + 45
    while time.time() < deadline:
        try:
            sentences.append(tts_q.get(timeout=1.5))
        except queue.Empty:
            if sentences:
                break
    agent.stop()

    assert sentences, "no answer sentences were produced"
    answer = " ".join(
        s if isinstance(s, str) else s.get("text", "") for s in sentences
    ).strip()
    log("smoke", f"answer ({len(sentences)} sentence(s)): {answer}")
    assert len(answer) > 20, "answer suspiciously short"
    log("smoke", "=== PHASE 2 SMOKE PASSED ===")


if __name__ == "__main__":
    main()
