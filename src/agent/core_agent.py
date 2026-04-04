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
from agent.tools.tool_executor import execute_tools
from agent.tools.tools import execute_tool_query, get_tool_records, default_exec_callaback
from config_schema.general import get_name
from utils.debug import bcolors
from data_flow.ctx_handler import CtxHandler
from utils.debug import print_messages

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
            # Get recent messages for context
            recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=6)
            last_messages = [m.get("msg", "") for m in recent if m.get("msg")]
            current_msg = last_messages[-1] if last_messages else ""

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

            # Log interaction
            self._profile_mgr.log_interaction(
                self._current_student, student_msg, agent_response,
                meta_analysis=str(meta_result), emotion=meta_result.get("mood", "neutral"),
            )
        except Exception as e:
            print(f"[META] Profile update error: {e}")

    def step(self):
        """Run a single iteration of the agent with streaming TTS."""
        try:
            if not self.initialized:
                print("[DEBUG CORE AGENT] NOT INITIALIZED")
                return

            # Meta-analysis: student profile + style instruction
            student_profile, meta_instruction, meta_result = self._run_meta_analysis()

            messages, response_starting = construct_prompt_messages(
                get_tool_records(),
                self.ctx_handler,
                rag_model=self.rag_model,
                output_format="langchain",
                tool_use_format="command",
                student_profile=student_profile,
                meta_instruction=meta_instruction,
            )
            if messages is None:
                return
            if self.ctx_swarm["env"].get("debug_print_prompt", False):
                print("Context messages:")
                print_messages(messages)
            smart_event_waiter = SmartEventWaiter(
                ctx_handler=self.ctx_handler, delay=1
            )
            self.ctx_swarm["fx_queue"].put("thinking")

            # --- Stream LLM, collect full response, then TTS as one piece ---
            # Piper TTS is fast (~0.3s), so no need to split by sentence.
            # Sending full text preserves natural prosody.
            full_response = ""
            interrupted = False
            _STREAM_TIMEOUT = 15.0

            import random
            _temperature = random.uniform(0.4, 0.75)
            stream_iter = iter(tools_config.llm_model.stream(messages, temperature=_temperature))
            timed_out = False
            while True:
                token_result = _next_with_timeout(stream_iter, _STREAM_TIMEOUT)
                if token_result is _STREAM_END:
                    break
                if token_result is _STREAM_TIMEOUT_END:
                    timed_out = True
                    break

                if smart_event_waiter.check():
                    interrupted = True
                    print("[CORE AGENT] Interrupted by new event during streaming")
                    break

                event = token_result
                token = event.content if not isinstance(event, str) else event
                if not token:
                    continue

                print(bcolors.OKCYAN + str(token) + bcolors.ENDC, flush=True, end="")
                full_response += token

            # Graceful truncation marker when timeout cuts mid-sentence
            if timed_out and full_response.strip() and not full_response.rstrip().endswith(('.', '!', '?', '…')):
                full_response += "..."

            smart_event_waiter.shutdown()
            print()

            # Send full response to TTS as single call
            if full_response.strip() and not interrupted:
                self._flush_sentence(full_response.strip(), is_last=True)

            # Save professor's response to ctx_chat so the model sees its own history
            # Strip emotion tags from saved text so LLM context stays clean
            if full_response.strip():
                from data_schema.chat_structures import EventBase
                from utils.time_helper import eztime
                clean_msg = self._EMOTION_PAREN_RE.sub('', full_response.strip())
                clean_msg = self._EMOTION_STAR_RE.sub('', clean_msg).strip()
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

                # Update student profile from meta-analysis
                recent = self.ctx_handler.get_ctx_chat(dict_format=True, limit=2)
                last_student_msg = ""
                for m in reversed(recent):
                    if not m.get("self"):
                        last_student_msg = m.get("msg", "")
                        break
                self._update_student_profile(meta_result, clean_msg, last_student_msg)

            print(f"Agent response:\n---\n{full_response}\n---\n")

        except Exception as e:
            print(f"Error running agent: {e}")
            traceback.print_exc()
            time.sleep(10)

    def run(self):
        """Main agent loop"""
        print("Starting simple chat agent")
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
