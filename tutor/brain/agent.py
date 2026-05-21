"""The agent — the brain of the tutor.

PHASE 5 — adaptive layer: register drift, length tuning, mini-lecture.

Per student utterance the agent routes:
  * a pending offer ("вернёмся к…?" / "разобрать отложенный вопрос?")
    -> "да" accepts, anything else declines;
  * "продолжай" -> finish the current answer; "вернёмся"/"назад" -> step
    back up to the parent answer — both re-voiced from memory, no LLM;
  * a question while an answer is in progress -> nest it under the current
    answer, UNLESS the stack is already 3 deep — then refuse with a fixed
    phrase and PARK the question (it resurfaces when the stack unwinds);
  * a fresh question -> answer it from a clean stack.

Generation runs in its own thread and always completes into the `Answer`
object, so a resume just re-voices stored, finished text — instant, no LLM.

Still stubbed for later phases: cross-session memory + profiles (Phase 6).
"""
from __future__ import annotations

import concurrent.futures
import queue
import re
import threading
import traceback

from tutor.brain import commands
from tutor.brain import meta as meta_agent
from tutor.brain.answer import MAX_STACK_DEPTH, Answer, AnswerStack
from tutor.brain.llm import stream_response_sentences
from tutor.brain.prompt import PROFESSOR_GOAL, construct_prompt, create_chat_from_prompt
from tutor.brain.rag import RagModel
from tutor.util import log

QA_MAX_SENTENCES = 4              # default answer cap; tuned 2..8 at runtime
RESPONSE_MAX_TOKENS = 400
MINILECTURE_MAX_TOKENS = 900      # bigger budget for a confirmed mini-lecture
HISTORY_TURNS_IN_PROMPT = 6
DEFAULT_PERSONALITY = "professor_simpler"
DEFAULT_REGISTER = 2             # 1..5 vocabulary level; starts simple


def _length_rule(max_sentences: int) -> str:
    return (
        f"Отвечай кратко и по существу — максимум {max_sentences} предложения. "
        "Это устный ответ, студент слушает, а не читает."
    )


# Per-register speaking-style line — injected every turn. The agent's own
# _register drifts one step per turn toward the student's observed register.
_REGISTER_RULES = {
    1: "Говори совсем просто, как с новичком: бытовые слова, без терминов.",
    2: "Говори простым языком, термины — только с короткой расшифровкой.",
    3: "Обычная разговорная речь, базовые термины можно без расшифровки.",
    4: "Студент в теме — используй профессиональную терминологию свободно.",
    5: "Студент на экспертном уровне — говори технически плотно, без упрощений.",
}

# Mini-lecture: spoken to confirm before launching a long answer.
_MINILECTURE_OFFER = ("Это будет мини-лекция — большой развёрнутый рассказ. "
                      "Зачитать?")
_MINILECTURE_RULE = (
    "Это мини-лекция: раскрой тему развёрнуто и по порядку — что это такое, "
    "как работает, пример, типичные ошибки. Говори голосом, без маркеров "
    "списков, не дроби на крошечные реплики."
)

# "Continue" — finish voicing the CURRENT answer (it was cut off mid-way).
_CONTINUE_RE = re.compile(r"продолж|дальше|договор|поехали", re.IGNORECASE)
# "Return" — step one level back up the stack, to the parent answer.
_RETURN_RE = re.compile(r"верн[иёе]|назад|обратно", re.IGNORECASE)
_YES_RE = re.compile(r"\bда\b|давай|конечно|ага|хочу|разбер|продолж|верн[иёе]",
                     re.IGNORECASE)
_NO_RE = re.compile(r"\bнет\b|не\s+надо|не\s+нужно|потом|позже|не\s+хочу",
                    re.IGNORECASE)

# Stop commands — playback is already halted by the interrupt Event; the
# agent must simply NOT generate a reply.
_STOP_RE = re.compile(r"^\s*(стоп|стой|хватит|тихо|молчи|помолчи|подожди|погоди)\b",
                      re.IGNORECASE)

