"""
Base tools
Tool functions for agents.

Compatible to smolagents and langchain agent tool format.
"""

import json
from typing import Any, Callable, Dict, List, Optional, Sequence

# TOOLS CONFIG SHOULD BE FIRST!!!
from agent.tools import tools_config
from agent.tools.base_tools import (
    chat_simple,
    clear_queue,
    interrupt_chat,
    interrupt_voice,
    mc_send,
    private_messages,
    save_user_info,
    speak,
    voice_send,
    wait,
)
from agent.tools.control_tools import (
    agent_start_effects,
    agent_wipe_state,
    agent_wipe_state_effects,
    change_personality,
    directive,
)
from agent.tools.dialogue_tools import dialogue_step, dislike, like
from agent.tools.state_tools import focus, pattern, plan, state_update
from agent.tools.status_tools import (
    convert_tools_to_langchain,
    disable_tool,
    enable_tool,
    get_chat_status,
    get_game_status,
    get_plan,
    get_thought_status,
    get_tool_status,
    get_tts_status,
    get_vote_status,
    status,
    toggle_tool,
    validate_tool,
)
from agent.tools.tool_executor import execute_tools
from agent.tools.vision_tools import screenshot
from data_schema.structure_templates import FX_MANIFEST
from data_schema.tool_structures import ToolRecord
from utils.debug import bcolors
from utils.prompt_helper import yaml_load

active_votes = tools_config.active_votes
ctx_swarm = tools_config.ctx_swarm
queue_send = tools_config.queue_send


def fx(fx_name="warning"):
    "Play sound fx effect from provided in fx_manifest.yml"
    if fx_name:
        ctx_swarm["fx_queue"].put(fx_name)


def get_fx_names() -> str:
    "Get all sound fx names"
    return json.dumps(yaml_load(FX_MANIFEST), ensure_ascii=False)


ALL_TOOLS = [
    # base_tools
    interrupt_chat,
    interrupt_voice,
    save_user_info,
    speak,
    wait,
    voice_send,
    mc_send,
    chat_simple,
    private_messages,
    clear_queue,
    screenshot,
    # dialogue_tools
    dialogue_step,
    like,  # TODO UNTESTED!!!
    dislike,
    # state_tools
    focus,
    pattern,
    plan,
    state_update,
    # status_tools
    get_tool_status,
    get_vote_status,
    get_chat_status,
    get_game_status,
    status,
    get_thought_status,
    get_plan,
    get_tts_status,
    toggle_tool,
    enable_tool,
    disable_tool,
    # control_tools
    directive,
    change_personality,
    agent_start_effects,
    agent_wipe_state_effects,
    agent_wipe_state,
    # local tools
    fx,
    get_fx_names,
]

TOOL_STATUSES = []

# only for operator-use tools
DEFAULT_DISABLED_TOOLS = [
    # control_tools FOR DEV
    directive,
    change_personality,
    agent_start_effects,
    agent_wipe_state_effects,
    agent_wipe_state,
    # vote_register,
    # finish_vote,
    # start_vote,
    # statuses too much tokens
    get_tool_status,
    get_vote_status,
    get_chat_status,
    get_game_status,
    toggle_tool,
    enable_tool,
    disable_tool,
    status,
    get_thought_status,
    get_plan,
    get_tts_status,
    state_update,
    dialogue_step,  # not implemented
    # temporally disable
    interrupt_chat,
    interrupt_voice,
    # inner queue tools
    voice_send,
    mc_send,
    chat_simple,
    private_messages,
    clear_queue,
]

# REDUDANT FOR NOW

INTERRUPT_TOOLS = [interrupt_chat, interrupt_voice]
SPEAK_TOOLS = [speak, save_user_info]
STATE_TOOLS = [plan, focus]
DIALOGUE_TOOLS = [dialogue_step]
GENERATOR_TOOLS = []  # [generate_joke]  # check if it's afk issue cause
AGENT_SUPERVISOR_TOOLS = []
AGENT_SUPERVISOR_TOOLS.extend(SPEAK_TOOLS)
AGENT_SUPERVISOR_TOOLS.extend(GENERATOR_TOOLS)
AGENT_SUPERVISOR_TOOLS.extend(INTERRUPT_TOOLS)

AGENT_SUPERVISOR_TOOLS.extend([wait])

AGENT_SUPERVISOR_TOOLS_RAW = AGENT_SUPERVISOR_TOOLS.copy()
AGENT_SMO_TOOLS_RAW = AGENT_SUPERVISOR_TOOLS_RAW.copy()
AGENT_SMO_TOOLS_RAW.append(state_update)
AGENT_SUPERVISOR_TOOLS_RAW.extend(STATE_TOOLS)

# for tool in AGENT_SUPERVISOR_TOOLS_RAW:
#     register_tool(tool.__name__, tool)


AGENT_SUPERVISOR_TOOLS = convert_tools_to_langchain(AGENT_SUPERVISOR_TOOLS)

INTERRUPT_TOOLS_NAMES = [tool_item.__name__ for tool_item in INTERRUPT_TOOLS]


def get_tool_records(output_format: str = "list") -> Dict[str, ToolRecord]:
    """Get tools smartly with availability and cooldown checking"""
    output = {}
    for name, tool_record in tools_config.tool_bank.items():
        if validate_tool(tool_record):
            output[name] = tool_record
    return list(output.values()) if output_format == "list" else output


def get_tools(output_format: str = "list") -> Dict[str, Any]:
    """Get tools smartly with availability and cooldown checking"""
    output = {}
    for name, tool_record in tools_config.tool_bank.items():
        if validate_tool(tool_record):
            output[name] = tool_record["tool"]
    return list(output.values()) if output_format == "list" else output


def get_tool_names() -> List[str]:
    return list(get_tools("dict").keys())


# def stream_llm(prompt_messages: Sequence) -> Sequence:
#     """Stream LLM"""
#     return tools_config.llm_model.stream(prompt_messages)


def default_exec_callaback(*args, **kwargs):
    print(
        bcolors.OKGREEN,
        "[TOOL] Executed:",
        args,
        kwargs,
        bcolors.ENDC,
    )


def execute_tool_query(
    prompt_messages: Sequence,
    should_interrupt: Optional[Callable] = None,
    response_starting: str = "",
) -> Any:
    """Execute tool query"""

    def callable_printer(x):
        if isinstance(x, str):
            token = x
        else:
            token = x.content
        print(bcolors.OKCYAN + str(token) + bcolors.ENDC, flush=True, end="")

    return execute_tools(
        tools_config.llm_model.stream(prompt_messages),
        generator_callable=callable_printer,
        tool_exec_callable=default_exec_callaback,
        response_starting=response_starting,
        tool_bank=tools_config.tool_bank,
        max_tool_run_cnt=5,
        should_interrupt=should_interrupt,
        allow_disabled_tools=False,
    )
