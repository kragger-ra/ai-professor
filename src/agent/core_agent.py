"""

CORE AGENT

supports streaming output

tools like !tool 123
/command minecraft
@aget action
> speak *emotion*
"""

import os
import re
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Optional

from agent.base_agent import BaseAgent
from data_flow.ctx_host import CtxHost
from data_schema.ctx_structures import CtxSwarmType

if __name__ == "__main__":
    module_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, module_dir)
    from data_schema.structure_templates import create_ctx_swarm

from agent.llm_clients.lc_clients import get_llm_chain
from agent.prompt_generation.prompt_constructor import (
    SmartEventWaiter,
    construct_prompt_messages,
)
from agent.rag import RagModel
from agent.streaming_orchestrator import stream_response_sentences
from agent.meta_agent import analyze_context, build_meta_instruction, extract_student_info
from lecture.student_profiles import StudentProfileManager
from utils.patterns import BACKCHANNEL_PATTERNS
from lecture.lecture_delivery import (
    LectureDelivery,
    prepare_lecture,
    generate_quiz_questions,
    DELIVERY_SYSTEM_PROMPT,
)
from agent.humor import try_humor
from config_schema.general import get_name
from utils.debug import bcolors
from data_flow.ctx_handler import CtxHandler
from utils.debug import print_messages


_EMOTION_NAMES = (
    "neutral|happy|thoughtful|encouraging|sad|angry|scared|whispering|disgusted|sarcastic"
)
_EMOTION_PAREN_TAIL_RE = re.compile(rf'\(({_EMOTION_NAMES})\)\s*$', re.IGNORECASE)
_EMOTION_STAR_RE = re.compile(rf'\*({_EMOTION_NAMES})\*', re.IGNORECASE)


def _parse_emotion(comment: str) -> tuple:
    """Extract emotion tag from the end of a sentence, returning (emotion, text).

    Supports ``(happy)`` trailing parens and legacy ``*happy*`` inline markers.
    """
    if not comment:
        return "", comment or ""
    m = _EMOTION_PAREN_TAIL_RE.search(comment)
    if m:
        return m.group(1).lower(), comment[:m.start()].rstrip()
    tags = _EMOTION_STAR_RE.findall(comment)
    if tags:
        cleaned = _EMOTION_STAR_RE.sub('', comment).strip()
        return tags[-1].lower(), cleaned
    return "", comment

USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() in ("true", "1", "yes")

# Core timing/budget constants (extracted from scattered literals)
LECTURE_STREAM_TIMEOUT_S = 30           # hard cap per lecture block stream
# Lecture blocks are pre-structured (3-6 sentences each), don't need huge budget.
# RESPONSE_MAX_TOKENS_LONG stays at 5000 for free-form explanations.
LECTURE_BLOCK_MAX_TOKENS = 1500
LECTURE_QA_MAX_TOKENS = 800
LECTURE_TEMPERATURE = 0.6
LECTURE_QA_TEMPERATURE = 0.5
# Short student messages used to get a tiny budget (300) under the assumption
# they imply tiny answers. In practice "Хорошо, продолжайте" or "Поясни?" need
# room for a full continuation. Aligning both caps avoids mid-sentence cutoff.
RESPONSE_MAX_TOKENS_SHORT = 2000
RESPONSE_MAX_TOKENS_LONG = 5000

# Skeleton-driven response (two-pass): outline first, then deliver to plan.
# Phase 1: triggered for explanatory questions; Phase 2 will add per-point tracking.
SKELETON_OUTLINE_MAX_TOKENS = 250       # Pass 1 budget — just the bullet list
SKELETON_END_MARKER = "[END]"           # stop sequence for Pass 2
SKELETON_TRIGGERS = (                   # heuristic: detect explanation requests
    "объясни", "расскажи", "что такое", "что это", "почему",
    "как работает", "как устроен", "как сделать", "как ",
    "сравни", "разверни", "подробно", "приведи пример", "пример",
    "опиши", "разбери", "поясни", "в чём разница", "в чем разница",
    "повтори", "с начала", "запутал", "не понял",
)
SKELETON_LONG_MSG_THRESHOLD = 50
RESPONSE_TEMPERATURE_LOW = 0.4
RESPONSE_TEMPERATURE_HIGH = 0.75
TTS_POLL_INTERVAL_S = 0.3
STT_POLL_INTERVAL_S = 0.2
INTER_BLOCK_PAUSE_S = 3
POST_INTERRUPT_PAUSE_S = 2
CHECK_QUESTION_DELAY_S = 1.5
POST_INTERRUPT_REENTRY_PAUSE_S = 1.0
AGENT_ERROR_BACKOFF_S = 3
# Q&A audience phase: silence threshold before nudging / advancing
QA_AUDIENCE_SILENCE_S = 15
QA_AUDIENCE_MAX_STRIKES = 2
QA_POLL_INTERVAL_S = 0.5
QUIZ_QUESTIONS_COUNT = 3
LECTURE_FAREWELL_PHRASE = "Спасибо за ваше внимание. На этом наше занятие закончено."
BREAK_REMINDER_THRESHOLD_S = 3600       # 60 min
SILENCE_HINT_SHORT_S = 10
SILENCE_HINT_LONG_S = 30
STREAM_TOKEN_TIMEOUT_S = 10             # per-token idle timeout in streaming_orchestrator


def _should_use_skeleton(student_msg: str) -> bool:
    """Decide whether to plan-then-deliver via the skeleton mechanism.

    Disabled by default (USE_SKELETON env var). Pass 2 with [END] stop on
    Gemma 4 E4B currently truncates at 0 tokens — model emits the marker
    inside its thinking, killing the stream before TRIGGER_START. Re-enable
    after debugging the marker placement.

    Heuristic: explanatory keywords trigger regardless of length; without a
    trigger, only longer messages (>=50 chars) qualify. Short greetings,
    backchannels and yes/no responses skip the two-pass flow.
    """
    if os.getenv("USE_SKELETON", "false").lower() not in ("true", "1", "yes"):
        return False
    if not student_msg:
        return False
    msg = student_msg.strip()
    msg_lower = msg.lower()
    if any(trigger in msg_lower for trigger in SKELETON_TRIGGERS):
        # Still skip ultra-short triggers like "как?" alone — needs context.
        return len(msg) >= 8
    return len(msg) >= SKELETON_LONG_MSG_THRESHOLD


