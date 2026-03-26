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

import requests
from markdownify import markdownify
from requests.exceptions import RequestException
from smolagents import (
    CodeAgent,
    DuckDuckGoSearchTool,
    ManagedAgent,
    Tool,
    ToolCallingAgent,
    tool,
)

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )
    from data_schema.structure_templates import CTX_SWARM_EMPTY
    from utils.structure_helper import load_ctx_chat_sample

    # ctx_chat = load_ctx_chat_sample()  # fixed ctx chat

    ctx_swarm = CTX_SWARM_EMPTY.copy()
    ctx_swarm["ctx_chat"] = []
    ctx_chat = ctx_swarm["ctx_chat"]
    ctx_state = ctx_swarm["states"]
    load_ctx_chat_sample(realtime=True, new_ctx_chat=ctx_chat, add_time=10)

from agent.llm_clients.smo_clients import get_smo_llm
from utils.format_helper import format_events_for_llm
from utils.prompt_helper import prompt_load

streamer_main_role_description = prompt_load("personalities", "streamer_abstract")


@tool
def visit_webpage(url: str) -> str:
    """Visits a webpage at the given URL and returns its content as a markdown string.

    Args:
        url: The URL of the webpage to visit.

    Returns:
        The content of the webpage converted to Markdown, or an error message if the request fails.
    """
    try:
        # Send a GET request to the URL
        response = requests.get(url)
        response.raise_for_status()  # Raise an exception for bad status codes

        # Convert the HTML content to Markdown
        markdown_content = markdownify(response.text).strip()

        # Remove multiple line breaks
        markdown_content = re.sub(r"\n{3,}", "\n\n", markdown_content)

        return markdown_content

    except RequestException as e:
        return f"Error fetching the webpage: {str(e)}"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


# model_id = "Qwen/Qwen2.5-Coder-32B-Instruct"
# model = HfApiModel(model_id)

model = get_smo_llm()

web_agent = ToolCallingAgent(
    tools=[DuckDuckGoSearchTool(), visit_webpage],
    model=model,
    max_iterations=10,
)

managed_web_agent = ManagedAgent(
    agent=web_agent,
    name="search",
    description="""FOR USE BY YOU (INNER USE). Runs web searches for you. Give it your request as an argument. It should use like:
    ```python
    search(request='Your request')
    ```
    """,
)


ctx_state["game_state"] = "Nothing is happening."


MAXIMUM_STATE_LENGTH = 1000


def check_state_length(str: str) -> str:
    """check_state_length("state"). Returns "state" if it is not longer than 1000 characters."""
    assert len(str) < MAXIMUM_STATE_LENGTH
    return str


@tool
def report_game_state(state: str) -> str:
    """report_game_state("new state"). REPLACES current state.

    Args:
        state: The current game state summarization.
    """
    try:
        ctx_state["game_state"] = check_state_length(state)
        return state
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@tool
def report_chat_state(state: str) -> str:
    """report_chat_state("new state"). REPLACES current state.

    Args:
        state: The current chat state summarization.
    """
    try:
        ctx_state["chat_state"] = check_state_length(state)
        return state
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


@tool
def flag_event(processing_timestamp: int) -> str:
    """Rude event flagger. Removes the event from the ctx_chat. USE WITH CAUTION AND ONLY FOR SUSPICIOUS OR RULE/LAW BREAKING TEXTS!

    Usage: flag_event(4325436346346)

    Args:
        processing_timestamp: The processing timestamp field of an event to flag and remove.
    """
    try:
        # TODO add logic
        return "Event " + str(processing_timestamp) + " removed"
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


STATES_LIST = ["game_state", "chat_state", "emotional_state"]


@tool
def update_states(states: dict) -> str:
    """update_states("new state"). UPDATES current state variable. Call after any state changes to commit them to database.

    Args:
        states: The current states dict-like variable ONLY with keys of states
    """
    try:
        to_update = {}
        for state in STATES_LIST:
            if state in states.keys():
                to_update[state] = states[state]
            else:
                print("State not found:", state)
        ctx_state.update(to_update)
    except Exception as e:
        return f"An unexpected error occurred: {str(e)}"


