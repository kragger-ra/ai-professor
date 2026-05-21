"""AI Professor — Tutor v2 entry point (Phase 2: QA base).

Single process. Worker threads wired by two queues and one interrupt event:

    capture/STT  --input_q-->  agent  --tts_q-->  playback
         |                                            ^
         +------------------ interrupt ---------------+

External servers used: OpenAI API (or local LM Studio) for the LLM,
LM Studio for RAG embeddings, the Vosk TTS server for synthesis.

Run (from the repo root):
    python -m tutor.app
"""
from __future__ import annotations

import os
import queue
import threading
import time

from tutor.audio.capture import CaptureThread
from tutor.audio.playback import PlaybackThread
from tutor.brain.agent import AgentThread
from tutor.brain.answer import Answer
from tutor.brain.rag import RagModel
from tutor.util import log


def _capture_device() -> str:
    """Pick the STT input device from the audio mode."""
    if os.getenv("AUDIO_MODE", "none").lower() == "meeting":
        # In meeting mode STT listens to the call audio on Voicemeeter Out B2.
        return "Voicemeeter Out B2"
    return os.getenv("SOUND_DEVICE_IN", "")


def main() -> None:
    # --- shared channels -------------------------------------------------
    input_q: queue.Queue = queue.Queue()   # student utterances -> agent
    tts_q: queue.Queue = queue.Queue()     # answer sentences   -> playback
    interrupt = threading.Event()          # set the instant the student talks

    # --- RAG model (embeddings + FAISS index) ----------------------------
    log("app", "loading RAG model (embeddings + FAISS index)...")
    try:
        rag = RagModel()
    except Exception as exc:
        log("app", f"RAG unavailable ({type(exc).__name__}: {exc}) — "
                   f"is LM Studio running? continuing without course retrieval")
        rag = None

    # --- worker threads --------------------------------------------------
    agent = AgentThread(input_q, tts_q, interrupt, rag)
    playback = PlaybackThread(tts_q, interrupt)
    capture = CaptureThread(
        input_q,
        interrupt,
        tts_active=playback.speaking,           # anti-echo: raise VAD gate while voicing
        rag_vocab=(rag.get_vocabulary() if rag else set()),
        device_name=_capture_device(),
    )

    agent.start()
    playback.start()
    capture.start()

    # Audible "ready" cue once the mic stream is open — also a live
    # end-to-end check that the TTS chain works.
    if capture.ready.wait(timeout=120):
        cue = Answer(question="", sentences=["Профессор готов. Спрашивай."])
        cue.finish_generation()
        tts_q.put(cue)
    log("app", "pipeline up — speak to the professor (Ctrl+C to quit)")

    try:
        while capture.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        log("app", "shutting down")
    finally:
        capture.stop()
        # Capture this final session into cross-session memory before exit.
        log("app", "persisting session memory...")
        agent.persist_memory()
        agent.stop()
        playback.stop()


if __name__ == "__main__":
    main()