def _agent_log(msg):
    """Write agent debug to file (stdout often lost on Windows multiprocessing)."""
    import datetime
    line = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        with open("data/agent_log.txt", "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

# Regex for splitting sentences: punctuation followed by space, or newline(s)
_SENTENCE_BOUNDARY_RE = re.compile(r'(?<=[.!?])\s+|\n+')
# Minimum chars before we consider splitting a sentence off
_MIN_SENTENCE_LEN = 20

# Sentinels for stream end
_STREAM_END = object()
_STREAM_TIMEOUT_END = object()


def _next_with_timeout(iterator, timeout: float):
    """Get next item from iterator with timeout.
    Returns _STREAM_END on StopIteration, _STREAM_TIMEOUT_END on timeout.
    """
    import queue
    result_q = queue.Queue()

    def _pull():
        try:
            result_q.put(next(iterator))
        except StopIteration:
            result_q.put(_STREAM_END)
        except Exception as e:
            result_q.put(_STREAM_END)

    t = threading.Thread(target=_pull, daemon=True)
    t.start()
    try:
        return result_q.get(timeout=timeout)
    except queue.Empty:
        print("[CORE AGENT] Stream timeout — no tokens for "
              f"{timeout}s, treating as end of response")
        return _STREAM_TIMEOUT_END


class CoreAgent(BaseAgent):
    """Core agent for using with custom command and tool structures."""

    def __init__(
        self,
        ctx_swarm: CtxSwarmType,
        ctx_handler: Optional[CtxHandler] = None,
        ctx_host: Optional[CtxHost] = None,
    ):
        """Initialize the agent with context swarm"""
        super().__init__(ctx_swarm, ctx_handler)
        if ctx_handler is None:
            self.ctx_handler = CtxHandler(ctx_swarm)
        else:
            self.ctx_handler = ctx_handler

        # Initialize LLM
        self.llm = get_llm_chain()
        self._use_local_llm = USE_LOCAL_LLM

        # LM Studio client (local LLM with prompt caching + heartbeat)
        self._lm_studio_client = None
        if self._use_local_llm:
            try:
                from agent.lm_studio_client import get_lm_studio_client
                self._lm_studio_client = get_lm_studio_client()
                health = self._lm_studio_client.check_health()
                print(f"[CoreAgent] LM Studio: {health}")
                if health["status"] != "ok":
                    print("[CoreAgent] WARNING: LM Studio not ready, falling back to API")
                    self._use_local_llm = False
            except Exception as e:
                print(f"[CoreAgent] LM Studio init error: {e}, falling back to API")
                self._use_local_llm = False

        try:
            self.rag_model = RagModel()
        except Exception as e:
            print(f"[CoreAgent] Error initializing RagModel: {str(e)}")
            traceback.print_exc()
            self.rag_model = None
            print("[CoreAgent] Continuing without RAG model, setting it to None.")

        # Student profiles
        try:
            self._profile_mgr = StudentProfileManager()
            print("[CoreAgent] StudentProfileManager initialized")
        except Exception as e:
            print(f"[CoreAgent] StudentProfileManager error: {e}")
            self._profile_mgr = None
        self._current_student = None
        self._interrupted = False
        self._greeting_sent = False

        # Silence timer (feature 3)
        self._last_response_time = 0.0
        self._silence_hint_sent = False
        self._waiting_for_reply = False

        # Break reminder (feature 4)
        self._session_start_time = time.time()
        self._break_suggested = False

        # Lecture FSM: idle | delivering | qa_audience | qa_quiz | farewell
        self._lecture_phase = "idle"
        self._lecture_delivery = None
        self._lecture_waiting_reply = False  # waiting for check_question answer
        self._lecture_paused = False         # student said "stop/wait"
        self._lecture_last_handled_ts = 0    # timestamp of last handled student msg
        # Q&A audience phase state
        self._qa_silence_start = 0.0
        self._qa_no_q_strikes = 0
        self._qa_chat_baseline = 0
        # Q&A quiz phase state
        self._quiz_questions: list[str] = []
        self._quiz_idx = 0

        if ctx_host is None:
            self.ctx_host = CtxHost(ctx_handler)
        else:
            self.ctx_host = ctx_host
        self.initialized = True

    @contextmanager
    def cleanup_context(self):
        """Context manager for cleanup"""
        try:
            yield self
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
        if self.running:
            self.stop()
        # Shutdown LM Studio client heartbeat
        if hasattr(self, "_lm_studio_client") and self._lm_studio_client:
            try:
                from agent.lm_studio_client import shutdown_lm_studio_client
                shutdown_lm_studio_client()
            except Exception:
                pass
        if hasattr(self, "llm"):
            del self.llm
        if hasattr(self, "rag_model"):
            del self.rag_model
        if hasattr(self, "ctx_host"):
            del self.ctx_host

    def reload(self):
        """Safely reload the agent"""
        import importlib
        with self.cleanup_context():
            importlib.reload(sys.modules[__name__])
            self.__init__(self.ctx_swarm, self.ctx_handler)

    def stop(self):
        """Stop the agent"""
        self.running = False

    def is_running(self):
        """Check if agent is running"""
        return self.running

    # Regex to strip all emotion tags before sending to TTS
    _EMOTION_PAREN_RE = re.compile(
        r'\s*\((?:neutral|happy|thoughtful|encouraging|sad|angry|scared|whispering|disgusted|sarcastic)\)',
        re.IGNORECASE,
    )
    _EMOTION_STAR_RE = re.compile(
        r'\s*\*(?:neutral|happy|thoughtful|encouraging|sad|angry|scared|whispering|disgusted|sarcastic)\*',
        re.IGNORECASE,
    )

    def _flush_sentence(self, sentence: str, is_last: bool = False):
        """Send a complete sentence to TTS queue.

        For intermediate sentences, emotion is always 'neutral'.
        For the last sentence, we parse the *emotion* tag if present.
        """
        sentence = sentence.strip()
        if not sentence:
            return
        if is_last:
            emotion, text = _parse_emotion(sentence)
            if not emotion:
                emotion = "neutral"
        else:
            # Strip any stray emotion tags from intermediate chunks too
            emotion = "neutral"
            text = sentence
        # Safety net: strip ALL remaining emotion tags before TTS
        text = self._EMOTION_PAREN_RE.sub('', text)
        text = self._EMOTION_STAR_RE.sub('', text)
        text = text.strip()
        if text:
            self.ctx_swarm["tts_queue"].append(
                {"text": text, "emotion": emotion}
            )

    def _run_meta_analysis(self) -> tuple:
        """Run meta-agent analysis on latest message. Returns (student_profile, meta_instruction, meta_result)."""
        student_profile_text = ""
        meta_instruction = ""
        meta_result = {}

        if self._profile_mgr is None:
            return student_profile_text, meta_instruction, meta_result

        try:
            # Get recent messages for context (with role labels)
            recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=6)
            last_messages = []
            current_msg = ""
            for m in recent:
                msg = m.get("msg", "")
                if not msg:
                    continue
                is_self = m.get("self", False)
                role = "Профессор" if is_self else "Студент"
                last_messages.append(f"{role}: {msg}")
                if not is_self:
                    current_msg = msg  # last student message

            # Try to extract student name from latest message
            info = extract_student_info(current_msg)
            if info and info.get("name"):
                self._current_student = info["name"]
                if info.get("background"):
                    self._profile_mgr.update_profile(info["name"], {"background": info["background"]})

            # Build student profile text
            if self._current_student:
                student_profile_text = self._profile_mgr.get_profile_for_prompt(self._current_student)

            # Meta-agent analysis
            meta_result = analyze_context(student_profile_text, last_messages, current_msg)
            meta_instruction = build_meta_instruction(meta_result, student_known=bool(self._current_student))
        except Exception as e:
            print(f"[META] Error: {e}")
            traceback.print_exc()

        return student_profile_text, meta_instruction, meta_result

    def _update_student_profile(self, meta_result: dict, agent_response: str, student_msg: str):
        """Apply profile updates from meta-analysis after response."""
        if not self._profile_mgr or not self._current_student or not meta_result:
            return
        try:
            updates = meta_result.get("profile_updates", {})
            if updates.get("add_topic"):
                self._profile_mgr.append_to_list_field(self._current_student, "topics_of_interest", updates["add_topic"])
            if updates.get("add_issue"):
                self._profile_mgr.append_to_list_field(self._current_student, "known_issues", updates["add_issue"])
            if updates.get("communication_note"):
                self._profile_mgr.update_profile(self._current_student, {"personality_notes": updates["communication_note"]})
            if updates.get("background_info"):
                self._profile_mgr.update_profile(self._current_student, {"background": updates["background_info"]})
            delta = updates.get("tech_level_delta", 0)
            if delta and delta != 0:
                student = self._profile_mgr.get_or_create_student(self._current_student)
                new_level = max(1, min(5, student["tech_level"] + delta))
                self._profile_mgr.update_profile(self._current_student, {"tech_level": new_level})
            tlu = updates.get("topic_level_update")
            if tlu and isinstance(tlu, dict) and tlu.get("topic") and tlu.get("delta"):
                self._profile_mgr.update_topic_level(
                    self._current_student, tlu["topic"], tlu["delta"]
                )

            # Log interaction
            self._profile_mgr.log_interaction(
                self._current_student, student_msg, agent_response,
                meta_analysis=str(meta_result), emotion=meta_result.get("mood", "neutral"),
            )
        except Exception as e:
            print(f"[META] Profile update error: {e}")

    def _signal_interrupt(self) -> None:
        """Clear the TTS queue and push an interrupt sentinel.

        Central helper for the pattern repeated across step() / lecture flow
        whenever the student preempts ongoing speech.
        """
        tts_q = self.ctx_swarm["tts_queue"]
        if len(tts_q) > 0:
            tts_q[:] = []
        tts_q.append({"text": "interrupt", "emotion": "interrupt"})

    def _build_system_msg(self, content: str):
        """Construct a system message in the format expected by the active LLM backend."""
        if self._use_local_llm:
            return {"role": "system", "content": content}
        from langchain_core.messages import SystemMessage
        return SystemMessage(content=content)

    def _build_outline(self, base_messages: list) -> Optional[str]:
        """Pass 1 of the skeleton flow — request a short outline, hidden from TTS.

        Synchronous (collects tokens then returns). Strips TRIGGER_START leakage.
        Returns the outline text or None if generation failed.
        """
        from agent.streaming_orchestrator import stream_fast
        outline_request = (
            "Сначала кратко составь план будущего ответа: 4-7 пунктов "
            "в формате нумерованного списка. Только короткие заголовки пунктов, "
            "без раскрытия и пояснений. После списка ничего не пиши. "
            "Этот план будет основой подробного объяснения студенту.\n"
            "Начни ответ со слова TRIGGER_START, потом сразу нумерованный список."
        )
        outline_messages = list(base_messages) + [
            self._build_system_msg(outline_request)
        ]
        if not self._use_local_llm:
            outline_messages = self._to_dicts(outline_messages)

        full = ""
        try:
            for token in stream_fast(
                outline_messages,
                temperature=0.4,
                max_tokens=SKELETON_OUTLINE_MAX_TOKENS,
            ):
                full += token
        except Exception as e:
            _agent_log(f"[SKELETON] outline error: {e}")
            return None

        if "TRIGGER_START" in full:
            full = full.rsplit("TRIGGER_START", 1)[-1]
        full = full.strip()
        return full or None

    @staticmethod
    def _outline_has_points(outline: str) -> bool:
        """Quick sanity check — outline should contain at least 2 enumerated points."""
        if not outline:
            return False
        return len(re.findall(r"^\s*\d+[\.\)]", outline, flags=re.MULTILINE)) >= 2

    @staticmethod
    def _to_dicts(messages) -> list:
        """Convert langchain messages to plain dicts for litellm."""
        result = []
        for m in messages:
            if isinstance(m, dict):
                result.append(m)
            elif hasattr(m, "type") and hasattr(m, "content"):
                role_map = {"human": "user", "ai": "assistant", "system": "system"}
                result.append({"role": role_map.get(m.type, "user"), "content": m.content})
            else:
                result.append({"role": "user", "content": str(m)})
        return result

    # Strip all *markup* tags (e.g. *(пауза)*, *смеётся*, *вздыхает*)
    _STAR_TAG_RE = re.compile(r'\*[^*]+\*')

    @staticmethod
    def _stretch_ellipsis(text: str) -> str:
        """Convert '...' to stretched last letter for natural TTS.
        'Хм...' → 'Хмммм.' | 'Хотя...' → 'Хотяяя.'
        """
        def _stretch(m):
            before = m.group(1)
            if before:
                return before + before[-1] * 3 + "."
            return "..."
        return re.sub(r'(\S)\.{3}', _stretch, text)

    def _send_to_tts(self, text: str, split_sentences: bool = False):
        """Send text to TTS queue, optionally splitting into sentences."""
        text = self._EMOTION_PAREN_RE.sub('', text)
        text = self._EMOTION_STAR_RE.sub('', text)
        text = self._STAR_TAG_RE.sub('', text)
        text = self._stretch_ellipsis(text).strip()
        if not text:
            return
        if split_sentences:
            sentences = re.split(r'(?<=[.!?])\s+', text)
            for s in sentences:
                s = s.strip()
                if s:
                    self.ctx_swarm["tts_queue"].append({"text": s, "emotion": "neutral"})
        else:
            self.ctx_swarm["tts_queue"].append({"text": text, "emotion": "neutral"})

    def _save_to_history(self, text: str):
        """Save professor response to ctx_chat."""
        clean_msg = self._EMOTION_PAREN_RE.sub('', text)
        clean_msg = self._EMOTION_STAR_RE.sub('', clean_msg).strip()
        if not clean_msg:
            return
        from data_schema.chat_structures import EventBase
        from utils.time_helper import eztime
        prof_event = EventBase(
            processing_timestamp=time.time_ns(),
            date=eztime(),
            env="voice",
            user=get_name(),
            type="chat",
            msg=clean_msg,
            filter_results={"acceptable": True},
        )
        prof_event["self"] = True
        self.ctx_handler.add_message(prof_event)

    # Greeting prefixes to strip from subsequent responses
    _GREETING_PREFIXES = [
        "Привет!", "Привет,", "Привет.", "Привет ",
        "Здравствуйте!", "Здравствуйте,", "Здравствуйте.", "Здравствуйте ",
        "Добрый день!", "Добрый день,", "Добрый день.", "Добрый день ",
        "Доброе утро!", "Доброе утро,", "Доброе утро.", "Доброе утро ",
        "Добрый вечер!", "Добрый вечер,", "Добрый вечер.", "Добрый вечер ",
    ]

    MAX_CTX_CHAT = 200

    _LECTURE_QUERIES = [
        "о чём пара", "о чем пара", "что происходит", "что сейчас",
        "о чём лекция", "о чем лекция", "что обсуждали", "что было",
        "конспект", "что проходили", "о чём говорили", "о чем говорили",
    ]

    _LECTURE_STOP_WORDS = ["стоп", "подожди", "пауза", "секунду", "помолчи"]
    _LECTURE_REPEAT_WORDS = ["повтори", "ещё раз", "еще раз", "не понял", "непонятно"]

    # ------------------------------------------------------------------
    # Lecture mode
    # ------------------------------------------------------------------

    def load_lecture(self, plan_path: str):
        """Load a pre-prepared lecture plan and start delivery."""
        _agent_log(f"[LECTURE] Loading plan from: {plan_path}")
        try:
            self._lecture_delivery = LectureDelivery.load_plan(plan_path)
            self._lecture_phase = "delivering"
            self._lecture_waiting_reply = False
            self._send_to_tts(f"Начинаем лекцию: {self._lecture_delivery.topic}.")
            _agent_log(f"[LECTURE] Loaded: {self._lecture_delivery.total_blocks} blocks")
        except Exception as e:
            _agent_log(f"[LECTURE] Load failed: {e}")
            self._send_to_tts("Не удалось загрузить план лекции.")

    def start_lecture(self, topic: str, duration_min: int = 30):
        """Prepare and start a lecture on the given topic."""
        _agent_log(f"[LECTURE] Preparing lecture: '{topic}', {duration_min} min")
        self._send_to_tts(f"Готовлю лекцию по теме: {topic}. Одну минуту.")

        # Gather RAG context for the topic
        rag_context = ""
        if self.rag_model:
            rag_context = self.rag_model.explain(topic) or ""

        try:
            plan = prepare_lecture(topic, rag_context, duration_min)
            self._lecture_delivery = LectureDelivery(plan)
            self._lecture_phase = "delivering"
            self._lecture_waiting_reply = False

            # Save plan for debugging
            plan_path = os.path.join("data", "lecture_plans", f"plan_{int(time.time())}.json")
            self._lecture_delivery.save_plan(plan_path)

            self._send_to_tts(f"Начинаем лекцию: {plan.get('topic', topic)}.")
            _agent_log(f"[LECTURE] Started: {self._lecture_delivery.total_blocks} blocks")
        except Exception as e:
            _agent_log(f"[LECTURE] Preparation failed: {e}")
            traceback.print_exc()
            self._send_to_tts("Не удалось подготовить лекцию. Попробуйте ещё раз.")

    def stop_lecture(self):
        """Stop lecture and return to normal mode."""
        self._lecture_phase = "idle"
        self._lecture_delivery = None
        self._lecture_waiting_reply = False
        self._lecture_paused = False
        self._quiz_questions = []
        self._quiz_idx = 0
        _agent_log("[LECTURE] Stopped")

    def _check_for_new_student_msg(self) -> str:
        """Check if there's a NEW (unhandled) student message in ctx_chat."""
        recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=5)
        for m in reversed(recent):
            if not m.get("self"):
                ts = m.get("processing_timestamp", 0)
                if ts > self._lecture_last_handled_ts:
                    self._lecture_last_handled_ts = ts
                    return m.get("msg", "")
                break  # already handled this one
        return ""

    def _lecture_step(self):
        """One iteration of lecture delivery loop."""
        delivery = self._lecture_delivery
        if not delivery or not delivery.active:
            self._enter_qa_audience()
            return

        block = delivery.get_current_block()
        if block is None:
            self._enter_qa_audience()
            return

        _agent_log(f"[LECTURE] Block {delivery.progress}: type={block.get('type')}, "
                   f"style={block.get('delivery_style')}")

        # Build prompt and stream through Mistral → TTS
        delivery_prompt = delivery.build_delivery_prompt(block)
        _agent_log(f"[LECTURE] Delivery prompt: {len(delivery_prompt)} chars")
        messages = [
            {"role": "system", "content": DELIVERY_SYSTEM_PROMPT},
            {"role": "user", "content": delivery_prompt},
        ]

        _chat_len_before = len(self.ctx_handler.ctx_chat)
        interrupted = False
        spoken_sentences = []

        _agent_log("[LECTURE] Starting LLM stream...")
        _lec_sentence_count = 0
        _lec_stream_start = time.time()
        for sentence in stream_response_sentences(
            messages,
            temperature=LECTURE_TEMPERATURE,
            max_tokens=LECTURE_BLOCK_MAX_TOKENS,
        ):
            _lec_sentence_count += 1
            _agent_log(f"[LECTURE] sentence #{_lec_sentence_count}: '{sentence[:60]}'")

            spoken_sentences.append(sentence)
            self._send_to_tts(sentence)

            # Hard timeout for the entire block
            if time.time() - _lec_stream_start > LECTURE_STREAM_TIMEOUT_S:
                _agent_log(f"[LECTURE] Block stream timeout ({LECTURE_STREAM_TIMEOUT_S}s)")
                break
        _agent_log(f"[LECTURE] Stream done: {_lec_sentence_count} sentences")

        spoken_text = " ".join(spoken_sentences).strip()

        # Humor injection in lecture blocks
        if not interrupted and spoken_text and _lec_sentence_count >= 2:
            _topic = " ".join(block.get("key_points", [])[:1])[:100] or "лекция"
            _meta = getattr(self, '_last_meta_result', {}) or {"mood": "спокоен", "request_type": "теория"}
            _interactions = 5  # lecture = familiar context
            _with_humor = try_humor(
                response_text=spoken_text, topic=_topic,
                meta_result=_meta, student_msg="",
                student_interactions=_interactions,
            )
            if _with_humor != spoken_text:
                _humor_line = _with_humor.replace(spoken_text, "").strip()
                if _humor_line:
                    self._send_to_tts(_humor_line)
                    spoken_text = _with_humor
                    _agent_log(f"[HUMOR] Injected in lecture block: '{_humor_line[:60]}'")

        if spoken_text:
            self._save_to_history(spoken_text + (" [прервано студентом]" if interrupted else ""))

        # Update baseline AFTER saving history (so our own message doesn't trigger interrupt)
        _chat_len_before = len(self.ctx_handler.ctx_chat)

        # If interrupted, handle student message
        if interrupted:
            self._handle_lecture_interrupt()
            return

        # Wait for TTS to finish playing before advancing
        _tts_wait_start = time.time()
        _tts_q_logged = False
        while len(self.ctx_swarm["tts_queue"]) > 0 and time.time() - _tts_wait_start < 120:
            if not _tts_q_logged:
                _agent_log(f"[LECTURE] Waiting for TTS queue ({len(self.ctx_swarm['tts_queue'])} items)")
                _tts_q_logged = True
            time.sleep(TTS_POLL_INTERVAL_S)

        # Advance to next block
        delivery.advance()

        # Check question if the block has one
        check_q = block.get("check_question")
        if check_q:
            time.sleep(CHECK_QUESTION_DELAY_S)
            self._send_to_tts(check_q)
            self._save_to_history(check_q)
            self._lecture_waiting_reply = True
            self._waiting_for_reply = True
            self._silence_hint_sent = False
            self._last_response_time = time.time()
            return

        # Inter-block pause: listen for student
        time.sleep(INTER_BLOCK_PAUSE_S)

        # Check if student said something during the pause
        if len(self.ctx_handler.ctx_chat) > _chat_len_before:
            self._handle_lecture_interrupt()
        else:
            _agent_log(f"[LECTURE] Silence after block, continuing to {delivery.progress}")

    def _handle_lecture_interrupt_with_msg(self, student_msg: str):
        """Handle a known student message during lecture (skip msg lookup)."""
        # Reuse the main handler but with pre-fetched message
        self._handle_lecture_interrupt(_override_msg=student_msg)

    _END_LECTURE_PHRASES = (
        "завершаем пару", "заканчиваем пару", "конец пары", "закончим пару",
        "завершаем занятие", "заканчиваем занятие",
    )

    def _handle_lecture_interrupt(self, _override_msg: str = None, _resume_after: bool = True):
        """Handle a student message during lecture delivery.

        Any incoming sound = TTS paused (already happened at STT level).
        We wait for transcription, then decide:
        - End-lecture command → farewell
        - Empty/noise → resume where we stopped
        - Backchannel → resume
        - Repeat request → re-explain block
        - Question → answer separately, then resume (if _resume_after)
        """
        student_msg = _override_msg or self._check_for_new_student_msg()

        msg_lower = (student_msg or "").strip().lower().rstrip(".!?,")
        _agent_log(f"[LECTURE] Student said: '{(student_msg or '')[:60]}'")

        # End-lecture voice command — overrides everything else
        if msg_lower and any(p in msg_lower for p in self._END_LECTURE_PHRASES):
            _agent_log("[LECTURE] End-lecture command detected")
            self._enter_farewell()
            return

        # Empty message or noise — resume lecture
        if not msg_lower:
            _agent_log("[LECTURE] Empty/noise, resuming")
            return

        # Backchannel — resume
        if msg_lower in BACKCHANNEL_PATTERNS:
            _agent_log("[LECTURE] Backchannel, resuming")
            return

        # During lecture: only respond if addressed to professor or is a clear question
        _PROFESSOR_NAMES = ["профессор", "преподаватель", "препод"]
        _is_addressed = any(n in msg_lower for n in _PROFESSOR_NAMES)
        _is_question = msg_lower.rstrip().endswith("?") or any(w in msg_lower for w in [
            "что такое", "как работает", "зачем", "почему", "можно ли",
            "объясни", "расскажи", "не понял", "повтори",
        ])
        if not _is_addressed and not _is_question:
            _agent_log(f"[LECTURE] Not addressed to professor, ignoring: '{student_msg[:50]}'")
            return

        # Repeat / didn't understand
        if any(w in msg_lower for w in self._LECTURE_REPEAT_WORDS) and len(student_msg) < 50:
            _agent_log("[LECTURE] Repeating block with simpler style")
            self._lecture_delivery.rewind_current(simpler=True)
            self._send_to_tts("Хорошо, объясню иначе.")
            return

        # Any other speech = question → answer separately with RAG
        _agent_log(f"[LECTURE] Answering question: '{student_msg[:60]}'")

        rag_context = ""
        if self.rag_model:
            try:
                rag_context = self.rag_model.explain(student_msg) or ""
            except Exception:
                pass

        q_prompt = f"Вопрос студента: {student_msg}"
        if rag_context:
            q_prompt += f"\n\nКонтекст из материалов курса:\n{rag_context}"

        messages = [
            {"role": "system", "content": (
                DELIVERY_SYSTEM_PROMPT +
                "\nСтудент задал вопрос во время лекции. Ответь кратко и по существу (2-4 предложения). "
                "НЕ продолжай лекцию — только ответ на вопрос."
            )},
            {"role": "user", "content": q_prompt},
        ]

        answer_sentences = []
        for sentence in stream_response_sentences(
            messages,
            temperature=LECTURE_QA_TEMPERATURE,
            max_tokens=LECTURE_QA_MAX_TOKENS,
        ):
            answer_sentences.append(sentence)
            self._send_to_tts(sentence)

        answer_text = " ".join(answer_sentences).strip()
        if answer_text:
            self._save_to_history(f"[вопрос: {student_msg}] {answer_text}")
            _agent_log(f"[LECTURE] Answered: {len(answer_sentences)} sentences")

        # Brief pause then continue lecture from where we stopped
        time.sleep(POST_INTERRUPT_PAUSE_S)
        if _resume_after:
            self._send_to_tts("Продолжаем.")
            _agent_log("[LECTURE] Resuming after question")
        else:
            _agent_log("[LECTURE] Question answered (no resume — not in delivery phase)")

    def _enter_qa_audience(self):
        """Transition delivering → qa_audience. Open-floor questions from audience."""
        _agent_log("[LECTURE] → qa_audience")
        self._lecture_phase = "qa_audience"
        self._qa_silence_start = time.time()
        self._qa_no_q_strikes = 0
        self._send_to_tts("На этом основная часть лекции закончена. Есть вопросы по материалу?")

    def _qa_audience_step(self):
        """Listen for free-form audience questions; after silence, move to quiz."""
        msg = self._check_for_new_student_msg()
        if msg:
            msg_lower = msg.strip().lower().rstrip(".!?,")
            # End-lecture command — overrides everything
            if any(p in msg_lower for p in self._END_LECTURE_PHRASES):
                _agent_log("[LECTURE] End-lecture command in qa_audience")
                self._enter_farewell()
                return
            # Skip pure backchannel
            if msg_lower in BACKCHANNEL_PATTERNS:
                self._qa_silence_start = time.time()
                return
            # Treat as a question — answer with RAG via existing handler (no resume hint)
            self._handle_lecture_interrupt(_override_msg=msg, _resume_after=False)
            if self._lecture_phase != "qa_audience":
                return  # phase changed (farewell triggered inside handler)
            self._qa_silence_start = time.time()
            self._qa_no_q_strikes = 0
            return

        # No new message — check silence
        if time.time() - self._qa_silence_start > QA_AUDIENCE_SILENCE_S:
            self._qa_no_q_strikes += 1
            if self._qa_no_q_strikes >= QA_AUDIENCE_MAX_STRIKES:
                self._enter_qa_quiz()
                return
            self._send_to_tts("Ещё вопросы?")
            self._qa_silence_start = time.time()
            return
        time.sleep(QA_POLL_INTERVAL_S)

    def _enter_qa_quiz(self):
        """Transition qa_audience → qa_quiz. Generate and ask check questions."""
        _agent_log("[LECTURE] → qa_quiz")
        delivered = (self._lecture_delivery.blocks_delivered
                     if self._lecture_delivery else [])
        topic = self._lecture_delivery.topic if self._lecture_delivery else ""
        self._send_to_tts("А теперь несколько проверочных вопросов.")
        try:
            self._quiz_questions = generate_quiz_questions(
                delivered, n=QUIZ_QUESTIONS_COUNT, topic=topic,
            )
        except Exception as e:
            _agent_log(f"[LECTURE] Quiz generation failed: {e}")
            traceback.print_exc()
            self._quiz_questions = []
        self._quiz_idx = 0
        self._lecture_phase = "qa_quiz"
        if not self._quiz_questions:
            _agent_log("[LECTURE] No quiz questions generated, skipping to farewell")
            self._enter_farewell()
            return
        # Ask the first question and wait for answer
        self._ask_quiz_question(self._quiz_questions[0])

    def _ask_quiz_question(self, question: str):
        """Speak a quiz question and arm the wait-for-reply state."""
        time.sleep(CHECK_QUESTION_DELAY_S)
        self._send_to_tts(question)
        self._save_to_history(question)
        self._waiting_for_reply = True
        self._silence_hint_sent = False
        self._last_response_time = time.time()

    def _qa_quiz_step(self):
        """Process student answers to quiz questions one by one."""
        msg = self._check_for_new_student_msg()
        if not msg:
            time.sleep(QA_POLL_INTERVAL_S)
            return

        msg_lower = msg.strip().lower().rstrip(".!?,")
        # End-lecture command
        if any(p in msg_lower for p in self._END_LECTURE_PHRASES):
            _agent_log("[LECTURE] End-lecture command in qa_quiz")
            self._waiting_for_reply = False
            self._enter_farewell()
            return
        # Skip backchannel — wait for real answer
        if msg_lower in BACKCHANNEL_PATTERNS:
            return

        # This is the answer to current quiz question
        # (student msg is already in ctx_chat via STT — no need to save again)
        self._waiting_for_reply = False
        _agent_log(f"[LECTURE] Quiz answer #{self._quiz_idx + 1}: '{msg[:80]}'")
        # Short acknowledgement (Lecture mode: no grading; Tutor will override)
        ack = "Хорошо, спасибо."
        self._send_to_tts(ack)
        self._save_to_history(ack)

        self._quiz_idx += 1
        if self._quiz_idx >= len(self._quiz_questions):
            # All questions answered → farewell
            self._enter_farewell()
            return
        # Ask next question
        self._ask_quiz_question(self._quiz_questions[self._quiz_idx])

    def _enter_farewell(self):
        """Speak farewell and stop the lecture cleanly."""
        _agent_log("[LECTURE] → farewell")
        self._lecture_phase = "farewell"
        self._waiting_for_reply = False
        self._silence_hint_sent = False
        self._send_to_tts(LECTURE_FAREWELL_PHRASE)
        self._save_to_history(LECTURE_FAREWELL_PHRASE)

        # Kick off auto-summary export in the background BEFORE TTS drain wait,
        # so SMART_MODEL latency (~10s) overlaps with farewell playback.
        try:
            import threading
            from lecture.lecture_delivery import export_lecture_summary as _export
            _delivery = self._lecture_delivery
            _ctx_snapshot = list(self.ctx_handler.ctx_chat)
            _quiz = list(self._quiz_questions or [])
            threading.Thread(
                target=_export,
                args=(_delivery, _ctx_snapshot, _quiz, "data/lecture_summaries"),
                daemon=True,
            ).start()
        except Exception as e:
            _agent_log(f"[LECTURE-SUMMARY] Failed to start export thread: {e}")

        # Wait for TTS queue to drain so the farewell actually plays out
        wait_start = time.time()
        while len(self.ctx_swarm["tts_queue"]) > 0 and time.time() - wait_start < 60:
            time.sleep(TTS_POLL_INTERVAL_S)
        self.stop_lecture()

    def step(self):
        """Run a single iteration: wait for trigger → stream LLM → sentence TTS.

        Architecture v2: no classification step, direct streaming from Mistral.
        Meta-analysis runs AFTER response in background thread.
        Lecture mode: delivers prepared blocks instead of waiting for triggers.
        """
        try:
            if not self.initialized:
                print("[DEBUG CORE AGENT] NOT INITIALIZED")
                return

            # Check for lecture start command (file signal or ctx_swarm)
            _signal_path = os.path.join("data", "lecture_start_signal.txt")
            if os.path.exists(_signal_path):
                try:
                    with open(_signal_path, "r") as f:
                        _lecture_cmd = f.read().strip()
                    os.remove(_signal_path)
                    if _lecture_cmd:
                        if _lecture_cmd.endswith(".json"):
                            self.load_lecture(_lecture_cmd)
                        else:
                            self.start_lecture(_lecture_cmd)
                        return
                except Exception as e:
                    _agent_log(f"[LECTURE] Signal read error: {e}")

            _lecture_cmd = self.ctx_swarm["env"].get("start_lecture")
            if _lecture_cmd:
                self.ctx_swarm["env"]["start_lecture"] = None
                if _lecture_cmd.endswith(".json"):
                    self.load_lecture(_lecture_cmd)
                else:
                    self.start_lecture(_lecture_cmd)
                return

            # Lecture FSM dispatch
            if self._lecture_phase != "idle":
                _agent_log(f"[LECTURE] step() phase={self._lecture_phase}")
                try:
                    if self._lecture_phase == "delivering":
                        self._lecture_step()
                    elif self._lecture_phase == "qa_audience":
                        self._qa_audience_step()
                    elif self._lecture_phase == "qa_quiz":
                        self._qa_quiz_step()
                    elif self._lecture_phase == "farewell":
                        # farewell is synchronous inside _enter_farewell, this should not normally hit
                        time.sleep(0.2)
                except Exception as e:
                    _agent_log(f"[LECTURE] ERROR in phase={self._lecture_phase}: {e}")
                    traceback.print_exc()
                    time.sleep(AGENT_ERROR_BACKOFF_S)
                return

            # (lecture question answering is now handled inline in _handle_lecture_interrupt)

            _agent_log(f"[AGENT-DEBUG] step() called. interrupted={self._interrupted}, "
                  f"ctx_chat_len={len(self.ctx_handler.ctx_chat)}, "
                  f"meta_running={getattr(self, '_meta_running', False)}, "
                  f"tts_queue_len={len(self.ctx_swarm['tts_queue'])}")

            import random

            # Break reminder (feature 4): once after 60 min
            if not self._break_suggested and (time.time() - self._session_start_time) > BREAK_REMINDER_THRESHOLD_S:
                self._send_to_tts("Мы общаемся уже больше часа. Может, сделаем небольшой перерыв минут на пять?")
                self._break_suggested = True

            # Silence timer (feature 3): check before waiting for trigger
            if self._waiting_for_reply and self._last_response_time > 0:
                silence_duration = time.time() - self._last_response_time
                if silence_duration > SILENCE_HINT_LONG_S and self._silence_hint_sent:
                    self._send_to_tts("Ладно, пойдём дальше. Вернёмся к этому позже.")
                    self._waiting_for_reply = False
                    self._silence_hint_sent = False
                    self._last_response_time = time.time()
                    return
                elif silence_duration > SILENCE_HINT_SHORT_S and not self._silence_hint_sent:
                    self._send_to_tts("Подумай не спеша, я подожду.")
                    self._silence_hint_sent = True
                    return

            # 1. Wait for trigger and build prompt (includes RAG)
            # After interrupt: skip wait_for_trigger, use latest message
            _wait = not self._interrupted
            self._interrupted = False
            if not _wait:
                time.sleep(POST_INTERRUPT_REENTRY_PAUSE_S)
                print("[AGENT] Re-entering after interrupt (no wait)")

            _output_format = "dicts" if self._use_local_llm else "langchain"
            messages, response_starting = construct_prompt_messages(
                [],
                self.ctx_handler,
                rag_model=self.rag_model,
                output_format=_output_format,
                wait_for_trigger=_wait,
            )
            if messages is None:
                return

            # Interrupt: new trigger arrived — stop any ongoing TTS playback
            self._signal_interrupt()
            print("[AGENT] Cleared TTS queue for new response")

            # 2. Get latest student message
            recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=3)
            last_student_msg = ""
            for m in reversed(recent):
                if not m.get("self"):
                    last_student_msg = m.get("msg", "")
                    break

            # 2.5a Backchannel detection: "угу/ага" — skip LLM, no response
            _last_msg_stripped = last_student_msg.strip().lower().rstrip(".!?,")
            if _last_msg_stripped in BACKCHANNEL_PATTERNS:
                _agent_log(f"[AGENT] Backchannel detected, skipping: '{last_student_msg}'")
                return

            # Reset silence timer on real student message
            self._waiting_for_reply = False
            self._silence_hint_sent = False

            # 2.5b Stop commands: don't generate, just acknowledge and wait
            _stop_words = ["стоп", "подождите", "помолчите", "секунду", "погодите", "хватит", "тихо"]
            _msg_lower = last_student_msg.lower()
            if any(w in _msg_lower for w in _stop_words) and len(last_student_msg) < 50:
                print(f"[AGENT] Stop command detected: '{last_student_msg}'")
                self.ctx_swarm["tts_queue"].append({"text": "Хорошо, слушаю.", "emotion": "neutral"})
                self._save_to_history("Хорошо, слушаю.")
                return

            # 3. Inject cached student profile (from last meta-analysis)
            if self._current_student and self._profile_mgr:
                profile_text = self._profile_mgr.get_profile_for_prompt(self._current_student)
                if profile_text:
                    messages.insert(-1, self._build_system_msg(f"Профиль студента: {profile_text}"))

            # 3.5 Inject live lecture context if student asks about the lecture
            lecture_summary = self.ctx_swarm["env"].get("lecture_summary", "")
            if lecture_summary and any(q in last_student_msg.lower() for q in self._LECTURE_QUERIES):
                _lec_content = "КОНСПЕКТ ТЕКУЩЕЙ ЛЕКЦИИ (используй для ответа):\n" + lecture_summary
                messages.insert(1, self._build_system_msg(_lec_content))
                print(f"[AGENT] Injected lecture summary ({len(lecture_summary)} chars)")

            self.ctx_swarm["fx_queue"].put("thinking")

            # 4. STREAM response — sentences go to TTS as they arrive
            # Short messages get fewer tokens to prevent hallucination dumps
            _max_tokens = (RESPONSE_MAX_TOKENS_SHORT if len(last_student_msg) < 25
                           else RESPONSE_MAX_TOKENS_LONG)
            _chat_len_before = len(self.ctx_handler.ctx_chat)
            interrupted = False

            # 4a. Optional skeleton pass: build a hidden outline, then deliver
            # against it with a [END] stop sequence so the model halts when the
            # plan is fully covered (no overshoot to max_tokens).
            outline_text: Optional[str] = None
            stop_sequences: Optional[list] = None
            if self._use_local_llm and _should_use_skeleton(last_student_msg):
                # Skeleton fills out a multi-point plan; SHORT cap (300) starves it.
                # Force LONG cap so Pass 2 can complete and emit [END] cleanly.
                _max_tokens = RESPONSE_MAX_TOKENS_LONG
                _t_outline = time.perf_counter()
                outline_text = self._build_outline(messages)
                _outline_ms = (time.perf_counter() - _t_outline) * 1000
                if outline_text and self._outline_has_points(outline_text):
                    _agent_log(
                        f"[SKELETON] outline ({_outline_ms:.0f}ms): "
                        f"{outline_text[:200].replace(chr(10), ' | ')}"
                    )
                    # Pass 2 messages: original chat + outline as assistant turn
                    # + delivery instructions as system message.
                    delivery_instructions = (
                        "Теперь развёрнуто объясни студенту по плану выше. "
                        "Каждый пункт — 2-4 связных предложения, говори естественно, "
                        "не цитируй сам план буквально, не пиши номера пунктов как часть текста. "
                        f"Когда полностью раскроешь все пункты, напиши {SKELETON_END_MARKER} "
                        "и больше ничего не пиши.\n"
                        "Обязательно начни ответ со слова TRIGGER_START."
                    )
                    messages = list(messages) + [
                        {"role": "assistant", "content": outline_text}
                        if self._use_local_llm
                        else self._build_system_msg(outline_text),
                        self._build_system_msg(delivery_instructions),
                    ]
                    stop_sequences = [SKELETON_END_MARKER]
                    # Check interrupt before starting Pass 2
                    if len(self.ctx_handler.ctx_chat) > _chat_len_before:
                        _agent_log("[SKELETON] interrupted during outline — abort")
                        return
                else:
                    _agent_log(
                        f"[SKELETON] outline rejected ({_outline_ms:.0f}ms), falling back"
                    )
                    outline_text = None

            t0 = time.perf_counter()
            messages_dicts = messages if self._use_local_llm else self._to_dicts(messages)
            _llm_label = "LM Studio (local)" if self._use_local_llm else "Mistral API"
            _agent_log(
                f"[AGENT] Starting LLM stream via {_llm_label} "
                f"(max_tokens={_max_tokens}, skeleton={bool(outline_text)}, "
                f"msg='{last_student_msg[:50]}')"
            )
            spoken_sentences = []   # sentences actually sent to TTS
            sentence_count = 0

            for sentence in stream_response_sentences(
                messages_dicts,
                temperature=random.uniform(RESPONSE_TEMPERATURE_LOW, RESPONSE_TEMPERATURE_HIGH),
                max_tokens=_max_tokens,
                stop=stop_sequences,
            ):
                # Check: student started speaking → wait for STT
                if self.ctx_swarm["voice"].get("student_speaking"):
                    print(f"[AGENT] Student speaking — waiting for STT")
                    interrupted = True
                    self._signal_interrupt()
                    _wait_start = time.time()
                    while self.ctx_swarm["voice"].get("student_speaking") and time.time() - _wait_start < 15:
                        time.sleep(STT_POLL_INTERVAL_S)
                    break

                # Check if student interrupted (new message in ctx_chat)
                if len(self.ctx_handler.ctx_chat) > _chat_len_before:
                    print(f"[AGENT] Student interrupted — stopping generation")
                    interrupted = True
                    self._signal_interrupt()
                    break

                # Strip greeting from first sentence if already greeted
                if sentence_count == 0 and self._greeting_sent:
                    for g in self._GREETING_PREFIXES:
                        if sentence.startswith(g):
                            sentence = sentence[len(g):].strip()
                            print(f"[AGENT] Stripped repeated greeting: '{g}'")
                            break
                    if not sentence:
                        continue  # skip empty sentence after greeting removal
                elif sentence_count == 0:
                    self._greeting_sent = True

                sentence_count += 1
                spoken_sentences.append(sentence)

                # Push each sentence to TTS immediately
                self._send_to_tts(sentence, split_sentences=False)

                elapsed = (time.perf_counter() - t0) * 1000
                print(f"[AGENT] sentence #{sentence_count} ({elapsed:.0f}ms): "
                      f"'{sentence[:60]}'")

            elapsed = (time.perf_counter() - t0) * 1000
            spoken_text = " ".join(spoken_sentences).strip()

            # 5. Humor injection (after streaming, before history save)
            # Disabled for local LLM — humor module duplicates the response
            if not self._use_local_llm and not interrupted and spoken_text and sentence_count >= 2:
                _topic = last_student_msg[:100] if last_student_msg else "общая тема"
                _student_interactions = 0
                if self._current_student and self._profile_mgr:
                    try:
                        _prof = self._profile_mgr.get_or_create_student(self._current_student)
                        _student_interactions = _prof.get("total_interactions", 0)
                    except Exception:
                        pass
                _meta = getattr(self, '_last_meta_result', {}) or {}
                _with_humor = try_humor(
                    response_text=spoken_text,
                    topic=_topic,
                    meta_result=_meta,
                    student_msg=last_student_msg,
                    student_interactions=_student_interactions,
                )
                if _with_humor != spoken_text:
                    # Extract the injected humor line and send to TTS
                    _humor_line = _with_humor.replace(spoken_text, "").strip()
                    if _humor_line:
                        self._send_to_tts(_humor_line)
                        spoken_text = _with_humor

            if interrupted:
                print(f"[AGENT] Interrupted after {sentence_count} sentences, "
                      f"{elapsed:.0f}ms, spoken: '{spoken_text[:80]}'")
                if spoken_text:
                    self._save_to_history(spoken_text + " [прервано студентом]")
            else:
                print(f"[AGENT] Streaming done: {sentence_count} sentences, "
                      f"{elapsed:.0f}ms, {len(spoken_text)} chars")
                if spoken_text:
                    self._save_to_history(spoken_text)

            # Retry on empty response (LLM error / timeout)
            if not spoken_text and not interrupted:
                self._retry_count = getattr(self, '_retry_count', 0) + 1
                if self._retry_count <= 3:
                    _agent_log(f"[AGENT] Empty response from LLM — retry {self._retry_count}/3")
                    time.sleep(AGENT_ERROR_BACKOFF_S)
                    self._interrupted = True
                    return
                else:
                    _agent_log("[AGENT] LLM failed after 3 retries — notifying student")
                    self._send_to_tts("Извини, сервер не отвечает. Попробуй спросить ещё раз через минуту.")
                    self._retry_count = 0
                    return

            self._retry_count = 0  # reset on successful response

            # Silence timer: track if professor asked a question
            self._last_response_time = time.time()
            if spoken_text.rstrip().endswith("?"):
                self._waiting_for_reply = True
                self._silence_hint_sent = False
            else:
                self._waiting_for_reply = False

            # 6. Meta-analysis — only if NOT interrupted and no meta already running
            if not interrupted and not getattr(self, '_meta_running', False):
                _spoken = spoken_text
                _student_msg = last_student_msg
                self._meta_running = True
                def _post_response():
                    try:
                        _, _, meta_result = self._run_meta_analysis()
                        self._last_meta_result = meta_result
                        self._update_student_profile(meta_result, _spoken, _student_msg)
                    except Exception as e:
                        print(f"[META BG] Error: {e}")
                    finally:
                        self._meta_running = False
                threading.Thread(target=_post_response, daemon=True).start()

            # 7. If interrupted — flag for immediate re-run (skip wait_for_sync)
            if interrupted:
                self._interrupted = True

            # 8. Trim ctx_chat to prevent unbounded growth
            _chat_len = len(self.ctx_handler.ctx_chat)
            if _chat_len > self.MAX_CTX_CHAT:
                _trim = _chat_len - self.MAX_CTX_CHAT
                for _ in range(_trim):
                    try:
                        self.ctx_handler.ctx_chat.pop(0)
                    except (IndexError, Exception):
                        break
                print(f"[AGENT] Trimmed ctx_chat: {_chat_len} → {len(self.ctx_handler.ctx_chat)}")

            # 9. Push interaction data for metrics
            if spoken_text:
                self.ctx_swarm["env"]["last_interaction"] = {
                    "query": last_student_msg,
                    "response": spoken_text,
                    "response_time_ms": int(elapsed),
                    "emotion": "neutral",
                }

        except Exception as e:
            _agent_log(f"[AGENT] ERROR in step(): {e}")
            traceback.print_exc()
            time.sleep(10)

    def run(self):
        """Main agent loop"""
        _agent_log("[AGENT] === Agent run() started ===")
        self.running = True
        self.ctx_swarm["fx_queue"].put("starting")
        while self.ctx_swarm["env"]["actived"] and self.running:
            self.step()


if __name__ == "__main__":
    import multiprocessing as mp

    from data_schema.structure_templates import create_ctx_swarm

    manager = mp.Manager()
    # Test the agent
    ctx_swarm = create_ctx_swarm(manager)
    ctx_swarm["env"]["actived"] = True
    ctx_handler = CtxHandler(ctx_swarm=ctx_swarm)

    def console_loop():
        while True:
            cmd = input("Enter command: ")
            if cmd == "stop":
                agent.stop()
                break
            else:
                ctx_handler.add_message(cmd)
                print("ctx chat", ctx_handler.get_ctx_chat(dict_format=True, limit=5))
                # print("ctx chat", ctx_handler.get_ctx_chat(limit=5, validate=False, raw=True, dict_format=True))

    s = threading.Thread(target=console_loop, daemon=True)
    s.start()
    agent = CoreAgent(ctx_swarm, ctx_handler=ctx_handler)
    agent.run()
