"""Phase-1 smoke test — proves the queue + interrupt contracts, no human.

  TEST 1  an utterance flows through to a full spoken answer.
  TEST 2  the interrupt (gate opening) stops playback mid-answer and drains.
  TEST 3  the pipeline recovers — the next utterance is handled normally.

Run (from the repo root):
    python -m tutor._smoke_phase1
"""
from __future__ import annotations

import queue
import threading
import time

from tutor.audio.playback import PlaybackThread
from tutor.brain.agent import AgentThread
from tutor.util import log


def main() -> None:
    input_q: queue.Queue = queue.Queue()
    tts_q: queue.Queue = queue.Queue()
    interrupt = threading.Event()

    agent = AgentThread(input_q, tts_q, interrupt)
    playback = PlaybackThread(tts_q, interrupt)
    agent.start()
    playback.start()

    # TEST 1 — full answer flows through ----------------------------------
    log("smoke", "TEST 1 — full answer flows through")
    input_q.put("что такое RAG")
    time.sleep(5.5)   # 5 sentences * 0.8s + slack
    assert playback.played == 5, f"expected 5 played, got {playback.played}"
    assert tts_q.empty(), "queue not drained after a full answer"
    log("smoke", "TEST 1 ok")

    # TEST 2 — interrupt stops playback mid-answer ------------------------
    log("smoke", "TEST 2 — interrupt stops playback")
    playback.played = 0
    input_q.put("длинный вопрос")
    time.sleep(1.3)            # ~1-2 sentences in
    interrupt.set()           # student opens the gate
    time.sleep(0.6)
    cut_at = playback.played
    assert cut_at < 5, f"playback not interrupted, played {cut_at}"
    assert tts_q.empty(), "queue not drained on interrupt"
    time.sleep(0.6)
    assert playback.played == cut_at, "playback kept going after interrupt"
    log("smoke", f"TEST 2 ok — cut after {cut_at} sentence(s)")

    # TEST 3 — recovery after interrupt ----------------------------------
    log("smoke", "TEST 3 — recovery after interrupt")
    playback.played = 0
    input_q.put("новый вопрос")   # agent clears the interrupt on pickup
    time.sleep(5.5)
    assert playback.played == 5, f"recovery failed, played {playback.played}"
    log("smoke", "TEST 3 ok")

    log("smoke", "=== PHASE 1 SMOKE PASSED ===")
    agent.stop()
    playback.stop()


if __name__ == "__main__":
    main()
