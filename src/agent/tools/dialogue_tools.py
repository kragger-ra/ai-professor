"""
Dialog agent toolkit

This tool sub-module contains tools for managing dialog agents.

TODO implement
Should have database interactions to save, retrieve dialog, user summary, etc.

"""

import traceback

from agent.tools import tools_config
from agent.tools.control_tools import (
    _add_tool_error_log,
    _add_tool_result_log,
    _add_tool_run_log,
)
from data_schema.chat_structures import UserData
from utils.format_helper import get_user_mentions

queue_send = tools_config.queue_send
db = tools_config.db
history = tools_config.inner_dialogue_history
llm = tools_config.llm_model


def like(user: str) -> bool:
    """Increase user's rank if is interesting for you and you like him

    Args:
        user: The username of the user to like.
    """
    user_id = tools_config.db.get_user_id(user)
    if user_id:
        rank = tools_config.db.get_user_rank(user_id)
        success = tools_config.db.set_user_rank(user_id, new_rank=rank + 1)
        call_id = _add_tool_run_log("like", {"user": user})
        if success:
            _add_tool_result_log(call_id, {"returned": success, "call_id": call_id})
            return success
    return False


def dislike(user: str) -> bool:
    """Decrease user's rank if is boring for you and you hate him

    Args:
        user: The username of the user to dislike.
    """
    call_id = _add_tool_run_log("dislike", {"user": user})
    user_id = tools_config.db.get_user_id(user)
    if user_id:
        rank = tools_config.db.get_user_rank(user_id)
        success = tools_config.db.set_user_rank(user_id, new_rank=rank - 1)
        if success:
            _add_tool_result_log(call_id, {"returned": success, "call_id": call_id})
            return success
    return False


def get_users_summary(users: list[str]) -> list[str]:
    return [get_user_summary(user) for user in users]


def get_user_summary(user: str) -> str:
    user_id = tools_config.db.get_user_id(user)
    if user_id:
        summary = tools_config.db.get_user_summary(user_id)
        if summary:
            return summary
    return ""


def _get_user_data(user: str) -> UserData:
    return tools_config.db.get_user_data(user)


def _save_user_summary(user: str, summary: str) -> bool:
    mentioned = get_user_mentions(tools_config.ctx_swarm["ctx_chat"], user)
    if mentioned:
        event = mentioned["binded_events"][-1]
        user_id = tools_config.db.get_or_create_user(event)
        if user_id:
            return tools_config.db.set_user_summary(user_id, summary)
    return False


def _get_dialogue(user: str) -> list[dict]:
    user_id = tools_config.db.get_user_id(user)
    if user_id:
        dialogue = tools_config.db.get_relevant_diag(user_id)
        if dialogue:
            return dialogue
    return []


def dialogue_step(user: str, message: str) -> str:
    """Process a dialogue step."""
    user_id = tools_config.db.get_user_id(user)
    if not user_id:
        return "Error: User not found"
    dialogue = _get_dialogue(user)
    if not dialogue:
        print("Error: No dialogue found")
    dialogue.append({"role": "user", "content": message})
    # TODO rework, make get prompt tools, use status tools to construct prompt
    dialogue.insert(
        0,
        {
            "role": "system",
            "content": "You are LOL TEST clown. Always answer AHAHAHAHHAHAH",
        },
    )

    try:
        # Process the message
        response = llm.invoke(dialogue)
        # Save the message
        # db.add_diags(user_id, message, response)
        # Add the message to the dialogue history
        history.append((user, message, response))
        return response
    except Exception as e:
        _add_tool_error_log("dialogue_step", e, traceback.format_exc())
        return "Error: Failed to process message"


# NEED TO BE MOVED INTO AGENT, THIS FUNCTION NOT HERE
def start_dialogue_agent(user: str):
    """Start a new dialogue session."""
    pass
    # simpliest dialogue agent realisation
    # with trigger for awaiting answer
    # in the end of dialog prompt the llm to give answer about a player
