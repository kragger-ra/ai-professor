import time
from typing import Dict, Union

from agent.tools.tool_executor import format_tool_command
from config_schema.general import get_name
from data_schema.chat_structures import CtxEventBase, ToolCall
from utils.time_helper import eztime


def convert_to_chat_message(data: Union[Dict, str]) -> CtxEventBase:
    """Convert dictionary or string to CtxEventBase

    If string, it will be converted to a system message represents the current override directive
    """
    if isinstance(data, str):
        return CtxEventBase(
            msg=data,
            env="system",
            user="system",
            date=eztime(),  # tm from utils
            processing_timestamp=time.time_ns(),  # time ns
            type="directive",  # MessageType.SYSTEM
            additional_fields={"filter_results": {"acceptable": True}},
        )

    # Extract known fields
    known_fields = {"msg", "user", "date", "processing_timestamp", "type", "env"}
    base_fields = {
        "msg": data.get("msg", ""),
        "env": data.get("env", ""),
        "user": data.get("user", ""),
        "date": data.get("date", eztime()),
        "processing_timestamp": data.get("processing_timestamp", time.time_ns()),
        "type": data.get("type", "chat"),
    }

    # Collect additional fields
    additional_fields = {k: v for k, v in data.items() if k not in known_fields}

    return CtxEventBase(**base_fields, additional_fields=additional_fields)


def convert_tool_call_to_event(
    tool_name: str, args: Dict, tool_call_format: str = "command"
) -> CtxEventBase:
    """Convert tool call to CtxEventBase event

    Args:
        tool_name (str): The name of the tool
        args (Dict): Arguments passed to the tool

    Returns:
        CtxEventBase: Event representing the tool call
    """

    # action = AutoGPTAction(name=tool_name, args=args)
    return CtxEventBase(
        msg=None,  # format_action_for_display(action),
        user=get_name(),
        date=eztime(),
        processing_timestamp=time.time_ns(),
        type="tool_call",
        env="system",
        additional_fields={
            "self": True,
            "isEvent": True,
            "description": format_tool_command(
                tool_name, args, tool_call_format
            ),  # f" used tool call {tool_name} {str(args)}",
            "filter_results": {
                "acceptable": True,
            },
            "tool": tool_name,
            "args": args,
            "tool_call_format": tool_call_format,
        },
    )


def format_action_for_display(action: ToolCall) -> str:
    """Create a simple string representation of an AutoGPTAction for display/logging

    Args:
        action (AutoGPTAction): The action to format

    Returns:
        str: Human-readable string representing the action

    Examples:
        >>> action = AutoGPTAction(name="speak", args={"comment": "Hello", "emotion": "happy"})
        >>> format_action_for_display(action)
        'speak: Hello [happy]'

        >>> action = AutoGPTAction(name="minecraft_command", args={"command": "/kill player"})
        >>> format_action_for_display(action)
        'minecraft_command: /kill player'

        >>> action = AutoGPTAction(name="thoughts", args={"summary": "Planning next move"})
        >>> format_action_for_display(action)
        'thinking: Planning next move'
    """
    if action.name == "thoughts":
        # Get the thought summary if available, otherwise use full args
        thought_text = action.args.get("summary", str(action.args))
        return f"thinking *{thought_text}*"
        # return "changed thoughts"

    # For speak actions, combine comment and emotion
    elif action.name == "speak":
        comment = action.args.get("comment", "")
        emotion = action.args.get("emotion", "")
        if emotion:
            return f"tool speak with comment {comment} *{emotion}*"
        return f"tool speak with comment {comment}"

    # For other actions, try to extract the main argument or fall back to full args
    else:
        # Common argument names that represent the main action content
        # main_arg_names = ["command", "msg", "comment", "text"]
        main_arg_names = list(action.args.keys()).copy()
        # Try to find the main argument
        for arg_name in main_arg_names:
            if arg_name in action.args:
                return f"== YOU USED TOOL {str(action.name)} with args ({str(action.args[arg_name])})=="


def convert_autogpt_action_to_event(action: ToolCall) -> CtxEventBase:
    """Convert AutoGPTAction to CtxEventBase event

    Args:
        action (AutoGPTAction): The AutoGPT action to convert

    Returns:
        CtxEventBase: Event representing the action
    """
    # Format the action into a display string for the message
    display_msg = format_action_for_display(action)

    # Handle thoughts separately since they don't represent direct actions
    if action.name == "thoughts":
        return CtxEventBase(
            msg=display_msg,
            user=get_name(),
            env="system",
            date=eztime(),
            processing_timestamp=time.time_ns(),
            type="thought",
            additional_fields={
                "self": True,
                "description": display_msg,
                "tool": action.name,
                "args": action.args,
            },
        )

    # For other tool actions
    return CtxEventBase(
        msg=display_msg,
        user=get_name(),
        date=eztime(),
        processing_timestamp=time.time_ns(),
        type="tool_call",
        env="system",
        additional_fields={
            "self": True,
            "description": display_msg,
            "tool": action.name,
            "args": action.args,
        },
    )
