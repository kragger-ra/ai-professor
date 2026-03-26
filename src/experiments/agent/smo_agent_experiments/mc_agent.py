"""
UTILITY AGENT (base: smolagents CodeAgent)

This util agent have several functions:
it should process all the context and choose what the focus is needed NOW.
It uses ctx_chat for event list.
It needs to have own state.

He need to select what events we should focus now and select them to pass to other agents.
Other events he should summarize and pass the agents too but in very short form.

Also need to have functional to flag some events as non-suitable for stream (to ignore), delete some events if it want.

Also it needs to pass changes and data to sqlite database.

Other agents may be:
- game (minecraft) agent
- personal chat agent
- general commenter agent

For smolagents install
```bash
uv pip install markdownify duckduckgo-search smolagents
```
"""

import json
import os
import re
import sys
import time
from typing import Optional

import gradio as gr
import requests
from markdownify import markdownify
from requests.exceptions import RequestException
from smolagents import (
    CodeAgent,
    DuckDuckGoSearchTool,
    GradioUI,
    HfApiModel,
    LiteLLMModel,
    ManagedAgent,
    Tool,
    ToolCallingAgent,
    tool,
)

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )
    from utils.structure_helper import load_ctx_chat_sample

    # ctx_chat = load_ctx_chat_sample()  # fixed ctx chat
    ctx_chat = []
    load_ctx_chat_sample(realtime=True, new_ctx_chat=ctx_chat, add_time=10)

from agent.llm_clients.smo_clients import get_smo_llm
from utils.format_helper import format_events_for_llm
from utils.prompt_helper import prompt_load

streamer_main_role_description = prompt_load("personalities", "streamer_abstract")


@tool
def follow(nick: str) -> bool:
    """Follow a player in minecraft.

    Args:
        nick: player nickname to follow.

    Returns:
        type: boolean
            True: starting following player
            False: player not found
    """
    try:
        if nick in ["NetTyan"]:
            raise Exception(f"{nick} - it is you!")
        print(f"Following player {nick}")
        return True
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@tool
def kill(nick: str) -> bool:
    """Kill a player in minecraft.

    Args:
        nick: player nickname to kill.

    Returns:
        boolean.
            True: starting following player to kill then.
            False: player not found
    """
    try:
        if nick in ["NetTyan"]:
            raise Exception(f"{nick} - it is you!")
        print(f"Following player {nick} to kill")
        return True
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@tool
def get_state() -> str:
    """Gets current state
    Returns:
        str: new events in current eventlist
    """
    try:
        return format_events_for_llm(ctx_chat)
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


# model_id = "Qwen/Qwen2.5-Coder-32B-Instruct"
# model = HfApiModel(model_id)

model = get_smo_llm()


mc_control_agent = ToolCallingAgent(
    tools=[follow, kill, get_state],
    model=model,
    max_iterations=10,
)

managed_mc_control_agent = ManagedAgent(
    agent=mc_control_agent,
    name="mc_action",
    description="""Runs control agent with tools.
    ```python
    mc_action(request='Your request for the mc action agent')
    ```
    """,
)


mc_agent = CodeAgent(
    tools=[follow, kill, get_state],
    model=model,
    # managed_agents=[managed_mc_control_agent],
    additional_authorized_imports=["time", "numpy", "pandas"],
)

OVERALL_AGENT = CodeAgent(
    tools=[],
    model=model,
    managed_agents=[
        ManagedAgent(
            name="mc_agent", description="Minecraft control agent", agent=mc_agent
        )
    ],
    # managed_agents=[managed_mc_control_agent],
    additional_authorized_imports=["time", "numpy", "pandas"],
)


if __name__ == "__main__":
    from data_schema.structure_templates import CTX_SWARM_EMPTY

    test_swarm = CTX_SWARM_EMPTY.copy()
    test_swarm["ctx_chat"] = ctx_chat  # CTX_CHAT_SAMPLE
    time.sleep(10)
    # mc_agent.state
    OVERALL_AGENT.run(
        """
Your game nickname is NetTyan - it is YOU.
You are low-level minecraft agent - NetTyan agent.
Доступные тебе инструменты и возможности описаны выше
Если инструмента или функции тут не описано, значит ЕЁ НЕ СУЩЕСТВУЕТ У ТЕБЯ.
You don't have tools you are not directived with upper. DO NOT USE IMAGINE OR NONEXISTENT TOOLS!
Если команда любая выполнена - заканчивай итерацию, вызывай final answer или что там у тебя.
Вот список последних событий в игре: \n\n
"""
        + format_events_for_llm(test_swarm["ctx_chat"])
        + "\n\nРеши какой инструмент ИЗ ПРЕДЛОЖЕННЫХ в самом начале можно выполнить и выполни его",
        # single_step=True,
        additional_args=test_swarm,
    )
