"""The agent — the brain of the tutor.

PHASE 2 — the QA base. Per student utterance:
  1. meta-agent (pre-flight) + RAG retrieval run in PARALLEL — both need
     only the query text, so they hide under each other's latency.
  2. build the system prompt: persona + course + RAG context + meta.
  3. stream the LLM; each finished sentence is stored in an `Answer` object
     AND pushed onto the TTS queue.
  4. record the turn in the in-memory history.

Still stubbed for later phases: the answer stack / nesting (Phase 3-4),
voice commands and the checker / mini-lecture (Phase 5), cross-session
memory and profiles (Phase 6). The `Answer` object is created here already
so Phase 3 can switch playback to voice-from-Answer with resume.
"""
from __future__ import annotations

import concurrent.futures
import queue
import threading
import traceback

from tutor.brain import meta as meta_agent
from tutor.brain.answer import Answer
from tutor.brain.llm import stream_response_sentences
from tutor.brain.prompt import PROFESSOR_GOAL, construct_prompt, create_chat_from_prompt
from tutor.brain.rag import RagModel
from tutor.util import log

# QA mode: keep answers within an average listener's cognitive load.
# Phase 5 makes this number meta-tunable on student feedback.
QA_MAX_SENTENCES = 4
_LENGTH_RULE = (
    f"Отвечай кратко и по существу — максимум {QA_MAX_SENTENCES} предложения. "
    "Это устный ответ, студент слушает, а не читает."
)
RESPONSE_MAX_TOKENS = 400
HISTORY_TURNS_IN_PROMPT = 6        # recent turns kept verbatim in the prompt
DEFAULT_PERSONALITY = "professor_simpler"


class AgentThread(threading.Thread):
    """Phase-2 QA agent: utterance -> meta+RAG -> prompt -> stream -> TTS."""

    def __init__(self, input_q: queue.Queue, tts_q: queue.Queue,
                 interrupt: threading.Event, rag_model: RagModel | None):
        super().__init__(name="agent", daemon=True)
        self._input_q = input_q
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._rag = rag_model
        self._running = True
        self._personality = DEFAULT_PERSONALITY
        self._history: list[dict] = []          # [{"role","content"}, ...]
        self._current_answer: Answer | None = None
        self._pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=2, thread_name_prefix="preflight"
        )

    # ------------------------------------------------------------------
    # Thread body
    # ------------------------------------------------------------------

    def run(self) -> None:
        log("agent", "agent loop started")
        while self._running:
            try:
                utterance = self._input_q.get(timeout=0.3)
            except queue.Empty:
                continue
            # New utterance: the interrupt the gate raised has done its job
            # (playback already stopped). Clear it so this answer can play.
            self._interrupt.clear()
            log("agent", f"handling: {utterance!r}")
            try:
                self._handle(utterance)
            except Exception as exc:
                log("agent", f"turn failed: {type(exc).__name__}: {exc}")
                traceback.print_exc()

    # ------------------------------------------------------------------
    # One QA turn
    # ------------------------------------------------------------------

    def _handle(self, utterance: str) -> None:
        # 1. meta-agent + RAG retrieval, in parallel.
        recent = [h["content"] for h in self._history[-5:]]
        meta_future = self._pool.submit(
            meta_agent.analyze_context, "", recent, utterance
        )
        rag_future = self._pool.submit(self._rag_lookup, utterance)
        meta_result = meta_future.result()
        rag_context, rag_score = rag_future.result()

        # 2. build the prompt.
        meta_instruction = (
            _LENGTH_RULE + " " + meta_agent.build_meta_instruction(meta_result)
        ).strip()
        system_prompt = PROFESSOR_GOAL + "\n\n" + construct_prompt(
            rag_context=rag_context,
            personality_key=self._personality,
            student_profile="",
            meta_instruction=meta_instruction,
            rag_score=rag_score,
        )
        messages = create_chat_from_prompt(system_prompt, role="system")
        messages += self._history[-(2 * HISTORY_TURNS_IN_PROMPT):]
        messages.append({"role": "user", "content": utterance})

        # 3. stream the answer — sentence by sentence into the Answer object
        #    and onto the TTS queue.
        answer = Answer(question=utterance)
        self._current_answer = answer
        for sentence in stream_response_sentences(
            messages, max_tokens=RESPONSE_MAX_TOKENS
        ):
            if self._interrupt.is_set():
                log("agent", "interrupted — stop generating")
                break
            answer.add_sentence(sentence)
            self._tts_q.put(sentence)
        answer.finish_generation()

        # 4. record the turn.
        spoken = " ".join(answer.sentences).strip()
        self._history.append({"role": "user", "content": utterance})
        if spoken:
            self._history.append({"role": "assistant", "content": spoken})
        log("agent", f"answer done: {len(answer.sentences)} sentence(s)")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rag_lookup(self, query: str) -> tuple[str, float]:
        """Return (context_text, l2_score); empty / inf when RAG is unavailable."""
        if self._rag is None:
            return "", float("inf")
        try:
            context = self._rag.explain(query)
            score = getattr(self._rag, "last_score", float("inf"))
            return context or "", float(score)
        except Exception as exc:
            log("agent", f"RAG lookup failed: {exc}")
            return "", float("inf")

    def stop(self) -> None:
        self._running = False
        self._pool.shutdown(wait=False)