manager_agent = CodeAgent(
    # tools=[report_game_state, report_chat_state, flag_event],
    tools=[update_states, flag_event],
    model=get_smo_llm(),
    # managed_agents=[managed_web_agent],
    additional_authorized_imports=["time", "numpy", "pandas"],
    max_iterations=2,
)


def limit_ctx_chat(ctx_chat) -> list:
    """limit_ctx_chat(). Returns ctx_chat with limited length."""
    LIMIT_FOR_CTX_CHAT = 10
    if len(ctx_chat) <= LIMIT_FOR_CTX_CHAT:
        return list(ctx_chat)
    return list(ctx_chat[: LIMIT_FOR_CTX_CHAT - 1])


class PreparedSwarm(dict):
    def __str__(self):
        return json.dumps(dict(self), indent=2, ensure_ascii=False)


def prepare_ctx_swarm_for_llm(ctx_swarm_proxy: dict) -> dict:
    """prepare_ctx_swarm_for_llm(ctx_swarm_proxy). Returns ctx_swarm for LLM model."""
    formatted_swarm = {}  # dict(ctx_swarm_proxy)
    formatted_swarm["provided_data_description"] = {
        "states": {
            "game_state": "Str: The previous game state short general summarization.",
            "chat_state": "Str: The previous chat state summarization. Should be about PEOPLE, players, etc.",
            "emotional_state": "Str: The previous emotional state summarization.",
        },
        "ctx_chat": "List[Dict]: The of recent NEW up-to-date events. Represents current actual situation.",
    }
    ctx_state_this = {}
    ctx_state_proxy = ctx_swarm_proxy["states"]
    formatted_swarm["states"] = ctx_state_this
    state_keys = STATES_LIST
    for state_key in state_keys:
        ctx_state_this[state_key] = ctx_state_proxy[state_key]
    event_key = "ctx_chat"
    if "ctx_chat" in ctx_swarm_proxy.keys():
        new_ctx_chat = limit_ctx_chat(ctx_swarm_proxy[event_key])
        ctx_chat_to_add = []
        for event in new_ctx_chat:
            event = {
                k: v for k, v in event.items() if v is not None
            }  # remove none items
            ctx_chat_to_add.append(event)
        formatted_swarm["ctx_chat"] = ctx_chat_to_add

    return PreparedSwarm(formatted_swarm)


if __name__ == "__main__":

    states = prepare_ctx_swarm_for_llm(ctx_swarm)
    print("STATE PREPARED")
    time.sleep(0.5)
    print("RUNNING AGENT...")
    manager_agent.run(
        task="""
Your game nickname is NetTyan - it is YOU.
You are low-level utility agent - NetTyan util agent unit #3650.
You don't have tools you are not directived with upper.
DO NOT USE IMAGINE OR NONEXISTENT TOOLS.
If you are using non-authorized tools, your result will be flagged as failure.
Unit #3650 (NetTyan), you are tasked with directives:
1. Update the emotional, 2) chat and 3) game state on ctx_chat event situation change.
4. Confirm state changes using the ctx_chat field info. It is filled with new recent events. 
5. Flag the event if it is not suitable for stream.
6. Report ALL the changed states: chat, game, emotional.
7. Change the states as needed and DONT report changes for which situation is the same
8. Final answer should be gave in strict form with completed directives in format specified below as tool:

final_answer("(numbers of directives used), 6, 7, 8")

Directives 6, 7, 8 should always be completed, others on demand.

Unit's #3650 failure will result in perk termination.
Unit's #3650 comply and success will be appreciated and rewarded with special deliver.

You can change your state by interacting with it just like with python dict.


========= EXAMPLE RUN =========

```python
(event json about start skywars game in 3 seconds)
(previous game state is "doing nothing" )

new_states = {
    "game_state": "Minecraft Skywars game starting soom, in 3 seconds.",
}

update_states(new_states)
```

========= EXAMPLE RUN END =========


Strictly use as LESS and EASY code as presented above.
ANY other interaction scenarios are not permitted and will be marked as failure.
The reason: you are running in a very tiny closed environment.


Further you will be provided with previous states (in '*_state' ) and latest events (in ctx_chat). 
""",
        # single_step=True,
        additional_args=states,
    )
    print("New states:")
    del ctx_swarm["ctx_chat"]  # only for debug and good view
    print(str(PreparedSwarm(ctx_swarm)))
