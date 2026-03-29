import time
import traceback
from typing import Optional

from agent.base_agent import BaseAgent
from agent.llm_clients.lc_clients import get_llm_chain
from agent.prompt_generation.prompt_constructor import (
    SmartEventWaiter,
    get_game_status,
    get_users_info,
)
from agent.tools import tools_config
from agent.tools.status_tools import get_tool_status
from config_schema.general import get_name
from data_flow.ctx_handler import CtxHandler
from data_flow.ctx_host import CtxHost
from data_schema.chat_structures import CtxEventBase, default_event_check
from data_schema.ctx_structures import CtxSwarmType
from data_schema.tool_structures import SpeakEmotion, SpeakEmotions, ToolBankType
from utils.debug import print_messages
from utils.format_helper import format_events_with_roles
from utils.prompt_helper import prompt_load


class ReactionAgent(BaseAgent):
    """
    Reaction agent
    VERY SIMPLE, FAST, LIGHTWEIGHT

    Should act IMMEDIATELY on chat event, interrupt with chat events
    NO Tool usage
    personality
    """

    def __init__(
        self,
        ctx_swarm: CtxSwarmType,
        ctx_handler: Optional[CtxHandler] = None,
        ctx_host: Optional[CtxHost] = None,
        tool_bank: Optional[ToolBankType] = None,
    ):
        """Initialize reaction agent with minimal setup"""
        super().__init__(ctx_swarm, ctx_handler)
        if ctx_handler is None:
            self.ctx_handler = CtxHandler(ctx_swarm)
        else:
            self.ctx_handler = ctx_handler

        # Lightweight LLM
        self.llm = get_llm_chain()
        self.self_name = get_name()

        # Initialize tools for minecraft chat
        if tool_bank is not None:
            self.tool_bank = tool_bank
        else:
            self.tool_bank = tools_config.init_tools_module(
                ctx_swarm, self.ctx_handler, new_llm=self.llm
            )
        if ctx_host is None:
            self.ctx_host = CtxHost(ctx_handler, tool_bank=self.tool_bank)
        else:
            self.ctx_host = ctx_host
        self.initialized = True

    def react(self, trigger_event: CtxEventBase) -> str:
        """
        React immediately to event with simple response

        Args:
            trigger_event: Event to react to

        Returns:
            Simple text response
        """
        if not self.initialized:
            return ""

        # Build minimal prompt
        personality = self.ctx_swarm["states"].get("personality", "professor_default")
        system_prompt = prompt_load("personalities", personality)

        # Get speak tool info
        speak_tool_desc = ""
        speak_status = ""
        if "speak" in self.tool_bank:
            # tool_info = self.tool_bank["speak"]
            emotions = list(SpeakEmotions.copy())
            speak_tool_desc = f"\n\nYour output format is just text to speak *emotion* with one of available emotions: {', '.join(emotions)}."

            # speak_tool_desc = f"\n\nYour output format is just text to speak: {tool_info.get('description', 'speak to chat')}"
            speak_status = get_tool_status("speak")
            if speak_status:
                speak_tool_desc += f"\nOutput system status: {speak_status}"

        # Get situation context from prompt_constructor
        # Get last few events with proper formatting
        # Format context for prompt
        messages_dicts, mentioned_users = format_events_with_roles(
            # TODO untested
            self.ctx_handler.get_ctx_chat(
                validate=True, dict_format=True, limit=50
            ),  # self.ctx_swarm["ctx_chat"]
            trigger_event_id=trigger_event.processing_timestamp,
            return_mentioned_users=True,
            tool_call_format="text",
        )

        # Get users info (players and chat users)
        users_info = get_users_info(
            ctx_swarm=self.ctx_swarm, chat_users=mentioned_users
        )

        # Get game status
        game_status = get_game_status()

        # Build situation context
        situation_context = f"""# Current Situation:
## Game Status:
{game_status}

## Nearby Users & Players:
{users_info}
"""

        reminder_message = {
            "role": "user",
            "content": "Response reminder: Respond BRIEFLY and EMOTIONALLY. 2 SHORT sentences maximum answer, or a quick reaction for some event. Do not forget *emotion*. Do not write anything else.",
        }
        # Build system message with situation context
        system_message = {
            "role": "system",
            "content": f"{system_prompt}{speak_tool_desc}",
        }

        # Build messages list with formatted events
        messages = [system_message]

        messages.append({"role": "user", "content": situation_context})

        # Add formatted events as conversation history
        if messages_dicts:
            messages.extend(messages_dicts)
        # Add reminder message
        # add a reminder text to the last message
        reminder_added = False
        try:
            if messages[-1]:
                if messages[-1]["role"] == "user" and isinstance(
                    messages[-1]["content"], str
                ):
                    messages[-1]["content"] += "\n\n" + reminder_message["content"]
                    reminder_added = True
        except Exception as e:
            print(f"[REACTION] Error adding reminder to last message: {e}")
        if not reminder_added:
            messages.append(reminder_message)
        print("FULL PROMPT")
        print_messages(messages)

        # Get quick response with streaming
        print("[Reaction agent] ", end="", flush=True)
        response_text = ""

        try:
            smart_event_waiter = SmartEventWaiter(ctx_handler=self.ctx_handler)
            self.ctx_swarm["fx_queue"].put("thinking")
            # Stream response like in tool executor
            for chunk in self.llm.stream(messages):
                chunk_text = chunk.content if hasattr(chunk, "content") else str(chunk)
                print(chunk_text, end="", flush=True)
                response_text += chunk_text
                if smart_event_waiter.check():
                    print(
                        "\nGeneration interrupted by event...",
                        str(smart_event_waiter.caught_event),
                    )
                    break
            print()  # New line after streaming
            smart_event_waiter.shutdown()
        except Exception as e:
            print(f"\n[REACTION] Error during streaming: {e}")
            # Fallback to non-streaming
            response = self.llm.invoke(messages)
            response_text = (
                response.content if hasattr(response, "content") else str(response)
            )
            print(f"[{self.self_name}] {response_text}")

        print(f"\n[REACTION] Generated response ({len(response_text)} chars)")

        # Send directly via minecraft chat tool
        if "speak" in self.tool_bank:
            try:
                self.tool_bank["speak"]["function"](response_text)
            except Exception as e:
                print(f"[REACTION] Error speaking: {e}")

        return response_text

    def step(self):
        """Run a single iteration: wait for event and react"""
        try:
            # Use same trigger waiting logic as CoreAgent
            print("[REACTION AGENT] Waiting for trigger...")
            check_start_time = time.time()

            def extended_wait_check(event: CtxEventBase) -> bool:
                """Check function dont trigger while we have messages to say or print"""

                def check_timeout():
                    return time.time() - check_start_time > 30.0

                # dont trigger while we have messages to say or print
                if (
                    len(self.ctx_handler.ctx_swarm["chat_queue"]) > 1
                    and not check_timeout()
                ):
                    return False
                if (
                    len(self.ctx_handler.ctx_swarm["tts_queue"]) > 1
                    and not check_timeout()
                ):
                    return False
                if default_event_check(event):
                    return True
                return False

            # Wait for trigger event using handler
            event: CtxEventBase = self.ctx_handler.wait_for_sync(
                check=extended_wait_check, timeout=15.0, raise_timeout=False
            )

            if event:
                print(f"[REACTION AGENT] Triggered by event: {event}")
                self.react(event)
            else:
                print("[REACTION AGENT] No trigger event found")

        except Exception as e:
            print(f"[REACTION AGENT] Error: {e}")
            traceback.print_exc()

    def run(self):
        """Main loop: wait for events and react immediately"""
        print("[REACTION AGENT] Starting...")
        self.running = True

        while self.ctx_swarm["env"]["actived"] and self.running:
            self.step()

    def stop(self):
        """Stop the agent"""
        self.running = False
        print("[REACTION AGENT] Stopped")

    def cleanup(self):
        """Clean up resources"""
        if self.running:
            self.stop()
        if hasattr(self, "llm"):
            del self.llm
