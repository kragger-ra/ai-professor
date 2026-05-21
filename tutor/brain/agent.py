"""The agent — the brain of the tutor.

PHASE 5 — voice commands, mini-lecture checker, nested-short answers.

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

RESPONSE_MAX_TOKENS = 400
NESTED_MAX_TOKENS = 220           # a nested clarification stays short (2-3 sentences)
MINILECTURE_MAX_TOKENS = 900      # bigger budget for a confirmed mini-lecture
META_TIMEOUT_S = 4.0              # cap how long an answer waits on the meta-agent
HISTORY_TURNS_IN_PROMPT = 6
DEFAULT_PERSONALITY = "professor_simpler"

# Answer length and vocabulary are NOT pre-computed here — the main LLM
# adapts its own style from the conversation (see PROFESSOR_GOAL). The agent
# keeps only the two STRUCTURAL rules below: a nested clarification stays
# short, a confirmed mini-lecture goes long.

# Mini-lecture: spoken to confirm before launching a long answer.
_MINILECTURE_OFFER = ("Это будет мини-лекция — большой развёрнутый рассказ. "
                      "Зачитать?")
_MINILECTURE_RULE = (
    "Это мини-лекция: раскрой тему развёрнуто и по порядку — что это такое, "
    "как работает, пример, типичные ошибки. Говори голосом, без маркеров "
    "списков, не дроби на крошечные реплики."
)

# A nested answer is a quick clarification asked mid-explanation — keep it
# tight (2-3 sentences) so the student does not lose the main thread.
_NESTED_RULE = (
    "Это короткий уточняющий вопрос, заданный посреди другого объяснения. "
    "Ответь сжато — максимум 3 предложения, лучше 2: дай определение и одно "
    "пояснение. Без длинных примеров и без углубления — студент должен "
    "быстро вернуться к основной мысли."
)

# "Continue" — finish voicing the CURRENT answer (it was cut off mid-way).
_CONTINUE_RE = re.compile(r"продолж|дальше|договор|поехали", re.IGNORECASE)
# "Return" — step one level back up the stack, to the parent answer.
_RETURN_RE = re.compile(r"верн[иёе]|назад|обратно", re.IGNORECASE)
# Bare acknowledgement — the whole utterance is just yes/ok filler. With no
# pending offer it is NOT a question and must not clear the answer stack.
_ACK_TOKEN = (r"да|ага|угу|окей|ок|хорошо|ладно|понятно|понятненько|ясно|"
              r"конечно|договорились|давай|давайте|спасибо|ну|вот|я|это|"
              r"всё|все|уже|понял|поняла|поняли")
_ACK_RE = re.compile(
    rf"^[\s,.!?\-—]*(?:(?:{_ACK_TOKEN})[\s,.!?\-—]*){{1,5}}$", re.IGNORECASE)
_NEGATION_RE = re.compile(r"\b(не|нет|ни)\b", re.IGNORECASE)
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

        # Bare acknowledgement ("да", "давайте", "понятно") — not a question.
        # It must not clear the stack: continue the current answer if one is
        # live, otherwise ignore it.
        if self._is_acknowledgement(utterance):
            if self._stack.depth > 0:
                log("agent", f"acknowledgement — continuing: {utterance!r}")
                self._handle_continue()
            else:
                log("agent", f"acknowledgement — nothing to do: {utterance!r}")
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
    def _is_acknowledgement(utterance: str) -> bool:
        """The whole utterance is bare yes/ok filler — not a question."""
        u = utterance.strip()
        if not u or len(u) > 35:
            return False
        if _NEGATION_RE.search(u):
            return False               # "не понял", "нет" — not acknowledgement
        return bool(_ACK_RE.fullmatch(u))

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
        # Meta is best-effort — it must not stall the answer. If it is slow,
        # proceed with safe defaults; the abandoned task finishes on its own.
        try:
            meta_result = meta_future.result(timeout=META_TIMEOUT_S)
        except concurrent.futures.TimeoutError:
            log("agent", "meta-agent slow — answering with defaults this turn")
            meta_result = dict(meta_agent.SAFE_DEFAULTS)
        rag_context, rag_score = rag_future.result()

        # Structural length rule only. mini-lecture: long. nested: a quick
        # mid-explanation clarification, forced short so the main thread is
        # not lost — UNLESS the student explicitly asked for the detailed
        # manner. fresh: no rule here — the main LLM self-adapts length and
        # vocabulary from the conversation (PROFESSOR_GOAL).
        if long:
            style_rule, max_tokens = _MINILECTURE_RULE, MINILECTURE_MAX_TOKENS
        elif nested and self._manner != "detailed":
            style_rule, max_tokens = _NESTED_RULE, NESTED_MAX_TOKENS
        else:
            style_rule, max_tokens = "", RESPONSE_MAX_TOKENS
        meta_instruction = " ".join(p for p in (
            style_rule, meta_agent.build_meta_instruction(meta_result),
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
        mode = "mini-lecture" if long else ("nested" if nested else "fresh")
        log("agent", f"answering ({mode}) — depth {self._stack.depth}, "
                     f"max_tokens {max_tokens}")

        # History in chronological order; the assistant entry keeps a live
        # reference to the Answer so its text fills in as generation streams.
        self._history.append({"role": "user", "content": utterance})
        self._history.append({"role": "assistant", "answer": answer})

        # Generation runs in its own thread — always completes into `answer`.
        threading.Thread(
            target=self._generate, args=(answer, messages, max_tokens),
            daemon=True, name="generate",
        ).start()
        self._tts_q.put(answer)

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
