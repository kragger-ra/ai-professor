"""
Status tools module provides simple status reporting functions:

1. Tool usage tracking:
    - Register and track tool calls
    - Monitor success/error counts
    - Track last used timestamps (relative to now)

2. System state reporting:
    - Chat queue status
    - Current vote status
    - Agent thoughts status
    - TTS system status

3. Status summary generation:
    - Combines all non-empty statuses
    - Shows only active/relevant info
    - Includes tool usage statistics
    - Provides info for prompt creation

Each status function returns empty string when nothing to report.
"""

import time
from typing import Any, Callable, Dict, Optional, TypedDict

from langchain_core.tools import StructuredTool

from agent.tools import tools_config
from data_schema.tool_structures import ToolRecord
from utils.time_helper import format_relative_time


def get_langchain_tool(function: Callable) -> StructuredTool:
    return StructuredTool.from_function(function, parse_docstring=True)


def convert_tools_to_langchain(tools_list: list[Callable]) -> list[StructuredTool]:
    for i, tool_func in enumerate(tools_list):
        tool_func = get_langchain_tool(tool_func)
        tools_list[i] = tool_func
    return tools_list


def _register_tool_use(
    tool_name: str, success: bool = True, last_args: dict = None
) -> None:
    """Update tool usage statistics"""
    if tool_name in tools_config.tool_bank:
        tool_record = tools_config.tool_bank[tool_name]
        tool_record["last_call"] = time.time()
        tool_record["call_count"] += 1
        if last_args:
            tool_record["last_args"] = last_args
        if success:
            tool_record["success_count"] += 1
        else:
            tool_record["error_count"] += 1


def validate_tool(tool_record: ToolRecord) -> bool:
    """Check tool for agent use:
    - is enabled cooldown is normal
    - is not disabled"""
    if tool_record["disabled"]:
        return False
    # TODO UNTESTED!
    cd = tool_record.get("cooldown", 0)
    if cd > 0:
        last_call = tool_record.get("last_call", -1)
        if last_call != -1:
            delta = time.time() - last_call
            if delta < tool_record["cooldown"]:
                return False
    return True


def register_tool(
    name: str, func: Callable, disable: bool = False, config=None
) -> ToolRecord:
    """Register a tool in the bank"""

    tool_record = ToolRecord(
        name=name,
        last_call=-1,
        call_count=0,
        success_count=0,
        error_count=0,
        cooldown=0,
        disabled=disable,
        args={},
        function=func,
        description=func.__doc__,
        tool=get_langchain_tool(func),
    )
    # TODO untested
    if config:
        for field in config:
            if field in tool_record:
                tool_record[field] = config[field]
    tools_config.tool_bank[name] = tool_record
    return tools_config.tool_bank[name]


def register_tool_status(name: str, get_status: Callable) -> ToolRecord:
    """Register a tool status function"""
    if name in tools_config.tool_bank:
        tools_config.tool_bank[name]["get_status"] = get_status
        return tools_config.tool_bank[name]
    return ToolRecord()


def toggle_tool(tool_name: str, disable: Optional[bool] = None) -> bool:
    """Toggle tool by name and boolean enable/disable"""
    print("[TOOL TOGGLE REQUESTED] " + tool_name + ", on=" + str(disable))
    if tool_name in tools_config.tool_bank:
        if disable is None:
            disable = not tools_config.tool_bank[tool_name]["disabled"]
        tools_config.tool_bank[tool_name]["disabled"] = disable
        print(tools_config.tool_bank[tool_name])
        return True
    return False


def enable_tool(tool_name: str) -> bool:
    """Enable a tool by name"""
    return toggle_tool(tool_name, False)


def disable_tool(tool_name: str) -> bool:
    """Disable a tool by name"""
    return toggle_tool(tool_name, True)


def get_tool_last_call_relative(tool_name: str) -> str:
    """Get relative time since tool was last called"""
    if tool_name not in tools_config.tool_bank:
        return ""
    tool_status = tools_config.tool_bank[tool_name]
    if tool_status["last_call"] == -1:
        return ""
    return format_relative_time(tool_status["last_call"])


