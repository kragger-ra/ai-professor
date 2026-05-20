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
# Voice-friendly Q&A caps. Previously 2000/5000 — that let GPT-5.4 generate
# 90+ second monologues that no student listened to fully, and on long recap
# questions the request would hang OpenAI-side past our timeouts (incident
# 2026-05-17 ~00:01, see project_streaming_hang_2026_05_17). 1000 tokens
# ≈ 60s of TTS speech which is the realistic ceiling for one turn anyway.
RESPONSE_MAX_TOKENS_SHORT = 400
RESPONSE_MAX_TOKENS_LONG = 1000

RESPONSE_TEMPERATURE_LOW = 0.4
RESPONSE_TEMPERATURE_HIGH = 0.75
TTS_POLL_INTERVAL_S = 0.3
STT_POLL_INTERVAL_S = 0.2
INTER_BLOCK_PAUSE_S = 3
POST_INTERRUPT_PAUSE_S = 2
CHECK_QUESTION_DELAY_S = 1.5
POST_INTERRUPT_REENTRY_PAUSE_S = 1.0
AGENT_ERROR_BACKOFF_S = 3
BREAK_REMINDER_THRESHOLD_S = 3600       # 60 min
STREAM_TOKEN_TIMEOUT_S = 10             # per-token idle timeout in streaming_orchestrator


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
        # Set True after a bare "загрузи курс" without a name; the next
        # student utterance is interpreted as the course name.
        self._awaiting_course_name = False

        # Break reminder
        self._session_start_time = time.time()
        self._break_suggested = False

        # Manner of explanation, switched by student commands.
        # simpler   (default) — bytovye analogii, korotkie phrases
        # neutral             — academic neutral
        # detailed            — full definitions, terminology
        self._manner = "simpler"

        # Pause-on-request: when set to a future timestamp, STT input is
        # ignored unless it matches an explicit resume phrase.
        self._paused_until: Optional[float] = None

        # Meta-agent outputs cached from the previous turn. They are injected
        # into the NEXT prompt, so style_hint / level / mood from now propagate
        # forward instead of vanishing into _last_meta_result.
        self._last_meta_instruction: str = ""
        self._last_student_profile: str = ""

        # Last spoken response, kept for resume after an interrupt.
        # Structure: {"sentences": list[str], "started_at": float}.
        # Updated at the end of every successful or interrupted stream.
        # _replay_unspoken walks voice["last_played_text"] against this list
        # to figure out which tail still needs to be re-sent to TTS.
        self._pending_response: Optional[dict] = None
        # Guards _replay_unspoken against being run twice concurrently
        # (auto-resume watcher + explicit "продолжай" can both fire).
        self._resume_in_flight: bool = False

        # Heartbeat for the run() watchdog. step() pings this whenever it
        # finishes a stage; the watchdog tears down the iteration if it
        # stays silent for _STEP_HEARTBEAT_DEADLINE_S.
        self._last_heartbeat: float = time.time()

        # Background daemon: auto-replay unspoken tail after a silent RMS flap
        # (cough / chair / mic bump that didn't produce a transcribed message).
        # Spawned here so the watcher exists as soon as the agent does.
        self.running = True
        threading.Thread(
            target=self._auto_resume_watcher,
            daemon=True,
            name="AutoResumeWatcher",
        ).start()

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
    # Markdown that Vosk doesn't render — strip before TTS to avoid empty-WAV drops.
    _MD_CODE_SPAN_RE = re.compile(r'`+([^`]+)`+')   # `code` → code
    _MD_BOLD_RE = re.compile(r'\*\*([^*]+)\*\*')    # **bold** → bold
    _MD_ITALIC_UNDERSCORE_RE = re.compile(r'(?<!\w)_([^_\n]+)_(?!\w)')   # _italic_ → italic
    _MD_HEADING_RE = re.compile(r'^\s{0,3}#{1,6}\s+', re.MULTILINE)
    _MD_BULLET_RE = re.compile(r'^\s*[-*+]\s+', re.MULTILINE)
    _BACKSLASH_ESCAPE_RE = re.compile(r'\\([_*`])')  # \_ \* \` from LLM markdown-escapes

    @classmethod
    def _strip_markdown_for_tts(cls, text: str) -> str:
        """Remove markdown that Vosk can't pronounce but doesn't drop silently."""
        if not text:
            return text
        text = cls._MD_BOLD_RE.sub(r'\1', text)
        text = cls._MD_CODE_SPAN_RE.sub(r'\1', text)
        text = cls._MD_ITALIC_UNDERSCORE_RE.sub(r'\1', text)
        text = cls._MD_HEADING_RE.sub('', text)
        text = cls._MD_BULLET_RE.sub('', text)
        text = cls._BACKSLASH_ESCAPE_RE.sub(r'\1', text)
        return text

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
        text = self._strip_markdown_for_tts(text)
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
        """Persist a one-row interaction log for this turn.

        The richer profile_updates (tech_level / topics_of_interest /
        known_issues / personality_notes) were removed when the meta-agent
        was slimmed to six fields — those updates were unreliable on small
        models and didn't survive between sessions during апробация anyway.
        weak_blocks still get populated separately by quiz_session.
        """
        if not self._profile_mgr or not self._current_student or not meta_result:
            return
        try:
            self._profile_mgr.log_interaction(
                self._current_student, student_msg, agent_response,
                meta_analysis=str(meta_result),
                emotion=meta_result.get("mood", "спокоен"),
            )
        except Exception as e:
            print(f"[META] log_interaction error: {e}")

    def _signal_interrupt(self) -> None:
        """Clear the TTS queue and push an interrupt sentinel.

        Central helper for the pattern repeated across step() / lecture flow
        whenever the student preempts ongoing speech.
        """
        tts_q = self.ctx_swarm["tts_queue"]
        if len(tts_q) > 0:
            tts_q[:] = []
        tts_q.append({"text": "interrupt", "emotion": "interrupt"})

    # Phrases that mean "carry on where you left off" as the whole utterance.
    # Embedded in a longer sentence ("продолжай и объясни про X") → NOT a
    # resume; falls through to LLM as a normal request.
    _RESUME_PHRASE_RE = re.compile(
        r"^(?:профессор[,\s]+)?"
        r"(?:продолж(?:ай|и|им|айте)|давай(?:те)?\s+дальше|и\s+дальше|дальше)"
        r"\s*[.!?]?\s*$",
        re.IGNORECASE,
    )

    def _is_resume_phrase(self, msg: str) -> bool:
        return bool(msg) and bool(self._RESUME_PHRASE_RE.match(msg.strip()))

    def _replay_unspoken(self) -> bool:
        """Re-send sentences from _pending_response that haven't been played.

        Uses voice["last_played_text"] (set by the TTS handler after each
        sentence completes playback) to find the resume index. Repeats the
        last-played sentence too so the student hears a context lead-in
        instead of starting mid-thought.

        Returns True if anything was replayed.
        """
        pending = self._pending_response
        if not pending or not pending.get("sentences"):
            return False
        if self._resume_in_flight:
            return False
        self._resume_in_flight = True
        try:
            sentences: list = pending["sentences"]
            try:
                last_played = (
                    self.ctx_swarm["voice"].get("last_played_text") or ""
                ).strip()
            except Exception:
                last_played = ""
            played_idx = -1
            if last_played:
                for i, s in enumerate(sentences):
                    if (s or "").strip() == last_played:
                        played_idx = i
                        break
            # Replay starting from the last played sentence: repeating one
            # sentence is the cheap price for the student knowing we resumed.
            start = max(0, played_idx)
            tail = sentences[start:]
            if not tail:
                _agent_log(
                    f"[AGENT] Replay: nothing to replay "
                    f"(played_idx={played_idx}/{len(sentences)})"
                )
                return False
            _agent_log(
                f"[AGENT] Replaying {len(tail)} sentence(s) "
                f"from idx={start}/{len(sentences)}"
            )
            for s in tail:
                self._send_to_tts(s)
            return True
        finally:
            self._resume_in_flight = False

    def _auto_resume_watcher(self) -> None:
        """Daemon: if STT flagged speech but no transcribed message landed
        within 1.5s, treat the flap as noise and replay the un-played tail
        of the last response.

        We deliberately do NOT gate on voice["is_speaking"] because the TTS
        handler tends to leave that flag stuck True after an interrupt (was
        force-reset only in the now-removed blocked-lecture path). Same goes
        for tts_queue length — after the mic_stt_handler pushes its
        interrupt-sentinel, the queue may still hold that one sentinel for a
        moment. Both checks blocked the watcher in the wild.
        """
        _agent_log("[AUTO-RESUME] watcher thread started")
        while True:
            try:
                if not self.running:
                    return
                time.sleep(0.3)
                voice = self.ctx_swarm.get("voice", {}) if hasattr(self.ctx_swarm, "get") else {}
                if not voice.get("student_speaking", False):
                    continue
                # RMS flap observed. Wait 1.5s for STT to either publish a
                # transcribed message (real interrupt) or stay silent (noise).
                flap_at_ns = time.time_ns()
                _agent_log(
                    f"[AUTO-RESUME] flap seen, waiting 1.5s for STT to commit"
                )
                time.sleep(1.5)
                # New event since flap? → real interrupt, step() handles it.
                try:
                    chat = self.ctx_handler.ctx_chat
                    last_ts = chat[-1].get("processing_timestamp", 0) if chat else 0
                except Exception:
                    last_ts = 0
                if last_ts > flap_at_ns:
                    _agent_log(
                        f"[AUTO-RESUME] real interrupt — step() will handle it"
                    )
                    continue
                if not self._pending_response or self._resume_in_flight:
                    _agent_log(
                        f"[AUTO-RESUME] nothing pending or resume already running"
                    )
                    continue
                _agent_log("[AGENT] Auto-resume after silent RMS flap")
                self._replay_unspoken()
            except Exception as _e:
                _agent_log(f"[AGENT] auto-resume watcher error: {_e}")
                time.sleep(1.0)

    def _build_system_msg(self, content: str):
        """Construct a system message in the format expected by the active LLM backend."""
        if self._use_local_llm:
            return {"role": "system", "content": content}
        from langchain_core.messages import SystemMessage
        return SystemMessage(content=content)

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
        if not text or not isinstance(text, str):
            return
        text = self._EMOTION_PAREN_RE.sub('', text)
        text = self._EMOTION_STAR_RE.sub('', text)
        text = self._STAR_TAG_RE.sub('', text)
        text = self._strip_markdown_for_tts(text)
        text = self._stretch_ellipsis(text).strip()
        if not text:
            return
        if split_sentences:
            sentences = re.split(r'(?<=[.!?])\s+(?=[А-ЯA-ZЁ0-9«"\'(])', text)
            for s in sentences:
                s = s.strip()
                if s:
                    self.ctx_swarm["tts_queue"].append(
                        {"text": s, "emotion": "neutral"}
                    )
        else:
            self.ctx_swarm["tts_queue"].append(
                {"text": text, "emotion": "neutral"}
            )

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

    # --- Tutor-only voice commands -----------------------------------------
    # Verbs that count as "load this course". 'добавь' is the only one that
    # uses append-mode in reload_from_path; the rest replace.
    _LOAD_VERBS = r"загрузи|подгрузи|добавь|открой|возьми|включи|начни"
    _SUBJECT_NOUNS = r"предмет|курс|тему|дисциплину|модуль"
    # Long form: "загрузи предмет X из папки Y" — explicit path
    _LOAD_SUBJECT_RE = re.compile(
        rf"(?P<verb>{_LOAD_VERBS})\s+"
        rf"(?:{_SUBJECT_NOUNS})\s+"
        r"(?P<name>.+?)\s+"
        r"из\s+(?:папки\s+)?(?P<path>.+?)\s*$",
        re.IGNORECASE,
    )
    # Short form: "загрузи курс X" — resolved via course directory scan
    _LOAD_SUBJECT_SHORT_RE = re.compile(
        rf"(?P<verb>{_LOAD_VERBS})\s+"
        rf"(?:{_SUBJECT_NOUNS})\s+"
        r"(?P<name>.+?)\s*$",
        re.IGNORECASE,
    )
    # Bare form: "загрузи курс" — no name. Triggers a follow-up question
    # ("какой курс загрузить?") and parks the agent in awaiting-name mode.
    _LOAD_SUBJECT_BARE_RE = re.compile(
        rf"(?P<verb>{_LOAD_VERBS})\s+(?:{_SUBJECT_NOUNS})\s*[.!?,]?\s*$",
        re.IGNORECASE,
    )
    # Directories scanned for pre-packaged courses (relative to repo root).
    # Each subdir is a course package if it contains course_config.yml.
    _COURSE_SEARCH_DIRS = ("courses", "samples", "data/courses")

    # Concept-lookup triggers — short Q&A asking for a specific term. We
    # extract the term and tell the LLM to answer only about it, not the
    # adjacent concepts that share the same RAG chunk.
    _CONCEPT_LOOKUP_RE = re.compile(
        r"^(?:профессор[,\s]+|преподаватель[,\s]+|препод[,\s]+)?"
        r"(?:"
        r"что\s+(?:такое|значит|это(?:\s+за)?)"
        r"|что\s+за"
        r"|опиши(?:\s+(?:мне|кратко))?"
        r"|объясни(?:\s+(?:мне|кратко))?"
        r"|коротко\s+про"
        r"|что\s+это\s+за"
        r")\s+(?P<term>.+?)\s*[?.!]*\s*$",
        re.IGNORECASE,
    )

    def _extract_concept_term(self, msg: str) -> str:
        """Return the asked-about term if this looks like a short concept
        lookup question. Empty string otherwise (no inject in that case).

        Capped at 60 chars to avoid false-positives on long compound questions
        that happen to start with 'объясни ...'.
        """
        if not msg or len(msg) > 80:
            return ""
        m = self._CONCEPT_LOOKUP_RE.match(msg.strip())
        if not m:
            return ""
        term = m.group("term").strip().rstrip(".!?,")
        # Reject if the "term" itself is a long phrase — likely a real
        # explanation request, not a concept lookup.
        if len(term.split()) > 4:
            return ""
        return term

    _LIST_COURSES_RE = re.compile(
        r"(?:"
        # "какие [у тебя [есть]] курсы / какие курсы [у тебя/доступны/есть/загружены]"
        r"какие(?:\s+\w+){0,3}\s+курс\w*"
        # "покажи / перечисли / список [доступных] курсов"
        r"|(?:покажи|перечисли|список)\s+(?:доступн\w+\s+)?курс\w*"
        # "что [у тебя] есть / загружено"
        r"|что\s+(?:у\s+тебя\s+)?(?:есть|загружено)"
        # "что [ты] умеешь / можешь преподавать"
        r"|что\s+(?:ты\s+)?(?:умеешь|можешь\s+преподавать)"
        r")",
        re.IGNORECASE,
    )

    _PROFILE_QUERY_RE = re.compile(
        r"(?:покажи|расскажи|запроси|давай)\s+(?:мой\s+)?профиль|"
        r"мой\s+профиль|"
        r"что\s+ты\s+обо\s+мне\s+(?:знаешь|помнишь)|"
        r"какие\s+у\s+меня\s+(?:слабые|трудные)\s+места|"
        r"над\s+чем\s+(?:мне\s+)?поработать",
        re.IGNORECASE,
    )

    _TOPIC_LEVEL_LABELS = {
        1: "начинающий", 2: "базовый", 3: "средний", 4: "продвинутый", 5: "эксперт",
    }
    _WEAK_TOPIC_LEVEL_MAX = 2  # topic_level <= 2 → "слабое место"

    _SESSION_SUMMARY_RE = re.compile(
        r"(?:"
        r"давай(?:те)?\s+(?:резюмируем|подведём|подведем|итог|итожим)"
        r"|подведи\s+(?:итог|итоги)"
        r"|резюм(?:е|ируй)"
        r"|сделай\s+(?:итог|резюме|выводы)"
        r"|что\s+мы\s+(?:разобрали|изучили|прошли|обсудили)"
        r"|итог(?:и)?\s+(?:занят|сессии|урока)"
        r"|подытожь"
        r")",
        re.IGNORECASE,
    )

    def _handle_session_summary(self, msg: str) -> bool:
        """Voice command 'давай резюмируем' → final wrap-up across the dialogue.

        Pulls the last N student/assistant turns from ctx_chat, asks the LLM
        for a short 3-4 sentence summary covering what was discussed, then
        speaks it and saves to history. Works only in the free-dialogue path
        (lecture FSM has its own farewell flow).
        """
        if not msg:
            return False
        if not self._SESSION_SUMMARY_RE.search(msg.strip()):
            return False
        _agent_log(f"[TUTOR] Session summary requested: '{msg[:60]}'")

        # Gather the last ~30 turns as plain "роль: текст" lines for the LLM
        recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=30) or []
        if len(recent) < 4:
            self._send_to_tts(
                "Пока мало успели обсудить — нечего резюмировать. Спрашивай дальше."
            )
            return True

        student_name = self._current_student or "студент"
        lines = []
        for ev in recent:
            role = "Преподаватель" if ev.get("self") else student_name
            text = (ev.get("msg") or "").strip()
            if text:
                lines.append(f"{role}: {text[:300]}")
        transcript = "\n".join(lines[-30:])

        prompt = (
            "Подведи итог занятия. Ровно 3-4 коротких предложения. Опирайся "
            "только на текст диалога ниже.\n\n"
            "Структура:\n"
            "1) Что разобрали — перечисли темы кратко.\n"
            "2) Где студент уверенно отвечал — одна фраза.\n"
            "3) Что стоит повторить — одна фраза.\n"
            "Не вставляй маркеры, говори текстом для голоса. Не повторяй сам диалог.\n\n"
            f"=== Диалог ===\n{transcript}\n=== Конец ===\n"
        )

        try:
            # Reuse the same non-streaming LM Studio path used by quiz / meta —
            # fast (~1-2 s on Gemma 4 E4B), no TRIGGER_START dance needed.
            import requests
            _lm_base = os.getenv("LM_STUDIO_API_BASE", "http://127.0.0.1:22227/v1").rstrip("/")
            _lm_model = os.getenv("LM_STUDIO_MODEL_NAME", "google/gemma-4-e4b-it")
            r = requests.post(
                f"{_lm_base}/chat/completions",
                json={
                    "model": _lm_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 350,
                    "temperature": 0.3,
                    "stream": False,
                    "reasoning_effort": "none",
                },
                timeout=30,
            )
            r.raise_for_status()
            summary = r.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            _agent_log(f"[TUTOR] Summary LLM call failed: {e}")
            traceback.print_exc()
            summary = ("Сегодня прошлись по нескольким темам по курсу. "
                       "Хочешь — продолжим разбирать конкретное, или закончим занятие.")

        # Drop leaked TRIGGER_START / reasoning prefixes just in case
        for marker in ("TRIGGER_START",):
            if marker in summary:
                summary = summary.split(marker, 1)[1].strip()

        self._send_to_tts(summary, split_sentences=True)
        self._save_to_history(summary)
        return True

    def _handle_profile_query(self, msg: str) -> bool:
        """Voice command 'покажи профиль' → speak public weak spots + recommendations.

        Does NOT go through the LLM — pulls SQLite directly and pushes phrase to TTS.
        Public scope only: known_issues + weak topic_levels. Never speaks
        communication_style / personality_notes / background / mood.
        """
        if not msg:
            return False
        if not self._PROFILE_QUERY_RE.search(msg.strip()):
            return False
        _agent_log(f"[TUTOR] Profile query: '{msg[:60]}'")

        if not self._profile_mgr or not self._current_student:
            self._send_to_tts(
                "Пока я не знаком с тобой. Назови имя, тогда смогу вести профиль."
            )
            return True

        try:
            student = self._profile_mgr.get_or_create_student(self._current_student)
        except Exception as e:
            _agent_log(f"[TUTOR] Profile read failed: {e}")
            traceback.print_exc()
            self._send_to_tts("Не получилось прочитать профиль, попробуй позже.")
            return True

        if student.get("total_interactions", 0) < 2:
            self._send_to_tts(
                "Пока недостаточно данных. Давай поработаем над материалом — позже покажу."
            )
            return True

        import json as _json
        issues_raw = student.get("known_issues") or "[]"
        try:
            issues = _json.loads(issues_raw) if isinstance(issues_raw, str) else list(issues_raw)
        except Exception:
            issues = []
        topic_levels_raw = student.get("topic_levels") or "{}"
        try:
            topic_levels = _json.loads(topic_levels_raw) if isinstance(topic_levels_raw, str) else {}
        except Exception:
            topic_levels = {}

        weak_topics = [t for t, lvl in topic_levels.items()
                       if isinstance(lvl, int) and lvl <= self._WEAK_TOPIC_LEVEL_MAX]

        parts = []
        if issues:
            parts.append("По нашим занятиям вижу следующие трудности: " + ", ".join(issues[:3]) + ".")
        if weak_topics:
            parts.append("Слабее всего темы: " + ", ".join(weak_topics[:3]) + ".")
            parts.append("Рекомендую вернуться и проработать " + weak_topics[0] + " подробнее.")
        elif issues:
            parts.append("Рекомендую повторить разделы где были трудности.")

        if not parts:
            phrase = "Слабых мест пока не вижу. Идём дальше — спрашивай или выбирай новую тему."
        else:
            phrase = " ".join(parts)

        # POST-MVP: full profile (tech_level, interests, total_interactions).
        # Gated behind env flag — disabled by default.
        if os.getenv("TUTOR_FULL_PROFILE") == "1":
            tech = student.get("tech_level", 3)
            tech_label = self._TOPIC_LEVEL_LABELS.get(tech, "средний")
            total = student.get("total_interactions", 0)
            try:
                interests = _json.loads(student.get("topics_of_interest") or "[]")
            except Exception:
                interests = []
            phrase += f" Общий уровень: {tech_label}. Занятий: {total}."
            if interests:
                phrase += " Интересы: " + ", ".join(interests[:3]) + "."

        self._send_to_tts(phrase)
        self._save_to_history(phrase)
        return True

    def _scan_known_courses(self) -> dict:
        """Scan _COURSE_SEARCH_DIRS for course packages.

        Returns {short_name_lower: abs_path}. A package is any subdir with
        course_config.yml; key is short_name (or name) from that YAML.
        """
        try:
            import yaml as _yaml  # type: ignore
        except ImportError:
            _agent_log("[TUTOR] PyYAML missing; cannot scan course directories")
            return {}
        found = {}
        for base in self._COURSE_SEARCH_DIRS:
            if not os.path.isdir(base):
                continue
            for entry in os.listdir(base):
                pkg_path = os.path.join(base, entry)
                cfg_path = os.path.join(pkg_path, "course_config.yml")
                if not os.path.isfile(cfg_path):
                    continue
                try:
                    with open(cfg_path, "r", encoding="utf-8") as f:
                        cfg = _yaml.safe_load(f) or {}
                except Exception as e:
                    _agent_log(f"[TUTOR] Failed to read {cfg_path}: {e}")
                    continue
                course = cfg.get("course") or cfg
                short = (course.get("short_name") or course.get("name") or entry).strip().lower()
                if short not in found:
                    found[short] = os.path.abspath(pkg_path)
                # Also index by directory name for fallback
                dirkey = entry.strip().lower()
                if dirkey not in found:
                    found[dirkey] = os.path.abspath(pkg_path)
        return found

    def _resolve_course_by_name(self, name: str) -> str | None:
        """Find a known course matching the spoken name (case-insensitive).

        Tries exact -> substring -> fuzzy (difflib) match in that order, so
        STT distortions like "вашим матом" / "вышмату" still find "вышмат".
        """
        known = self._scan_known_courses()
        if not known:
            return None
        target = name.strip().lower().rstrip(".!?,")
        # 1. Exact
        if target in known:
            return known[target]
        # 2. Substring either way ("вышмат" ↔ "вышмат-2026")
        for key, path in known.items():
            if target in key or key in target:
                return path
        # 3. Fuzzy — catches STT mishears. cutoff 0.55 is lenient enough for
        #    "вашим матом" -> "вышмат" but still rejects unrelated phrases.
        import difflib
        close = difflib.get_close_matches(target, list(known.keys()), n=1, cutoff=0.55)
        if close:
            _agent_log(f"[TUTOR] fuzzy course match: '{target}' -> '{close[0]}'")
            return known[close[0]]
        # 4. Word-by-word fuzzy: STT may pad the name with garbage
        #    ("займемся вашим матом" -> tokenize, try each word).
        for token in re.findall(r"\w+", target):
            if len(token) < 4:
                continue
            close = difflib.get_close_matches(token, list(known.keys()), n=1, cutoff=0.7)
            if close:
                _agent_log(f"[TUTOR] fuzzy token match: '{token}' -> '{close[0]}'")
                return known[close[0]]
        return None

    def _handle_tutor_load_subject(self, msg: str) -> bool:
        """Detect load-course commands and reload RAG. Returns True if handled.

        Three forms:
          1. "загрузи предмет X из папки Y" — explicit path
          2. "загрузи курс X" — resolved by scanning courses/, samples/, data/courses/
          3. "загрузи курс" (no name) — speaks "какой курс?" and parks the
             agent in awaiting-name mode; the next utterance is treated as
             the course name.
        """
        if not msg:
            return False
        stripped = msg.strip()

        # Awaiting-name mode: previous turn was a bare "загрузи курс". Treat
        # this whole utterance as a name and try to resolve. If it does NOT
        # look like a valid course name (no match), drop out of awaiting-mode
        # so the student isn't trapped — let the message fall through to the
        # normal pipeline.
        if self._awaiting_course_name:
            self._awaiting_course_name = False
            cleaned = stripped.rstrip(".!?,")
            resolved = self._resolve_course_by_name(cleaned)
            if resolved is None:
                known = self._scan_known_courses()
                if known:
                    options = ", ".join(sorted(set(known.keys()))[:5])
                    self._send_to_tts(
                        f"Не нашёл такой курс. Доступны: {options}."
                    )
                else:
                    self._send_to_tts(
                        "У меня пока нет ни одного курса. Положи папку курса в courses или samples."
                    )
                _agent_log(f"[TUTOR] Awaiting-name: '{cleaned}' not resolved")
                return True
            name = cleaned
            path = resolved
            verb = "загрузи"
            _agent_log(f"[TUTOR] Awaiting-name resolved: '{name}' → '{path}'")
            # Fall through to actual load
            return self._do_load_subject(name, path, verb)

        # Try long form first (explicit path takes precedence)
        m = self._LOAD_SUBJECT_RE.search(stripped)
        if m:
            name = m.group("name").strip().rstrip(".!?,")
            path = m.group("path").strip().rstrip(".!?,")
            verb = m.group("verb").lower()
            return self._do_load_subject(name, path, verb)

        # Bare form: "загрузи курс" without a name. Park, ask back.
        if self._LOAD_SUBJECT_BARE_RE.search(stripped):
            known = self._scan_known_courses()
            if not known:
                self._send_to_tts(
                    "У меня пока нет ни одного курса. Положи папку курса в courses или samples."
                )
                _agent_log("[TUTOR] Bare load: no known courses")
                return True
            options = ", ".join(sorted(set(known.keys()))[:5])
            self._send_to_tts(
                f"Какой курс загрузить? Доступны: {options}."
            )
            self._awaiting_course_name = True
            _agent_log("[TUTOR] Bare load: asking for course name")
            return True

        # Short form: "загрузи курс X" — resolve via known-courses scan
        m = self._LOAD_SUBJECT_SHORT_RE.search(stripped)
        if not m:
            return False
        name = m.group("name").strip().rstrip(".!?,")
        verb = m.group("verb").lower()
        resolved = self._resolve_course_by_name(name)
        if resolved is None:
            known = self._scan_known_courses()
            if known:
                options = ", ".join(sorted(set(known.keys()))[:5])
                self._send_to_tts(
                    f"Не нашёл курс {name}. Доступны: {options}."
                )
            else:
                self._send_to_tts(
                    f"Не нашёл курс {name}. Положи папку курса в courses или samples."
                )
            _agent_log(f"[TUTOR] Short load: name='{name}' not resolved")
            return True
        path = resolved
        _agent_log(f"[TUTOR] Short load resolved: name='{name}' → '{path}'")
        return self._do_load_subject(name, path, verb)

    def _do_load_subject(self, name: str, path: str, verb: str) -> bool:
        mode = "append" if verb == "добавь" else "replace"
        _agent_log(f"[TUTOR] Load subject: name='{name}', path='{path}', mode='{mode}'")
        self._send_to_tts(f"Загружаю предмет {name}, минуту.")
        try:
            n = self.rag_model.reload_from_path(name, path, mode=mode)
        except FileNotFoundError:
            self._send_to_tts(f"Папка не найдена: {path}.")
            return True
        except ValueError as e:
            self._send_to_tts(f"В папке нет файлов для загрузки.")
            _agent_log(f"[TUTOR] reload_from_path ValueError: {e}")
            return True
        except Exception as e:
            err = str(e)[:120]
            self._send_to_tts(f"Не получилось загрузить: {err}.")
            _agent_log(f"[TUTOR] reload_from_path failed: {e}")
            traceback.print_exc()
            return True
        self._send_to_tts(f"Готово, загружено {n} фрагментов. Могу преподавать предмет {name}.")
        return True

    def _handle_list_courses(self, msg: str) -> bool:
        """Voice command 'какие курсы / список курсов / что ты умеешь'.

        Reads the names of all known course packages aloud — bypasses the
        LLM so the answer is always factual, not hallucinated. Returns
        True iff the message matched.
        """
        if not msg:
            return False
        if not self._LIST_COURSES_RE.search(msg.strip()):
            return False
        known = self._scan_known_courses()
        if not known:
            self._send_to_tts(
                "У меня пока нет ни одного курса. "
                "Положи папку курса в courses или samples."
            )
            _agent_log("[TUTOR] List courses: empty")
            return True
        names = sorted(set(known.keys()))
        listing = ", ".join(names[:8])
        more = "" if len(names) <= 8 else f" и ещё {len(names) - 8}"
        self._send_to_tts(f"Доступные курсы: {listing}{more}.")
        _agent_log(f"[TUTOR] List courses: {names}")
        return True


    def step(self):
        """Run a single iteration: wait for trigger → stream LLM → sentence TTS.

        Architecture v2: no classification step, direct streaming from Mistral.
        Meta-analysis runs AFTER response in background thread.
        """
        try:
            if not self.initialized:
                print("[DEBUG CORE AGENT] NOT INITIALIZED")
                return

            self._last_heartbeat = time.time()
            _agent_log(f"[AGENT-DEBUG] step() called. interrupted={self._interrupted}, "
                  f"ctx_chat_len={len(self.ctx_handler.ctx_chat)}, "
                  f"meta_running={getattr(self, '_meta_running', False)}, "
                  f"tts_queue_len={len(self.ctx_swarm['tts_queue'])}")

            import random

            # Break reminder (feature 4): once after 60 min
            if not self._break_suggested and (time.time() - self._session_start_time) > BREAK_REMINDER_THRESHOLD_S:
                self._send_to_tts("Мы общаемся уже больше часа. Может, сделаем небольшой перерыв минут на пять?")
                self._break_suggested = True

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
                meta_instruction=self._last_meta_instruction,
                student_profile=self._last_student_profile,
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

            # 2.5a1 Explicit "продолжай" — replay the unspoken tail of the
            # previous response from TTS without an LLM round-trip. Falls
            # through to LLM only if there's nothing pending or the phrase
            # is embedded in a longer sentence (caller meant something else).
            if last_student_msg and self._is_resume_phrase(last_student_msg) \
                    and self._pending_response and not self._resume_in_flight:
                _agent_log(
                    f"[AGENT] Explicit 'продолжай' — replaying pending tail"
                )
                self._replay_unspoken()
                return

            # 2.5a2 Pause-on-request: while paused, only explicit resume phrases
            # bring the tutor back. Everything else (chat noise, side comments,
            # off-topic) is dropped so the student can actually rest.
            if self._paused_until is not None:
                _msg_lower_p = last_student_msg.lower()
                if re.search(r"продолж|вернулся|вернулась|я\s+тут|давай\s+дальше|поехали|пошл[иёе]м",
                             _msg_lower_p):
                    _agent_log(f"[AGENT] Resume from pause after "
                               f"{int(time.time() - (self._paused_until - 5*60))}s: "
                               f"'{last_student_msg[:60]}'")
                    self._paused_until = None
                    self.ctx_swarm["tts_queue"].append(
                        {"text": "Продолжаем. На чём мы остановились?", "emotion": "neutral"}
                    )
                    self._save_to_history("Продолжаем.")
                    return
                _agent_log(f"[AGENT] Paused — ignoring input: '{last_student_msg[:60]}'")
                return

            # 2.5b Stop commands: don't generate, just acknowledge and wait
            _stop_words = ["стоп", "подождите", "помолчите", "секунду", "погодите",
                           "хватит", "тихо", "давай паузу", "подожди минуту"]
            _msg_lower = last_student_msg.lower()
            if any(w in _msg_lower for w in _stop_words) and len(last_student_msg) < 50:
                print(f"[AGENT] Stop command detected: '{last_student_msg}'")
                self.ctx_swarm["tts_queue"].append({"text": "Хорошо, слушаю.", "emotion": "neutral"})
                self._save_to_history("Хорошо, слушаю.")
                return

            # 2.5b2 Pause-for-N-minutes: full pause, only resume by explicit phrase
            _pause_m = re.search(
                r"(?:дава[йт]+\s+(?:сдела[ею]м\s+)?(?:паузу|перерыв)|сдела[ею]м\s+(?:паузу|перерыв)|перерыв)"
                r"(?:\s+на\s+(?P<n1>\d+)\s*мин)?|"
                r"(?P<n2>\d+)\s*минут\w*\s+отдых",
                _msg_lower,
            )
            if _pause_m and len(last_student_msg) < 100:
                _n_raw = _pause_m.group("n1") or _pause_m.group("n2")
                _mins = int(_n_raw) if _n_raw else 5
                _mins = max(1, min(60, _mins))
                _agent_log(f"[AGENT] Pause requested for {_mins} min")
                self._paused_until = time.time() + _mins * 60
                tts_q = self.ctx_swarm["tts_queue"]
                if len(tts_q) > 0:
                    tts_q[:] = []
                tts_q.append({
                    "text": (f"Хорошо, делаем паузу на {_mins} минут. "
                             f"Скажи 'продолжим', когда вернёшься."),
                    "emotion": "neutral",
                })
                self._save_to_history(f"Хорошо, делаем паузу на {_mins} минут.")
                return

            # 2.5b3 Manner switch commands — change explanation style for future turns
            if len(last_student_msg) < 120:
                if re.search(r"расскажи\s+проще|поп?рощ[еауы]|короче|простыми\s+словами|объясни\s+проще",
                             _msg_lower):
                    if self._manner != "simpler":
                        self._manner = "simpler"
                        self.ctx_swarm["states"]["personality"] = "professor_simpler"
                        self.ctx_swarm["tts_queue"].append(
                            {"text": "Хорошо, объясню проще.", "emotion": "neutral"}
                        )
                        self._save_to_history("Хорошо, объясню проще.")
                        return
                if re.search(r"(?:расскажи|объясни)\s+подробне[ей]|подробне[ей]\s+(?:расскажи|объясни)|"
                             r"строже|больше\s+деталей|академически|развёрнуто|развернуто",
                             _msg_lower):
                    if self._manner != "detailed":
                        self._manner = "detailed"
                        self.ctx_swarm["states"]["personality"] = "professor_detailed"
                        self.ctx_swarm["tts_queue"].append(
                            {"text": "Хорошо, развёрнуто.", "emotion": "neutral"}
                        )
                        self._save_to_history("Хорошо, развёрнуто.")
                        return
                if re.search(r"как\s+обычно|нормально\s+говори|нейтрально", _msg_lower):
                    if self._manner != "neutral":
                        self._manner = "neutral"
                        self.ctx_swarm["states"]["personality"] = "professor_neutral"
                        self.ctx_swarm["tts_queue"].append(
                            {"text": "Хорошо, как обычно.", "emotion": "neutral"}
                        )
                        self._save_to_history("Хорошо, как обычно.")
                        return

            # 2.5c Tutor: voice command "загрузи предмет X из папки Y"
            if self._handle_tutor_load_subject(last_student_msg):
                return

            # 2.5c1 Tutor: "какие курсы / список курсов / что ты умеешь"
            if self._handle_list_courses(last_student_msg):
                return

            # 2.5e Tutor: voice command "покажи мой профиль" — public weak spots only
            if self._handle_profile_query(last_student_msg):
                return

            # 2.5f Tutor: voice command "давай резюмируем / подведи итог" — final wrap-up
            if self._handle_session_summary(last_student_msg):
                return

            # 3. Inject cached student profile (from last meta-analysis)
            if self._current_student and self._profile_mgr:
                profile_text = self._profile_mgr.get_profile_for_prompt(self._current_student)
                if profile_text:
                    messages.insert(-1, self._build_system_msg(f"Профиль студента: {profile_text}"))

            # 3.6 Narrow-focus inject for concept-lookup questions.
            # Course material chunks are dense — "summary" sits in the same
            # paragraph as "БД", "SaveUserInfoTool", "prompt constructor". On
            # a question like "что такое summary" the LLM sees that whole
            # paragraph and unrolls every concept in it. Tell it explicitly to
            # answer ONLY about the asked term.
            _focus_term = self._extract_concept_term(last_student_msg)
            if _focus_term:
                _narrow = (
                    f"Студент задал короткий вопрос про КОНКРЕТНЫЙ термин: «{_focus_term}». "
                    f"Ответь 2-4 короткими предложениями ТОЛЬКО про этот термин. "
                    f"НЕ разворачивай смежные концепции из контекста (БД, prompt constructor, "
                    f"инструменты, etc.), даже если они в нём упомянуты рядом. "
                    f"Если студенту нужно — он спросит про них отдельно."
                )
                messages.insert(-1, self._build_system_msg(_narrow))
                _agent_log(f"[FOCUS] narrow-focus inject for term={_focus_term!r}")

            self.ctx_swarm["fx_queue"].put("thinking")

            # 4. STREAM response — sentences go to TTS as they arrive
            # Short messages get fewer tokens to prevent hallucination dumps
            _max_tokens = (RESPONSE_MAX_TOKENS_SHORT if len(last_student_msg) < 25
                           else RESPONSE_MAX_TOKENS_LONG)
            _chat_len_before = len(self.ctx_handler.ctx_chat)
            interrupted = False

            t0 = time.perf_counter()
            messages_dicts = messages if self._use_local_llm else self._to_dicts(messages)
            _llm_label = (
                "LM Studio (local)" if self._use_local_llm
                else os.getenv("CORE_LLM_MODEL_NAME", "remote API")
            )
            _agent_log(
                f"[AGENT] Starting LLM stream via {_llm_label} "
                f"(max_tokens={_max_tokens}, msg='{last_student_msg[:50]}')"
            )
            spoken_sentences = []   # sentences actually sent to TTS
            sentence_count = 0

            for sentence in stream_response_sentences(
                messages_dicts,
                temperature=random.uniform(RESPONSE_TEMPERATURE_LOW, RESPONSE_TEMPERATURE_HIGH),
                max_tokens=_max_tokens,
            ):
                # Interrupt ONLY on a confirmed new student message in ctx_chat.
                # RMS-based student_speaking flag used to fire here too — it
                # produced false-positives on coughs / TTS bleed / chair noise
                # and hung step() in a Manager-IPC busy-wait. TTS playback is
                # still paused immediately by the mic_stt_handler 'interrupt'
                # sentinel; only the LLM stream keeps running until STT
                # actually publishes a transcribed event.
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

                # Keep _pending_response live after every yielded sentence so
                # auto-resume / "продолжай" can replay even if step() hangs on
                # a later Manager-IPC call (save_to_history etc.).
                self._pending_response = {
                    "sentences": list(spoken_sentences),
                    "started_at": t0,
                }
                self._last_heartbeat = time.time()

                elapsed = (time.perf_counter() - t0) * 1000
                print(f"[AGENT] sentence #{sentence_count} ({elapsed:.0f}ms): "
                      f"'{sentence[:60]}'")

            elapsed = (time.perf_counter() - t0) * 1000
            spoken_text = " ".join(spoken_sentences).strip()
            self._last_heartbeat = time.time()
            _agent_log(
                f"[AGENT-STAGE] for-loop exited: sentences={sentence_count}, "
                f"interrupted={interrupted}, spoken_chars={len(spoken_text)}"
            )

            # Save history + pending_response uniformly. Interrupt is now
            # always "real" (we only break on a new ctx_chat message), so the
            # spoken_sentences either are the full response or the tail we
            # got out before the student preempted.
            if interrupted:
                print(f"[AGENT] Interrupted after {sentence_count} sentences, "
                      f"{elapsed:.0f}ms, spoken: '{spoken_text[:80]}'")
            else:
                print(f"[AGENT] Streaming done: {sentence_count} sentences, "
                      f"{elapsed:.0f}ms, {len(spoken_text)} chars")
            if spoken_text:
                # Async save: ctx_handler.add_message goes through Manager IPC
                # which under Windows multiprocessing has been known to block
                # for 10-30s. Doing it in a daemon thread keeps step() moving.
                threading.Thread(
                    target=self._save_to_history,
                    args=(spoken_text,),
                    daemon=True,
                    name="SaveHistory",
                ).start()
                self._pending_response = {
                    "sentences": list(spoken_sentences),
                    "started_at": t0,
                }
            self._last_heartbeat = time.time()
            _agent_log("[AGENT-STAGE] history saved, entering retry-check")
            # Retry on empty response (LLM error / timeout)
            if not spoken_text and not interrupted:
                self._retry_count = getattr(self, '_retry_count', 0) + 1
                if self._retry_count <= 3:
                    _agent_log(f"[AGENT] Empty response from LLM — retry {self._retry_count}/3")
                    time.sleep(AGENT_ERROR_BACKOFF_S)
                    self._interrupted = True
                    return
                else:
                    self._retry_count = 0
                    self._send_to_tts(
                        "Извини, сервер не отвечает. Попробуй спросить ещё раз через минуту."
                    )
                    return

            self._retry_count = 0  # reset on successful response

            # 6. Meta-analysis — run after every confident student utterance,
            # including interrupting ones. The gate that used to require
            # `not interrupted` swallowed all style cues delivered as barge-in
            # ("отвечай короче, но так же подробно"). STT-confidence threshold
            # already filtered out noise upstream (see mic_stt_handler.py),
            # so meta is safe to call here.
            _stt_conf = self.ctx_swarm["env"].get("last_stt_confidence", 1.0)
            _agent_log(
                f"[AGENT-STAGE] meta gate: stt_conf={_stt_conf}, "
                f"meta_running={getattr(self, '_meta_running', False)}"
            )
            if (
                _stt_conf is None or _stt_conf >= 0.6
            ) and not getattr(self, '_meta_running', False):
                _spoken = spoken_text
                _student_msg = last_student_msg
                self._meta_running = True
                def _post_response():
                    try:
                        student_profile_text, meta_instruction, meta_result = \
                            self._run_meta_analysis()
                        self._last_meta_result = meta_result
                        self._last_meta_instruction = meta_instruction
                        self._last_student_profile = student_profile_text
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
                # Pick the most recent meta-analysis emotion if available
                # (set by the previous turn's background _post_response thread).
                _last_meta = getattr(self, "_last_meta_result", None) or {}
                _emotion = _last_meta.get("mood", "neutral") if isinstance(_last_meta, dict) else "neutral"
                # rag_sources: top-2 retrieval results from the just-built prompt.
                # rag.explain() stamps these on the model as a side effect.
                _rag_sources = []
                try:
                    raw_sources = getattr(self.rag_model, "last_sources", None) or []
                    for s in raw_sources:
                        # Compact string the SQLite column can hold without bloat.
                        _rag_sources.append(
                            f"{s.get('subject', '') or s.get('kind', '')}@{s.get('score', 0):.3f}: "
                            f"{s.get('preview', '')[:80]}"
                        )
                except Exception:
                    pass
                self.ctx_swarm["env"]["last_interaction"] = {
                    "query": last_student_msg,
                    "response": spoken_text,
                    "response_time_ms": int(elapsed),
                    "rag_sources": _rag_sources,
                    "emotion": _emotion,
                }
            self._last_heartbeat = time.time()
            _agent_log("[AGENT-STAGE] step() returning normally")

        except Exception as e:
            _agent_log(f"[AGENT] ERROR in step(): {e}")
            traceback.print_exc()
            time.sleep(10)

    def _play_startup_greeting(self):
        """Speak a startup greeting once TTS/STT are up.

        Asks the student to introduce themselves only on first launch
        (empty profile DB); on subsequent launches just greets and stays
        ready. Pre-greeting STT noise is dropped so it can't latch as a
        student name.
        """
        has_profiles = False
        try:
            if self._profile_mgr:
                has_profiles = self._profile_mgr.has_any_student()
        except Exception as e:
            _agent_log(f"[GREETING] profile check failed: {e}")

        if has_profiles:
            text = (
                "Здравствуй, я ИИ-профессор. Готов помочь тебе с учёбой. "
                "Скажи, какой курс хочешь изучать."
            )
        else:
            text = (
                "Здравствуй, я ИИ-профессор, готов помочь тебе с учёбой. "
                "Пожалуйста, представься, назови своё имя."
            )

        _agent_log(f"[GREETING] has_profiles={has_profiles}, speaking greeting")
        self._send_to_tts(text)

        # Wait until the TTS queue drains so anything the student says
        # after the greeting starts a clean turn.
        deadline = time.time() + 60
        tts_queue = self.ctx_swarm.get("tts_queue")
        while time.time() < deadline:
            try:
                if len(tts_queue) == 0:
                    time.sleep(0.6)  # grace for final playback latency
                    if len(tts_queue) == 0:
                        break
            except Exception:
                break
            time.sleep(0.2)

        # Drop any STT-captured words that landed BEFORE the greeting finished —
        # they should not be parsed as the student's name by extract_student_info.
        try:
            with self.ctx_swarm["ctx_chat_lock"]:
                del self.ctx_swarm["ctx_chat"][:]
            _agent_log("[GREETING] pre-greeting ctx_chat flushed")
        except Exception as e:
            _agent_log(f"[GREETING] ctx_chat flush failed: {e}")

    # Watchdog uses a heartbeat — step() pings _last_heartbeat at each stage,
    # watchdog fires when stage-to-stage silence exceeds the deadline. This
    # is forgiving toward long generations (we ping inside the for-loop too)
    # but catches Manager-IPC deadlocks within a few seconds.
    # 2026-05-19: queue-aware watchdog. Both timers are pinned while the
    # TTS queue is non-empty — a producing/playing agent is by definition
    # alive. Deadlines only count idle time, so long answers (300+ tokens
    # + 20s of playback) no longer trigger false-positive recovery, while
    # genuine Manager-IPC deadlocks (queue stuck non-decreasing) still fire.
    _STEP_HEARTBEAT_DEADLINE_S = 45
    _STEP_TIMEOUT_S = 120

    def _recover_from_hang(self) -> None:
        """Take whatever state survived the hang, tell the student, and let
        the next iteration of run() start fresh.

        Old step() thread keeps spinning in the background until the process
        exits — it's a daemon, so nothing dies hard. The main loop just
        leaves it behind and walks forward.
        """
        _agent_log("[WATCHDOG] step() hung — recovering, telling student to retry")
        try:
            tts_q = self.ctx_swarm["tts_queue"]
            tts_q[:] = []
            tts_q.append({
                "text": (
                    "Кажется моя основная модель подвисла. "
                    "Я всё перезапустил. Можешь повторить свой вопрос?"
                ),
                "emotion": "neutral",
            })
        except Exception as e:
            _agent_log(f"[WATCHDOG] TTS push failed: {e}")
        # Wipe chat history so the recovered turn starts with a clean prompt.
        # If we keep the stale history, the next step() may rebuild the same
        # toxic prompt that triggered the hang in the first place.
        try:
            with self.ctx_swarm["ctx_chat_lock"]:
                del self.ctx_swarm["ctx_chat"][:]
        except Exception as e:
            _agent_log(f"[WATCHDOG] ctx_chat wipe failed: {e}")
        # Reset agent-side state so the next step() doesn't replay or
        # auto-resume into the abandoned response.
        self._pending_response = None
        self._resume_in_flight = False
        self._meta_running = False
        self._interrupted = False
        self._last_meta_instruction = ""
        self._last_student_profile = ""
        try:
            self.ctx_swarm["voice"]["student_speaking"] = False
        except Exception:
            pass

    def run(self):
        """Main agent loop with heartbeat watchdog.

        Each step() runs in its own worker thread and pings _last_heartbeat
        at the start and after every long-running stage. If the heartbeat
        goes silent for longer than _STEP_HEARTBEAT_DEADLINE_S — even while
        the worker thread is still technically alive — we recover and move
        on. Old worker stays as a daemon.
        """
        _agent_log("[AGENT] === Agent run() started ===")
        self.running = True
        self.ctx_swarm["fx_queue"].put("starting")
        self._play_startup_greeting()
        while self.ctx_swarm["env"]["actived"] and self.running:
            self._last_heartbeat = time.time()
            t = threading.Thread(target=self.step, daemon=True, name="AgentStep")
            t.start()
            _step_start = time.time()
            hung = False
            while t.is_alive():
                time.sleep(0.5)
                now = time.time()
                # Queue-aware: while there is anything in the TTS queue the
                # agent is by definition producing or playing — pin both
                # timers so they only count truly idle time.
                try:
                    if len(self.ctx_swarm["tts_queue"]) > 0:
                        self._last_heartbeat = now
                        _step_start = now
                        continue
                except Exception:
                    pass
                if now - self._last_heartbeat > self._STEP_HEARTBEAT_DEADLINE_S:
                    _agent_log(
                        f"[WATCHDOG] heartbeat silence "
                        f"{now - self._last_heartbeat:.1f}s (queue empty) "
                        f"— declaring hang"
                    )
                    hung = True
                    break
                if now - _step_start > self._STEP_TIMEOUT_S:
                    _agent_log(
                        f"[WATCHDOG] absolute step timeout "
                        f"{now - _step_start:.1f}s (queue empty) "
                        f"— declaring hang"
                    )
                    hung = True
                    break
            if hung:
                self._recover_from_hang()
                time.sleep(2.0)


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
