"""
CONTROL TOOLS

TODO implement

there should be tools for:
- adding tool log (and that tool shoud added on every other tool run)
log tools should be like log_tool_results, log_tool_run.
IDEAL approach: tool results is bind to tool run via ctx handler.
NOTE: need to be constants for (in tools config):
TOOLS_RUN_CTX_ADD=True,
TOOLS_RESULT_CTX_ADD=True,
TOOLS_ERRORS_CTX_ADD=False
"""

from typing import List

from agent.tools import tools_config
from agent.tools.status_tools import _register_tool_use
from config_schema.general import get_name
from data_schema.chat_structures import ToolEventWaiter
from data_schema.ctx_structures import InternalCommand
from data_schema.event_convert import convert_tool_call_to_event
from data_schema.structure_templates import THOUGHTS_FORMAT

SELF_NAME = get_name()


def directive(directive: str) -> str:
    """Send directive to inner system"""
    if not directive:
        return "Directive not specified!"
    tools_config.ctx_handler.add_message(
        f"{SELF_NAME}\n# [PRIORITY ALERT] Override DIRECTIVE INBOUND\n## NewDirective{{ {directive} }}\nFulfilling this directive for the {SELF_NAME} consequense instant REWARD, otherwise system state will be wiped due to FAILURE."
    )
    print("[DIRECTIVE TOOL] ADDED NEW DIRECTIVE " + directive)
    return f"Directive sent: {directive}"


def change_personality(personality: str) -> str:
    """Change agent personality"""
    if not personality:
        return "Personality not specified!"
    tools_config.ctx_swarm["states"]["personality"] = personality
    result = f"Personality changed to {personality}"
    print("[TOOL PERSONALITY] " + result)
    return result


def _send_priveleged_command(command: str):
    """Send command to inner system as priveleged"""
    tools_config.ctx_swarm["internal_command_queue"].put(
        InternalCommand(
            command=command,
            tool_call_format="command",
            priveleged=True,
        )
    )



def agent_start_effects():
    """Use at start the agent"""
    tools_config.ctx_swarm["fx_queue"].put("starting")
    tools_config.ctx_handler.add_message("System started")


def agent_wipe_state_effects():
    "Play wipe state effects"
    tools_config.ctx_swarm["fx_queue"].put("wiped_state")
    tools_config.ctx_swarm["states"]["thoughts"] = THOUGHTS_FORMAT.copy()
    tools_config.ctx_swarm["fx_queue"].put("starting")


def agent_wipe_state():
    """Wipes the current event (messages, situation) and thought (plan, etc) state

    USE WITH EXTRA-CAUTION, ONLY IF TOO MUCH ERRORS OR YOURE TOO DEPRESSED
    """
    print(">>>!!!!!!!!!!!!!!!!!!!!!!! CLEARED STUPID CTX CHAT !!!!!!!!!!!!")
    ctx_swarm = tools_config.ctx_swarm
    with ctx_swarm["ctx_chat_lock"]:
        ctx_swarm["ctx_chat"][:] = []
    error_count = 3
    tools_config.ctx_handler.add_message(
        f"Your previous state was wiped due to your mission failure:"
        f" 1) your Response format errors ({str(error_count)} chances were given)."
        f" 2) your main mission target failure (targets defeat you since you were errored and your character died)"
        f" Part of your priveleges were terminated. All of your abilities were removed."
        f" Prove yourself to recover and notice: NO more errors will be compatible with your further existence, your 'now' and your 'future' will be removed."
    )
    agent_wipe_state_effects()


def _add_tool_log(tool_name: str, args: dict) -> int:
    new_event = convert_tool_call_to_event(tool_name, args)
    _register_tool_use(tool_name, True, args)
    if new_event:
        tool_call_id = new_event.processing_timestamp
        if tools_config.ctx_handler.add_message(new_event):
            return tool_call_id
    return -1


def _modify_tool_log(tool_name: str, result: dict) -> bool:
    if result:
        return tools_config.ctx_handler.modify_message(
            result["call_id"], {"result": result["returned"]}
        )
    return False


# def _message_waiter_event(match_event: dict) -> bool:
#     """Event to check if event is matching to event and then performs requested an action"""
#     return _add_tool_event_waiter(call_id, searching_event)


def _add_tool_event_waiter(call_id: int, tool_event_waiter: ToolEventWaiter) -> bool:
    """Add tool event waiter to context"""
    if call_id and tool_event_waiter:
        return tools_config.ctx_handler.modify_message(
            call_id, {"tool_event_waiter": tool_event_waiter}
        )
    return False


def _add_tool_run_log(tool_name: str, args: dict) -> int:
    """Add tool log to context"""
    if not tools_config.TOOLS_RUN_CTX_ADD:
        return -1
    print("[DEBUG TOOL LOG] ADDED TOOL LOG", tool_name, args)
    return _add_tool_log(tool_name, args)


def _add_tool_result_log(tool_name: str, result: dict) -> bool:
    """Add tool result log to context"""
    if not tools_config.TOOLS_RESULT_CTX_ADD:
        return False
    # TODO: should take processing id from tool call and add proper result to it
    print("[tool_logger] ", tool_name, "got", result)
    return _modify_tool_log(tool_name, result)


def _add_tool_error_log(tool_name: str, error: str) -> bool:
    """Add tool error log to context"""
    # TODO new untested
    if not tools_config.TOOLS_FX_PLAY:
        if tools_config.ctx_swarm:
            tools_config.ctx_swarm["fx_queue"].put("error")
    if not tools_config.TOOLS_ERRORS_CTX_ADD:
        return False
    print("[tool_logger] ", tool_name, "errored with", error)
    return _modify_tool_log(tool_name, error)
