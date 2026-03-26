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


def create_simple_agent():
    """Create a simple tool calling agent with pretty printing."""

    # Get LLM
    llm = get_llm_chain()

    # Define tools
    tools = [get_current_temperature]

    # Bind tools to LLM
    llm_with_tools = llm.bind_tools(tools)

    prompt: ChatPromptTemplate = ChatPromptTemplate.from_messages(
        [
            ("system", "You are a helpful assistant. Use tools when needed."),
            ("human", "{input}"),
            ("placeholder", "{agent_scratchpad}"),
        ]
    )
    ae = AgentExecutor(agent=llm_with_tools, tools=tools, max_iterations=10)
    # Run agent
    # result = llm_with_tools.invoke(
    #     prompt.format(input="What wheather parizz")
    # )
    # result = ae.run(prompt.format(input="What wheather parizz"))
    result = ae.invoke(prompt.format(input="What wheather parizz"))
    print("\n=== Agent Result ===")
    print(result)
    print("Parsing and running")
    parser = ToolsAgentOutputParser(name="tool_calls")
    parsed = parser.invoke(result)
    print("\n=== Parsed Result ===")
    print(parsed)

    ae._perform_agent_action(
        {"get_current_temperature": get_current_temperature},
        color_mapping=get_color_mapping(
            [tool.name for tool in ae.tools],
            excluded_colors=["green"],
        ),
        agent_action=parsed[0],
    )


if __name__ == "__main__":
    create_simple_agent()
