"""The agent — the brain of the tutor.

PHASE 3 — interrupt + resume on the answer stack.

Per student utterance the agent routes:
  * a resume phrase ("продолжай" / "вернёмся") -> re-voice from memory,
    NO LLM call (instant, hang-proof);
  * a question while an answer is still in progress (the student interrupted)
    -> push the new answer onto the stack — a nested follow-up;
  * a fresh question -> clear the stack and answer from the top.

Generation runs in its OWN thread and always completes into the `Answer`
object, even when voicing was interrupted — so a resume just re-voices the
stored, already-finished answer.

Still stubbed for later phases: the depth-3 cap + deferred-question parking
+ the auto-offer (Phase 4); voice commands and the mini-lecture checker
(Phase 5); cross-session memory and profiles (Phase 6).
"""
from __future__ import annotations

import concurrent.futures
import queue
import re
import threading
import time
import traceback

from tutor.brain import meta as meta_agent
from tutor.brain.answer import Answer, AnswerStack
from tutor.brain.llm import stream_response_sentences
from tutor.brain.prompt import PROFESSOR_GOAL, construct_prompt, create_chat_from_prompt
from tutor.brain.rag import RagModel
from tutor.util import log

QA_MAX_SENTENCES = 4
_LENGTH_RULE = (
    f"Отвечай кратко и по существу — максимум {QA_MAX_SENTENCES} предложения. "
    "Это устный ответ, студент слушает, а не читает."
)
RESPONSE_MAX_TOKENS = 400
HISTORY_TURNS_IN_PROMPT = 6
DEFAULT_PERSONALITY = "professor_simpler"

# Resume phrases — short utterances meaning "go back to voicing".
_RESUME_RE = re.compile(
    r"продолж|верн[иёе]|дальше|поехали", re.IGNORECASE
)
# A stray interrupt with no follow-up utterance (a cough): auto-resume the
# unfinished answer after this idle gap.
_AUTO_RESUME_AFTER_S = 2.0

_RESUME_BRIDGE = "Возвращаемся к тому, о чём говорили."
_CONTINUE_BRIDGE = "Продолжаю."