# Mini-lecture request — a request verb + a depth word + an explicit topic
# ("про/о/об X"). A depth word with no topic ("расскажи подробнее") is a
# manner switch; a depth word with no request verb is the student narrating.
_DEPTH_RE = re.compile(
    r"подробн|поподробн|детальн|поглубже|глубже|побольше"
    r"|развёрнут|развернут|целую\s+лекцию|мини[-\s]?лекци",
    re.IGNORECASE,
)
_TOPIC_RE = re.compile(r"\b(про|об|о)\s+\S", re.IGNORECASE)
_REQUEST_RE = re.compile(
    r"расскаж|объясн|опиш|раскро|поясн|давай|\bмож|хочу|хотел",
    re.IGNORECASE,
)

_RESUME_BRIDGE = "Возвращаемся к тому, о чём говорили."
_CONTINUE_BRIDGE = "Продолжаю."
_RETURN_OFFER = "Вернёмся к тому, о чём мы говорили до этого?"
# Spoken verbatim when a 4th nesting level is refused.
_CAP_PHRASE = ("Давай закончим начатое, а про твой вопрос поговорим чуть позже, "
               "иначе можем запутаться.")


class AgentThread(threading.Thread):
    """QA agent with a depth-capped, interrupt-aware answer stack."""

    def __init__(self, input_q: queue.Queue, tts_q: queue.Queue,
                 interrupt: threading.Event, rag_model: RagModel | None):
        super().__init__(name="agent", daemon=True)
        self._input_q = input_q
        self._tts_q = tts_q
        self._interrupt = interrupt
        self._rag = rag_model
        self._running = True
        self._personality = DEFAULT_PERSONALITY
        self._manner = "simpler"          # tracked style; switched by voice command
        self._register = DEFAULT_REGISTER       # 1..5; drifts toward the student
        self._max_sentences = QA_MAX_SENTENCES  # answer cap; tuned by feedback
        self._history: list[dict] = []
        self._stack = AnswerStack()
        # A proactively spoken offer awaiting a yes/no:
        #   {"type": "return"} | {"type": "deferred", "question": str}
        self._offer: dict | None = None
        self._offered_for: Answer | None = None   # answer we already offered for
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
                item = self._input_q.get(timeout=0.3)
            except queue.Empty:
                self._maybe_offer()
                continue
            utterance, was_interruption = item
            self._interrupt.clear()
            log("agent", f"handling: {utterance!r} (interruption={was_interruption})")
            try:
                self._handle(utterance, was_interruption)
            except Exception as exc:
                log("agent", f"turn failed: {type(exc).__name__}: {exc}")
                traceback.print_exc()

    # ------------------------------------------------------------------
    # Routing one utterance
    # ------------------------------------------------------------------

    def _handle(self, utterance: str, was_interruption: bool) -> None:
        # A proactive offer is awaiting an answer.
        if self._offer is not None:
            offer, self._offer = self._offer, None
            if self._is_yes(utterance):
                if offer["type"] == "return":
                    self._handle_return()
                elif offer["type"] == "minilecture":
                    self._answer_question(offer["question"], nested=False,
                                          long=True)
                else:                                  # deferred question
                    self._answer_question(offer["question"], nested=False)
                return
            if self._is_no(utterance):
                if offer["type"] == "minilecture":
                    # Declined the long form — still answer, but briefly.
                    self._answer_question(offer["question"], nested=False)
                else:
                    log("agent", "offer declined")
                return
            # neither yes nor no — a new question; drop the offer, handle below.

        # Stop command — playback is already halted by the interrupt Event;
        # the agent simply stays silent (generates no reply).
        if len(utterance) < 25 and _STOP_RE.search(utterance):
            log("agent", "stop command — staying silent")
            return

        # Continue — finish voicing the current answer, no LLM.
        if self._stack.depth > 0 and self._is_continue(utterance):
            self._handle_continue()
            return

        # Return — step back up to the parent answer, no LLM.
        if self._stack.depth > 0 and self._is_return(utterance):
            self._handle_return()
            return

        # Mini-lecture request — confirm before launching a long answer.
        if self._is_minilecture_request(utterance):
            self._offer = {"type": "minilecture", "question": utterance}
            self._offered_for = None
            log("agent", f"mini-lecture offered: {utterance[:50]!r}")
            self._speak_line(_MINILECTURE_OFFER)
            return

        # Voice commands — course load / list courses / manner switch.
        if commands.route(self, utterance):
            return

        # A question nests under the current answer ONLY if the student
        # actually interrupted — spoke while the professor was still voicing.
        # An independent question asked after a finished answer is NOT nested.
        cur = self._stack.current
        nested = was_interruption and cur is not None
        if nested and self._stack.depth >= MAX_STACK_DEPTH:
            # 4th nesting level — refuse and park the question.
            self._stack.defer(utterance)
            log("agent", f"depth cap ({MAX_STACK_DEPTH}) — parked: {utterance[:40]!r}")
            self._speak_line(_CAP_PHRASE)
            return
        self._answer_question(utterance, nested=nested)

    @staticmethod
    def _is_continue(utterance: str) -> bool:
        u = utterance.strip()
        return len(u) < 40 and bool(_CONTINUE_RE.search(u))

    @staticmethod
    def _is_return(utterance: str) -> bool:
        u = utterance.strip()
        return len(u) < 40 and bool(_RETURN_RE.search(u))

    @staticmethod
    def _is_yes(utterance: str) -> bool:
        u = utterance.strip()
        return len(u) < 40 and bool(_YES_RE.search(u))

    @staticmethod
    def _is_no(utterance: str) -> bool:
        u = utterance.strip()
        return len(u) < 40 and bool(_NO_RE.search(u))

    @staticmethod
    def _is_minilecture_request(utterance: str) -> bool:
        """A short, directive ask for an in-depth talk on a named topic."""
        u = utterance.strip()
        return (len(u) < 90
                and bool(_REQUEST_RE.search(u))
                and bool(_DEPTH_RE.search(u))
                and bool(_TOPIC_RE.search(u)))

    # ------------------------------------------------------------------
    # Answering a question
    # ------------------------------------------------------------------

    def _answer_question(self, utterance: str, nested: bool,
                         long: bool = False) -> None:
        # meta-agent + RAG retrieval, in parallel.
        recent = [self._turn_text(h) for h in self._history[-5:]]
        meta_future = self._pool.submit(
            meta_agent.analyze_context, "", recent, utterance
        )
        rag_future = self._pool.submit(self._rag_lookup, utterance)
        meta_result = meta_future.result()
        rag_context, rag_score = rag_future.result()

        # Drift the speaking register + answer-length cap toward the student.
        self._apply_calibration(meta_result)

        style_rule = (_MINILECTURE_RULE if long
                      else _length_rule(self._max_sentences))
        register_rule = _REGISTER_RULES.get(self._register, "")
        meta_instruction = " ".join(p for p in (
            style_rule, register_rule,
            meta_agent.build_meta_instruction(meta_result),
        ) if p).strip()
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
        self._stack.push(answer)          # _handle already checked the cap
        self._offered_for = None
        log("agent", f"answering ({'nested' if nested else 'fresh'}"
                     f"{', mini-lecture' if long else ''}) — depth "
                     f"{self._stack.depth}, register {self._register}, "
                     f"cap {self._max_sentences}")

        # History in chronological order; the assistant entry keeps a live
        # reference to the Answer so its text fills in as generation streams.
        self._history.append({"role": "user", "content": utterance})
        self._history.append({"role": "assistant", "answer": answer})

        # Generation runs in its own thread — always completes into `answer`.
        max_tokens = MINILECTURE_MAX_TOKENS if long else RESPONSE_MAX_TOKENS
        threading.Thread(
            target=self._generate, args=(answer, messages, max_tokens),
            daemon=True, name="generate",
        ).start()
        self._tts_q.put(answer)

    def _apply_calibration(self, meta: dict) -> None:
        """Persistently calibrate output to the student. The register drifts
        one step per turn toward the student's observed register; an explicit
        length signal nudges the sentence cap by two."""
        target = meta.get("register")
        if isinstance(target, int) and 1 <= target <= 5:
            if target > self._register:
                self._register += 1
            elif target < self._register:
                self._register -= 1
        length = meta.get("length")
        if length == "shorter":
            self._max_sentences = max(2, self._max_sentences - 2)
        elif length == "longer":
            self._max_sentences = min(8, self._max_sentences + 2)

    def _generate(self, answer: Answer, messages: list,
                  max_tokens: int) -> None:
        try:
            for sentence in stream_response_sentences(
                messages, max_tokens=max_tokens
            ):
                answer.add_sentence(sentence)
        except Exception as exc:
            log("agent", f"generation error: {exc}")
        finally:
            answer.finish_generation()
        log("agent", f"generated {len(answer.sentences)} sentence(s) "
                     f"for {answer.question[:40]!r}")

    # ------------------------------------------------------------------
    # Resume + proactive offers
    # ------------------------------------------------------------------

    def _handle_continue(self) -> None:
        """Finish voicing the CURRENT answer from where it was cut off.
        Stack depth is unchanged. Never calls the LLM."""
        cur = self._stack.current
        if cur is None:
            return
        self._offered_for = None
        if not cur.unvoiced and not cur.generating:
            log("agent", "continue requested but nothing left to voice")
            return
        self._voice(_CONTINUE_BRIDGE, cur)
        log("agent", f"continued — stack depth {self._stack.depth}")

    def _handle_return(self) -> None:
        """Step one level back up the stack and re-voice the parent answer.
        At the root there is nothing above — fall back to continue. No LLM."""
        if self._stack.depth < 2:
            self._handle_continue()
            return
        parent = self._stack.pop()        # drop current top, return the parent
        self._offered_for = None
        if parent is None:
            return
        if not parent.unvoiced and not parent.generating:
            log("agent", f"returned — parent already fully voiced, "
                         f"stack depth {self._stack.depth}")
            self._speak_line(_RESUME_BRIDGE)
            return
        self._voice(_RESUME_BRIDGE, parent)
        log("agent", f"returned — stack depth {self._stack.depth}")

    def _maybe_offer(self) -> None:
        """When a (sub-)answer has finished voicing, proactively offer the
        next step: return to the parent, or pick up a parked question."""
        if self._offer is not None:
            return
        cur = self._stack.current
        if cur is None or not cur.fully_voiced:
            return
        if self._stack.depth >= 2:
            if cur is self._offered_for:
                return                    # already offered for this answer
            self._offered_for = cur
            self._offer = {"type": "return"}
            self._speak_line(_RETURN_OFFER)
            return
        # back at the root — surface a parked question, if any
        parked = self._stack.take_deferred()
        if parked:
            self._offer = {"type": "deferred", "question": parked}
            self._speak_line(f"Ты ещё спрашивал: «{parked[:70]}». Разобрать его?")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _voice(self, bridge_text: str, answer: Answer) -> None:
        """Speak a short bridge phrase, then (re-)voice `answer` from its
        current voiced_index."""
        self._speak_line(bridge_text)
        self._tts_q.put(answer)

    def _speak_line(self, text: str) -> None:
        """Voice a single transient line (a bridge / an offer / the cap)."""
        line = Answer(question="", sentences=[text])
        line.finish_generation()
        self._tts_q.put(line)

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
