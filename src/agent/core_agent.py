"""

CORE AGENT

supports streaming output

tools like !tool 123
/command minecraft
@aget action
> speak *emotion*
"""

import importlib
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
from data_schema.tool_structures import ToolBankType

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
from agent.tools import tools_config
from agent.meta_agent import analyze_context, build_meta_instruction, extract_student_info
from agent.tools.base_tools import _parse_emotion
from lecture.student_profiles import StudentProfileManager
from utils.patterns import BACKCHANNEL_PATTERNS
from lecture.lecture_delivery import LectureDelivery, prepare_lecture, DELIVERY_SYSTEM_PROMPT
from agent.tools.tool_executor import execute_tools
from agent.tools.tools import execute_tool_query, get_tool_records, default_exec_callaback
from config_schema.general import get_name
from utils.debug import bcolors
from data_flow.ctx_handler import CtxHandler
from utils.debug import print_messages


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
        tool_bank: Optional[ToolBankType] = None,
    ):
        """Initialize the agent with context swarm"""
        super().__init__(ctx_swarm, ctx_handler)
        if ctx_handler is None:
            self.ctx_handler = CtxHandler(ctx_swarm)
        else:
            self.ctx_handler = ctx_handler

        # Initialize LLM
        self.llm = get_llm_chain()
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

        # Lecture mode
        self._lecture_mode = False
        self._lecture_delivery = None
        self._lecture_waiting_reply = False  # waiting for check_question answer

        if tool_bank is not None:
            self.tool_bank = tool_bank
        else:
            self.tool_bank = tools_config.init_tools_module(
                ctx_swarm, self.ctx_handler, new_llm=self.llm
            )
        print("tool bank init")
        if ctx_host is None:
            self.ctx_host = CtxHost(ctx_handler, tool_bank=self.tool_bank)
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
        if hasattr(self, "llm"):
            del self.llm
        if hasattr(self, "rag_model"):
            del self.rag_model
        if hasattr(self, "ctx_host"):
            del self.ctx_host
        # Reset tools config globals
        importlib.reload(tools_config)

    def reload(self):
        """Safely reload the agent and tools"""
        with self.cleanup_context():
            # Reload all dependent modules
            importlib.reload(sys.modules["agent.tools.tools"])
            importlib.reload(sys.modules["agent.tools.tools_config"])
            importlib.reload(sys.modules[__name__])

            # Reinitialize
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
            self._lecture_mode = True
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
        self._lecture_mode = False
        self._lecture_delivery = None
        self._lecture_waiting_reply = False
        _agent_log("[LECTURE] Stopped")

    def _lecture_step(self):
        """One iteration of lecture delivery loop."""
        from agent.streaming_orchestrator import stream_response_sentences

        delivery = self._lecture_delivery
        if not delivery or not delivery.active:
            self._send_to_tts("На этом лекция закончена. Есть вопросы по всему материалу?")
            self.stop_lecture()
            return

        block = delivery.get_current_block()
        if block is None:
            self._send_to_tts("Лекция завершена. Спрашивайте, если что-то осталось непонятным.")
            self.stop_lecture()
            return

        _agent_log(f"[LECTURE] Block {delivery.progress}: type={block.get('type')}, "
                   f"style={block.get('delivery_style')}")

        # Build prompt and stream through Mistral → TTS
        delivery_prompt = delivery.build_delivery_prompt(block)
        messages = [
            {"role": "system", "content": DELIVERY_SYSTEM_PROMPT},
            {"role": "user", "content": delivery_prompt},
        ]

        _chat_len_before = len(self.ctx_handler.ctx_chat)
        interrupted = False
        spoken_sentences = []

        for sentence in stream_response_sentences(messages, temperature=0.6, max_tokens=300):
            # Check for student interrupt
            if len(self.ctx_handler.ctx_chat) > _chat_len_before:
                _agent_log("[LECTURE] Student interrupted during block")
                interrupted = True
                tts_q = self.ctx_swarm["tts_queue"]
                tts_q[:] = []
                tts_q.append({"text": "interrupt", "emotion": "interrupt"})
                break
            spoken_sentences.append(sentence)
            self._send_to_tts(sentence)

        spoken_text = " ".join(spoken_sentences).strip()
        if spoken_text:
            self._save_to_history(spoken_text + (" [прервано студентом]" if interrupted else ""))

        # If interrupted, handle student message
        if interrupted:
            self._handle_lecture_interrupt()
            return

        # Advance to next block
        delivery.advance()

        # Check question if the block has one
        check_q = block.get("check_question")
        if check_q:
            time.sleep(1.5)
            self._send_to_tts(check_q)
            self._save_to_history(check_q)
            self._lecture_waiting_reply = True
            self._waiting_for_reply = True
            self._silence_hint_sent = False
            self._last_response_time = time.time()
            return

        # Inter-block pause: listen for 3 seconds
        time.sleep(3)

        # Check if student said something during the pause
        if len(self.ctx_handler.ctx_chat) > _chat_len_before:
            self._handle_lecture_interrupt()
        else:
            _agent_log(f"[LECTURE] Silence after block, continuing to {delivery.progress}")

    def _handle_lecture_interrupt(self):
        """Handle a student message during lecture delivery."""
        recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=3)
        student_msg = ""
        for m in reversed(recent):
            if not m.get("self"):
                student_msg = m.get("msg", "")
                break

        msg_lower = student_msg.strip().lower().rstrip(".!?,")
        _agent_log(f"[LECTURE] Student said: '{student_msg[:60]}'")

        # Backchannel — continue
        if msg_lower in BACKCHANNEL_PATTERNS:
            _agent_log("[LECTURE] Backchannel, continuing")
            return

        # Stop / pause
        if any(w in msg_lower for w in self._LECTURE_STOP_WORDS) and len(student_msg) < 50:
            self._send_to_tts("Хорошо, жду. Скажи когда продолжать.")
            self._save_to_history("Хорошо, жду. Скажи когда продолжать.")
            # Wait for "continue" trigger
            self._lecture_waiting_reply = True
            self._waiting_for_reply = True
            self._last_response_time = time.time()
            return

        # Repeat / didn't understand
        if any(w in msg_lower for w in self._LECTURE_REPEAT_WORDS) and len(student_msg) < 50:
            _agent_log("[LECTURE] Repeating block with simpler style")
            self._lecture_delivery.rewind_current(simpler=True)
            self._send_to_tts("Хорошо, объясню иначе.")
            return

        # Check-question answer (if waiting)
        if self._lecture_waiting_reply and self._lecture_delivery.blocks_delivered:
            react_prompt = self._lecture_delivery.build_react_prompt(student_msg)
            if react_prompt:
                from agent.streaming_orchestrator import stream_response_sentences
                messages = [
                    {"role": "system", "content": DELIVERY_SYSTEM_PROMPT},
                    {"role": "user", "content": react_prompt},
                ]
                for sentence in stream_response_sentences(messages, temperature=0.5, max_tokens=100):
                    self._send_to_tts(sentence)
                self._lecture_waiting_reply = False
                self._waiting_for_reply = False
                return

        # Regular question — answer via normal RAG pipeline, then continue
        _agent_log("[LECTURE] Answering student question, then continuing")
        self._lecture_mode = False  # temporarily disable lecture mode
        self._interrupted = True   # process this message in normal step()
        # After normal step() answers, lecture_mode will be re-enabled
        # via _post_lecture_question flag
        self._post_lecture_question = True

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

            # Lecture mode dispatch
            if self._lecture_mode and self._lecture_delivery:
                _agent_log(f"[LECTURE] step() — block {self._lecture_delivery.progress}")
                self._lecture_step()
                return

            # Re-enter lecture after answering a student question
            if getattr(self, '_post_lecture_question', False) and self._lecture_delivery:
                self._post_lecture_question = False
                self._lecture_mode = True
                self._send_to_tts("Продолжаем лекцию.")
                _agent_log("[LECTURE] Resuming after student question")
                return

            _agent_log(f"[AGENT-DEBUG] step() called. interrupted={self._interrupted}, "
                  f"ctx_chat_len={len(self.ctx_handler.ctx_chat)}, "
                  f"meta_running={getattr(self, '_meta_running', False)}, "
                  f"tts_queue_len={len(self.ctx_swarm['tts_queue'])}")

            import random
            from agent.streaming_orchestrator import stream_response_sentences

            # Break reminder (feature 4): once after 60 min
            if not self._break_suggested and (time.time() - self._session_start_time) > 3600:
                self._send_to_tts("Мы общаемся уже больше часа. Может, сделаем небольшой перерыв минут на пять?")
                self._break_suggested = True

            # Silence timer (feature 3): check before waiting for trigger
            if self._waiting_for_reply and self._last_response_time > 0:
                silence_duration = time.time() - self._last_response_time
                if silence_duration > 30 and self._silence_hint_sent:
                    self._send_to_tts("Ладно, пойдём дальше. Вернёмся к этому позже.")
                    self._waiting_for_reply = False
                    self._silence_hint_sent = False
                    self._last_response_time = time.time()
                    return
                elif silence_duration > 10 and not self._silence_hint_sent:
                    self._send_to_tts("Подумай не спеша, я подожду.")
                    self._silence_hint_sent = True
                    return

            # 1. Wait for trigger and build prompt (includes RAG)
            # After interrupt: skip wait_for_trigger, use latest message
            _wait = not self._interrupted
            self._interrupted = False
            if not _wait:
                time.sleep(1.0)  # brief pause for STT to finish
                print("[AGENT] Re-entering after interrupt (no wait)")
            messages, response_starting = construct_prompt_messages(
                get_tool_records(),
                self.ctx_handler,
                rag_model=self.rag_model,
                output_format="langchain",
                tool_use_format="command",
                wait_for_trigger=_wait,
            )
            if messages is None:
                return

            # Interrupt: new trigger arrived — stop any ongoing TTS playback
            tts_q = self.ctx_swarm["tts_queue"]
            if len(tts_q) > 0:
                tts_q[:] = []
            tts_q.append({"text": "interrupt", "emotion": "interrupt"})
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
                    from langchain_core.messages import SystemMessage as _SM
                    messages.insert(-1, _SM(content=f"Профиль студента: {profile_text}"))

            # 3.5 Inject live lecture context if student asks about the lecture
            lecture_summary = self.ctx_swarm["env"].get("lecture_summary", "")
            if lecture_summary and any(q in last_student_msg.lower() for q in self._LECTURE_QUERIES):
                from langchain_core.messages import SystemMessage as _SM
                messages.insert(1, _SM(content=(
                    "КОНСПЕКТ ТЕКУЩЕЙ ЛЕКЦИИ (используй для ответа):\n" + lecture_summary
                )))
                print(f"[AGENT] Injected lecture summary ({len(lecture_summary)} chars)")

            self.ctx_swarm["fx_queue"].put("thinking")

            # 4. STREAM response — sentences go to TTS as they arrive
            # Short messages get fewer tokens to prevent hallucination dumps
            _max_tokens = 150 if len(last_student_msg) < 25 else 500
            t0 = time.perf_counter()
            messages_dicts = self._to_dicts(messages)
            _agent_log(f"[AGENT] Starting LLM stream (max_tokens={_max_tokens}, "
                  f"msg='{last_student_msg[:50]}')")
            spoken_sentences = []   # sentences actually sent to TTS
            sentence_count = 0
            _chat_len_before = len(self.ctx_handler.ctx_chat)
            interrupted = False

            for sentence in stream_response_sentences(
                messages_dicts,
                temperature=random.uniform(0.4, 0.75),
                max_tokens=_max_tokens,
            ):
                # Check if student interrupted (new message in ctx_chat)
                if len(self.ctx_handler.ctx_chat) > _chat_len_before:
                    print(f"[AGENT] Student interrupted — stopping generation")
                    interrupted = True
                    tts_q = self.ctx_swarm["tts_queue"]
                    tts_q[:] = []
                    tts_q.append({"text": "interrupt", "emotion": "interrupt"})
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
                    _agent_log(f"[AGENT] Empty response from LLM — retry {self._retry_count}/3 in 3s")
                    time.sleep(3)
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
