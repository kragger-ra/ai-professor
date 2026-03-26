"""
Vision tools for the agent

Uses LLM client and vision helper methods for clean implementation.
"""

import traceback
from typing import Any, Dict

from langchain_core.messages import HumanMessage, SystemMessage

from agent.llm_clients.lc_clients import get_llm_chain
from agent.tools.control_tools import (
    _add_tool_error_log,
    _add_tool_result_log,
    _add_tool_run_log,
)
from config_schema.general import get_secret
from utils.prompt_helper import prompt_load
from utils.vision_helper import get_actual_frame


def screenshot(prompt: str = None) -> Dict[str, Any]:
    """Makes a screenshot, analyzes it and responses to a given prompt.

    Args:
        prompt:
            Str, what do you want to focus or to check in this
            screen capture?
    """
    tool_name = "screenshot"
    call_id = _add_tool_run_log(tool_name, {"prompt": prompt})

    try:
        vlm_name = get_secret("VISION_LLM_MODEL_NAME")
        if not vlm_name or vlm_name == "NONE":
            raise ValueError(
                "VISION_LLM_MODEL_NAME is not set in environment, screenshot tool must be disabled. Why it is running?"
            )
        # Get frame using vision helper
        frame_data = get_actual_frame()

        if not frame_data:
            error_msg = (
                "Failed to capture frame. "
                "Check if OBS is running with websocket enabled."
            )
            _add_tool_error_log(tool_name, {"returned": error_msg, "call_id": call_id})
            return {"status": "error", "error": error_msg}

        if not prompt:
            prompt = "Shortly analyze the situation on this screenshot."

        # Build messages using prompt from resources
        system_content = prompt_load("instructions", "captioner")
        messages = [
            SystemMessage(content=system_content),
            HumanMessage(
                content=[
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": frame_data}},
                ]
            ),
        ]

        # Invoke LLM
        llm = get_llm_chain(vlm_name)
        response = llm.invoke(messages)
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