class AgentThread(threading.Thread):
    """QA agent with an interrupt-aware answer stack."""

    def __init__(self, input_q: queue.Queue, tts_q: queue.Queue,
                 interrupt: threading.Event, rag_model: RagModel | None):
        super().__init__(name="agent", daemon=True)
        self._input_q = input_q
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._rag = rag_model
        self._running = True
        self._personality = DEFAULT_PERSONALITY
        self._history: list[dict] = []
        self._stack = AnswerStack()        # holds the active answer + parents
        self._interrupt_seen_at: float | None = None
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
                self._maybe_auto_resume()
                continue
            self._interrupt_seen_at = None
            self._interrupt.clear()
            log("agent", f"handling: {utterance!r}")
            try:
                self._handle(utterance)
            except Exception as exc:
                log("agent", f"turn failed: {type(exc).__name__}: {exc}")
                traceback.print_exc()

    # ------------------------------------------------------------------
    # Routing one utterance
    # ------------------------------------------------------------------

    def _handle(self, utterance: str) -> None:
        # Resume command — re-voice from memory, no LLM.
        if self._is_resume(utterance) and self._stack.depth > 0:
            self._handle_resume()
            return
        # A question. If the top answer is still in progress, the student
        # interrupted it — the new question nests under it.
        cur = self._stack.current
        nested = cur is not None and not cur.fully_voiced
        self._answer_question(utterance, nested=nested)

    def _is_resume(self, utterance: str) -> bool:
        u = utterance.strip()
        return len(u) < 40 and bool(_RESUME_RE.search(u))

    # ------------------------------------------------------------------
    # Answering a question
    # ------------------------------------------------------------------

    def _answer_question(self, utterance: str, nested: bool) -> None:
        # meta-agent + RAG retrieval, in parallel.
        recent = [self._turn_text(h) for h in self._history[-5:]]
        meta_future = self._pool.submit(
            meta_agent.analyze_context, "", recent, utterance
        )
        rag_future = self._pool.submit(self._rag_lookup, utterance)
        meta_result = meta_future.result()
        rag_context, rag_score = rag_future.result()

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
        messages += self._history_messages()
        messages.append({"role": "user", "content": utterance})

        answer = Answer(question=utterance)
        if not nested:
            self._stack.clear()           # fresh top-level question
        # Phase 4 handles a refused push (depth-3 cap); Phase 3 stays shallow.
        if not self._stack.push(answer):
            log("agent", "stack full — Phase 4 will defer; answering flat")
            self._stack.clear()
            self._stack.push(answer)
        else:
            log("agent", f"answering ({'nested' if nested else 'fresh'}) — "
                         f"stack depth {self._stack.depth}")

        # History in chronological order; the assistant entry keeps a live
        # reference to the Answer so its text fills in as generation streams.
        self._history.append({"role": "user", "content": utterance})
        self._history.append({"role": "assistant", "answer": answer})

        # Generation runs in its own thread — always completes into `answer`.
        threading.Thread(
            target=self._generate, args=(answer, messages),
            daemon=True, name="generate",
        ).start()
        # Hand the Answer to playback; it voices sentences as they appear.
        self._tts_q.put(answer)

    def _generate(self, answer: Answer, messages: list) -> None:
        try:
            for sentence in stream_response_sentences(
                messages, max_tokens=RESPONSE_MAX_TOKENS
            ):
                answer.add_sentence(sentence)
        except Exception as exc:
            log("agent", f"generation error: {exc}")
        finally:
            answer.finish_generation()
        log("agent", f"generated {len(answer.sentences)} sentence(s) "
                     f"for {answer.question[:40]!r}")

    # ------------------------------------------------------------------
    # Resume
    # ------------------------------------------------------------------

    def _handle_resume(self) -> None:
        """Re-voice from memory. depth>=2 pops up to the parent; depth==1
        just continues the current answer. Never calls the LLM."""
        cur = self._stack.current
        if cur is None:
            return
        if self._stack.depth >= 2:
            target = self._stack.pop()    # drop the finished top, return parent
            bridge = _RESUME_BRIDGE
        else:
            target = cur                  # continue the only answer
            bridge = _CONTINUE_BRIDGE
        if target is None:
            return
        if not target.unvoiced and not target.generating:
            log("agent", "resume requested but nothing left to voice")
            return
        self._voice(bridge, target)
        log("agent", f"resumed — stack depth {self._stack.depth}")

    def _maybe_auto_resume(self) -> None:
        """Stray interrupt with no follow-up (a cough) — re-voice the
        unfinished current answer after a short wait."""
        if not self._interrupt.is_set():
            self._interrupt_seen_at = None
            return
        if self._interrupt_seen_at is None:
            self._interrupt_seen_at = time.time()
            return
        if time.time() - self._interrupt_seen_at < _AUTO_RESUME_AFTER_S:
            return
        self._interrupt_seen_at = None
        self._interrupt.clear()
        cur = self._stack.current
        if cur is not None and not cur.fully_voiced:
            log("agent", "stray interrupt — auto-resuming current answer")
            self._voice(_CONTINUE_BRIDGE, cur)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _voice(self, bridge_text: str, answer: Answer) -> None:
        """Speak a short bridge phrase, then (re-)voice `answer` from its
        current voiced_index. Both go to playback as Answer objects."""
        bridge = Answer(question="", sentences=[bridge_text])
        bridge.finish_generation()
        self._tts_q.put(bridge)
        self._tts_q.put(answer)

    def _history_messages(self) -> list[dict]:
        """Recent turns as OpenAI-format messages (assistant text read live)."""
        out: list[dict] = []
        for h in self._history[-(2 * HISTORY_TURNS_IN_PROMPT):]:
            text = self._turn_text(h)
            if text:
                out.append({"role": h["role"], "content": text})
        return out

    @staticmethod
    def _turn_text(h: dict) -> str:
        if "content" in h:
            return h["content"]
        ans = h.get("answer")
        return " ".join(ans.sentences).strip() if ans else ""

    def _rag_lookup(self, query: str) -> tuple[str, float]:
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
