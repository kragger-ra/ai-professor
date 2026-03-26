"""BEST STREAMING TOOL CALLING APPROACH"""

import os
from typing import Any, Dict, List, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool
from langchain_litellm import ChatLiteLLM


class ChatLiteLLMCreds(TypedDict, total=False):
    model: str
    api_base: str
    api_key: str
    max_tokens: int


def get_secret(var):
    return os.getenv(var)


def get_llm_chain(model_name: str = None) -> BaseChatModel:
    """Get ChatLiteLLM instance with credentials from .env or defaults."""
    if model_name is None:
        model_name = get_secret("CORE_LLM_MODEL_NAME")

    core_llm_api_base = get_secret("CORE_LLM_API_BASE")
    creds = ChatLiteLLMCreds(model=model_name)

    max_tokens = get_secret("CORE_LLM_MAX_TOKENS")
    if max_tokens and core_llm_api_base != "NONE":
        creds["max_tokens"] = int(max_tokens)
    if core_llm_api_base and core_llm_api_base != "NONE":
        creds["api_base"] = core_llm_api_base

    return ChatLiteLLM(**creds)


@tool
def get_current_temperature(city: str) -> str:
    """Get the current temperature for a city."""
    temps = {"london": "15°C", "paris": "18°C", "tokyo": "22°C", "new york": "12°C"}
    print(f"\n[TOOL EXECUTED: get_current_temperature('{city}')]")
    return temps.get(city.lower(), "Unknown city")


def execute_streaming(user_input: str, tools: list):
    """Stream tokens and execute tools immediately when detected."""
    import json

    llm = get_llm_chain().bind_tools(tools)
    tool_map = {t.name: t for t in tools}
    tool_calls_data = []
    output = ""

    for chunk in llm.stream([{"role": "user", "content": user_input}]):
        # Print EVERY token immediately
        if chunk.content:
            output += chunk.content
            print(chunk.content, end="", flush=True)

        # Execute tools IMMEDIATELY when complete
        if hasattr(chunk, "tool_call_chunks") and chunk.tool_call_chunks:
            for tc_chunk in chunk.tool_call_chunks:
                tc_index = tc_chunk.get("index", 0)

                # Extend list if needed
                while len(tool_calls_data) <= tc_index:
                    tool_calls_data.append({"name": "", "args": ""})

                # Accumulate
                if tc_chunk.get("name"):
                    tool_calls_data[tc_index]["name"] = tc_chunk["name"]
                if tc_chunk.get("args"):
                    tool_calls_data[tc_index]["args"] += tc_chunk["args"]

                # Try to execute immediately if args look complete
                tc_data = tool_calls_data[tc_index]
                if tc_data["name"] and tc_data["args"].endswith("}"):
                    try:
                        args = json.loads(tc_data["args"])
                        if tc_data["name"] in tool_map and "executed" not in tc_data:
                            print(
                                f"\n🔧 Executing: {tc_data['name']}{args}", flush=True
                            )
                            result = tool_map[tc_data["name"]].invoke(args)
                            print(f"✅ Result: {result}\n", flush=True)
                            tc_data["executed"] = True
                    except:
                        pass  # Still accumulating
    return output
    print()


if __name__ == "__main__":
    tools = [get_current_temperature]
    print(
        "Result:",
        execute_streaming(
            "What is the current temperature in Paris and Tokyo? How are you?", tools
        ),
    )
