import os
from typing import Any, Dict, List, TypedDict

import langchain
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain.agents.output_parsers.tools import ToolsAgentOutputParser
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_core.utils.input import get_color_mapping
from langchain_litellm import ChatLiteLLM
from langchain_openai import OpenAIEmbeddings


class ChatLiteLLMCreds(TypedDict, total=False):
    model: str
    api_base: str
    api_key: str
    max_tokens: int


def get_secret(var):
    return os.getenv(var)


def get_llm_chain(model_name: str = None) -> BaseChatModel:
    """Get ChatLiteLLM instance with credentials from .env or defaults.
    Args:
        model_name:
            Str, model name to use. If None, get from .env CORE_LLM_MODEL_NAME.
    Returns:
        ChatLiteLLM instance.
    """

    if model_name is None:
        model_name = get_secret("CORE_LLM_MODEL_NAME")

    # proxies moved to .env, just configure this vars
    # proxy = get_secret("proxy")
    # if proxy and proxy != "NONE":
    #     environ["HTTP_PROXY"] = proxy
    #     environ["HTTPS_PROXY"] = proxy
    #     environ["NO_PROXY"] = "localhost,127.0.0.1,::1,0.0.0.0"
    core_llm_api_base = get_secret("CORE_LLM_API_BASE")
    creds = ChatLiteLLMCreds(
        model=model_name,
        # api_key=get_secret("CORE_LLM_API_KEY"),
        # stored in env, loaded by litellm
        # max_tokens=20000,  # >10k on start, 6k
    )
    max_tokens = get_secret("CORE_LLM_MAX_TOKENS")
    if max_tokens and core_llm_api_base != "NONE":
        creds["max_tokens"] = int(max_tokens)
    if core_llm_api_base and core_llm_api_base != "NONE":
        creds["api_base"] = core_llm_api_base
    # else chosen automatically from env / litellm defaults

    # print("[lc_clients.py DEBUG] LLM Model full creds =", creds)

    return ChatLiteLLM(**creds)


# Simple tool definition
@tool
def get_current_temperature(city: str) -> str:
    """Get the current temperature for a city."""
    # Mock implementation
    temps = {"london": "15°C", "paris": "18°C", "tokyo": "22°C", "new york": "12°C"}
    print("TOOL RUN [!!!!!!]")
    return temps.get(city.lower(), "Unknown city")


def execute_single_pass(user_input: str, tools: list):
    """Ultra-simple: invoke LLM, execute tools, done."""
    llm = get_llm_chain().bind_tools(tools)

    # Get LLM response with tool calls
    ai_msg = llm.invoke([{"role": "user", "content": user_input}])

    # Execute all tools immediately
    results = []
    if ai_msg.tool_calls:
        tool_map = {t.name: t for t in tools}
        for tc in ai_msg.tool_calls:
            results.append(tool_map[tc["name"]].invoke(tc["args"]))

    return results if results else ai_msg.content


if __name__ == "__main__":
    # Define tools
    tools = [get_current_temperature]
    # Run agent
    result = execute_single_pass(
        "What is the current temperature in Paris and tokyo?", tools
    )
    print("\n=== Agent Result ===")
    print(result)
