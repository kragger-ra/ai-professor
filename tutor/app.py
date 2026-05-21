"""AI Professor — Tutor v2 entry point.

Single process. Three worker threads wired by two queues and one interrupt
event:

    capture/STT  --input_q-->  agent  --tts_q-->  playback
         |                                            ^
         +------------------ interrupt ---------------+

This is the Phase-1 spine: STT / LLM / TTS are stubbed. It proves the
thread + queue + interrupt contracts before the real components land.

Run (from the repo root):
    python -m tutor.app
"""
from __future__ import annotations

import queue
import threading
import time

from tutor.audio.capture import ConsoleCapture
from tutor.audio.playback import PlaybackThread
from tutor.brain.agent import AgentThread
from tutor.util import log


def main() -> None:
    # --- shared channels -------------------------------------------------
    input_q: queue.Queue = queue.Queue()   # student utterances -> agent
    tts_q: queue.Queue = queue.Queue()     # answer sentences   -> playback
    interrupt = threading.Event()          # set the instant the student talks

    # --- worker threads --------------------------------------------------
    agent = AgentThread(input_q, tts_q, interrupt)
    playback = PlaybackThread(tts_q, interrupt)
    capture = ConsoleCapture(input_q, interrupt)

    agent.start()
    playback.start()
    capture.start()
    log("app", "pipeline up — type a line to speak to the professor, Ctrl+C to quit")

    try:
        while capture.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        log("app", "shutting down")
    finally:
        capture.stop()
        agent.stop()
        playback.stop()


if __name__ == "__main__":
    main()
