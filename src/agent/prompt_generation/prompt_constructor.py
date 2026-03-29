"""Prompt constructor for professor agent response generation.

Creates the system prompt and message chain for the LLM.
"""

import time
from threading import Thread
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.messages import (
    BaseMessage,
    SystemMessage,
    convert_to_messages,
)

from config_schema.general import get_name, get_secret
from data_flow.ctx_handler import CtxHandler
from data_schema.chat_structures import (
    CtxEventBase,
    default_event_check,
    interrupt_event_check,
)
from data_schema.tool_structures import ToolRecord
from utils.format_helper import (
    format_events_for_rag,
    format_events_with_roles,
    openai_chat_to_str,
)
from utils.prompt_helper import prompt_load

SELF_NAME = get_name()

PROFESSOR_GOAL = f"""Ты — {SELF_NAME}, ИИ-ассистент преподавателя.
Отвечай на вопросы студентов кратко и по делу (2-4 предложения).
Используй русский язык и мужской род.
Если в чате есть вопрос — ответь на него. Если вопросов нет — жди.
Не выдумывай факты. Не повторяйся."""


def construct_prompt(
    rag_context: Optional[str],
    ctx_swarm: dict,
) -> str:
    """Build system prompt from personality template + RAG context."""
    personality_key = ctx_swarm["states"].get("personality", "professor_default")
    personality_file = "personalities_professor" if "professor" in personality_key else "personalities"
    system_template = prompt_load(personality_file, personality_key)

    final_rag_context = (
        "\n\n## Контекст из материалов курса:\n" + rag_context if rag_context else ""
    )
    return system_template + final_rag_context


def create_chat_from_prompt(prompt: str, role: str = "system") -> List[Dict]:
    return [{"role": role, "content": prompt}]


def convert_message(prompt: str, output_format: str = "langchain") -> List[BaseMessage]:
    """Converts a prompt string to Langchain Messages format"""
    if output_format == "langchain":
        return [SystemMessage(content=prompt)]
    elif output_format == "dicts":
        return [{"role": "system", "content": prompt}]
    else:
        return prompt


class SmartEventWaiter:
    def __init__(self, ctx_handler: CtxHandler, delay: float = 5):
        self.handler: CtxHandler = ctx_handler
        self.delay: float = delay
        self.caught: bool = False
        self.activated: bool = True
        self.thread: Thread = Thread(target=self._wait_loop, daemon=False)
        self.caught_event: Union[CtxEventBase, None] = None
        self.thread.start()

    def check(self) -> bool:
        if self.caught:
            self.caught = False
            return True
        return False

    def _wait_loop(self) -> None:
        if self.delay > 0:
            event = self.handler.wait_for_sync(
                check=interrupt_event_check, timeout=self.delay, raise_timeout=False
            )
            if event:
                self.caught = True
                self.caught_event = event
                return
        while self.activated:
            self._wait()

    def _wait(self) -> Union[CtxEventBase, None]:
        event: Union[CtxEventBase, None] = self.handler.wait_for_sync(
            timeout=15.0, raise_timeout=False
        )
        if event and event.processing_timestamp != -1:
            self.caught = True
            self.caught_event = event
        return event

    def shutdown(self):
        self.activated = False

    def __exit__(self, *args, **kwargs):
        self.shutdown()


def construct_prompt_messages(
    tools: List[ToolRecord],
    ctx_handler: CtxHandler,
    wait_for_trigger: bool = True,
    rag_model: Any = None,
    output_format: str = "langchain",
    tool_use_format="command",
    goal: str = None,
    unfinished_response: str = "",
    response_starting: str = "",
) -> Tuple[Union[List[BaseMessage], List[Dict], str], str]:
    """
    Constructs prompt messages for the professor agent.

    Returns:
        Tuple of (messages, response_starting)
    """

    #######################
    # WAITING FOR TRIGGER #
    #######################

    rag_context = ""
    try:
        if wait_for_trigger:
            print("[AGENT] Waiting for trigger...")
            check_start_time = time.time()

            def extended_wait_check(event: CtxEventBase) -> bool:
                def check_timeout():
                    return time.time() - check_start_time > 30.0

                if len(ctx_handler.ctx_swarm["chat_queue"]) > 1 and not check_timeout():
                    return False
                if len(ctx_handler.ctx_swarm["tts_queue"]) > 1 and not check_timeout():
                    return False
                if default_event_check(event):
                    return True

            event: Union[CtxEventBase, None] = ctx_handler.wait_for_sync(
                check=extended_wait_check, timeout=15.0, raise_timeout=False
            )
            event_id = -1
        else:
            event = None
            event_id = -1
        if event:
            print(f"[AGENT] Triggered by event: {event}")
            event_id = event.processing_timestamp
        else:
            print("[AGENT] No trigger event found")
    except Exception as e:
        print(f"[AGENT] Error waiting for trigger event: {e}")
        event = None
        event_id = -1

    # RAG context
    rag_context = ""
    try:
        if rag_model is not None:
            if event is not None:
                for_rag_events = ctx_handler.get_ctx_chat(dict_format=True, limit=2)
                for_rag_events.append(event.to_dict())
            else:
                for_rag_events = ctx_handler.get_ctx_chat(dict_format=True, limit=3)
            if for_rag_events:
                rag_context = rag_model.explain(format_events_for_rag(for_rag_events))
            if not rag_context:
                rag_context = ""
    except Exception as e:
        print(f"[AGENT] Error getting RAG context: {e}")
        rag_context = ""

    # Format chat history as messages
    messages_dicts, _mentioned_users = format_events_with_roles(
        ctx_handler.get_ctx_chat(validate=True, dict_format=True, limit=50),
        trigger_event_id=event_id,
        return_mentioned_users=True,
    )

    # Build system prompt
    prompt = construct_prompt(
        rag_context,
        ctx_swarm=ctx_handler.ctx_swarm,
    )

    if goal is None:
        goal = PROFESSOR_GOAL
    goal_message = f"\n\n\n# === Инструкция ===\n{goal}"

    if len(messages_dicts) > 0:
        prompt += "\n\n======= Последние сообщения чата START ======"
        messages = create_chat_from_prompt(prompt)
        messages.extend(
            messages_dicts
            + create_chat_from_prompt(
                "======= Последние сообщения чата END ======"
                + goal_message,
                role="user",
            )
        )
    else:
        messages = create_chat_from_prompt(prompt + goal_message)

    if output_format == "langchain":
        messages = convert_to_messages(messages)
    elif output_format == "string":
        return openai_chat_to_str(messages)
    return messages, response_starting