def get_additional_tool_status(tool_name: str) -> str:
    """Get status of a specific tool"""
    if tool_name == "start_vote":
        return get_vote_status()
    elif tool_name == "minecraft_command":
        return get_chat_status()
    # elif tool_name == "thought":
    #     return get_thought_status()
    elif tool_name == "speak":
        return get_tts_status()
    else:
        last_call = get_tool_last_call_relative(tool_name)
        if last_call == "":
            return ""
        return "used " + get_tool_last_call_relative(tool_name)


def get_tool_status(tool_name: str) -> str:
    """Get status of a specific tool"""
    if tool_name not in tools_config.tool_bank:
        return ""
    tool_record = tools_config.tool_bank[tool_name]
    get_status = tool_record.get("get_status", None)
    base_status = get_additional_tool_status(tool_name)
    if get_status:
        status = get_status()
        return f"{base_status}\nUseful information:\n{status}"
    else:
        return base_status


def get_vote_status() -> str:
    """Get status of the voting system"""
    states = tools_config.ctx_swarm.get("states", {})
    vote = states.get("current_vote")
    if not vote:
        return ""
    counts = states.get("vote_counts", {})
    return f"Vote: {vote} - Counts: {counts}"


def get_chat_status() -> str:
    """Get status of the chat print (chat pending queue) system"""
    queue_len = len(tools_config.ctx_swarm.get("chat_queue", []))
    return f"Chat queue: {queue_len} messages" if queue_len > 0 else ""


def get_thought_status() -> str:
    """Only get thought status if present else empty string"""
    thoughts = tools_config.ctx_swarm.get("states", {}).get("thoughts", {})
    return f"Thoughts: {thoughts}" if thoughts else ""


def get_game_status() -> str:
    """Get status of the game process"""
    return ""


def get_tts_status() -> str:
    """ONLY get tts queue status, is speaking and last emotion"""
    states = tools_config.ctx_swarm.get("states", {})
    speaking = states.get("is_speaking", False)
    queue = len(states.get("tts_queue", []))
    if not speaking and queue == 0:
        return ""
    emotion = states.get("last_emotion", "neutral")
    status = "Speaking" if speaking else "Idle"
    return f"TTS {status} - Emotion: {emotion}, Queue: {queue}"


def _get_tool_statuses() -> Dict[str, Any]:
    """Get status of all registered tools"""
    tool_stats = {}
    for name, status in tools_config.tool_bank.items():
        tool_stats[name] = {
            "last_used": get_tool_last_call_relative(name),
            "call_count": status["call_count"],
            "success_count": status["success_count"],
            "error_count": status["error_count"],
        }
    return tool_stats


def _get_chat_queue_info() -> Dict[str, Any]:
    """Get current chat queue status"""
    return {
        "queue_length": len(tools_config.ctx_swarm.get("chat_queue", [])),
    }


def _get_votes_info() -> Dict[str, Any]:
    """Get current voting system status"""
    states = tools_config.ctx_swarm.get("states", {})
    return {
        "current_vote": states.get("current_vote", None),
        "vote_options": states.get("vote_options", []),
        "vote_counts": states.get("vote_counts", {}),
        "voting_active": bool(states.get("current_vote")),
    }


def get_plan() -> Dict:
    """Get current agent thoughts state"""
    # lets just return plan for now...
    return (
        tools_config.ctx_swarm.get("states", {})
        .get("thoughts", {})
        .get("plan", "Set a new plan!")
    )
    # return tools_config.ctx_swarm.get("states", {}).get("thoughts", {})


# TODO
# UNTESTED
# UNFINISHED
def status() -> str:
    """Get a status summary showing current tool system state"""
    parts = []
    # Collect only non-empty statuses
    statuses = [
        get_chat_status(),
        get_vote_status(),
        get_thought_status(),
        get_tts_status(),
    ]
    parts.extend(s for s in statuses if s)
    # Add active tools status
    tools = _get_tool_statuses()
    if tools:
        parts.append("\nTools Status:")
        parts.extend(
            f"- {name}: last used {stats['last_used']}, "
            f"calls: {stats['call_count']} "
            f"({stats['success_count']} ok, {stats['error_count']} err)"
            for name, stats in tools.items()
        )
    return "\n".join(parts) if parts else ""
