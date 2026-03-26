"""
Fun tools

Uses LLM client
"""

import traceback
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm_clients.lc_clients import get_llm_chain

# from agent.tools import tools_config
from agent.tools.control_tools import (
    _add_tool_error_log,
    _add_tool_result_log,
    _add_tool_run_log,
)
from config_schema.general import get_secret
from utils.prompt_helper import prompt_load

# llm for micro-tasks, maybe should add separate for env
# tools_config.llm_model not work here
simple_llm_name = get_secret("SIMPLE_LLM_MODEL_NAME")
if simple_llm_name and simple_llm_name != "NONE":
    simple_llm = get_llm_chain(simple_llm_name)
else:  # fallback to main model
    simple_llm = get_llm_chain()


def analyze_nickname(nickname: str) -> Dict[str, Any]:
    """Analyzes a nickname!

    Args:
        nickname:
            str, nickame to analyze
    """
    tool_name = "analyze_nickname"
    call_id = _add_tool_run_log(tool_name, {"prompt": nickname})

    try:
        task_content = prompt_load(
            "instructions", "nickname_analyzer_task", {"nick": nickname}
        )
        system_content = prompt_load("instructions", "nickname_analyzer_system")
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(content=task_content),
        ]

        # Invoke LLM
        response = simple_llm.invoke(messages)
        if hasattr(response, "content"):
            description = response.content
        else:
            description = str(response)

        _add_tool_result_log(tool_name, {"returned": description, "call_id": call_id})
        return description

    except Exception as e:
        error_msg = f"Vision tool error: {str(e)}"
        print(error_msg)
        traceback.print_exc()
        _add_tool_error_log(tool_name, {"returned": error_msg, "call_id": call_id})
        return {"status": "error", "error": error_msg}


def generate_joke(joke_topic: str) -> str:
    """Generate joke for generating. Power-consuming tool.
    Args:
        joke_topic: Topic to generate joke
    Returns:
        Joke string (after ~5 secs of generating).
    """
    call_id = _add_tool_run_log("generate_joke", {"joke_topic": joke_topic})
    try:
        # TODO
        generated = "UNIMPLEMENTED"
        speech_run_info = generated
        result = str(
            {"generated_joke": generated, "speech_function_returned": speech_run_info}
        )
        _add_tool_result_log("generate_joke", {"returned": result, "call_id": call_id})
        return result
    except Exception as e:
        _add_tool_error_log("generate_joke", {"returned": str(e), "call_id": call_id})
        return str(e)
