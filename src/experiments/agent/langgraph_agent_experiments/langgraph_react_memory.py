# First we initialize the model we want to use.

import os
import sys
from typing import Any, Dict, List, Literal, Optional

from langchain_community.embeddings import OpenAIEmbeddings
from langchain_core.messages import BaseMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, Graph, StateGraph
from langgraph.prebuilt import create_react_agent

# from langchain_openai import ChatOpenAI as BaseChatOpenAI


if __name__ == "__main__":  # add module imports for this one-file testing
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )


from agent.llm_clients.lc_chatopenai_patch import ChatOpenAI
from agent.llm_clients.lc_clients import get_embeddings_model, get_llm_chain
from config_schema.general import get_secret
from data_schema.structure_templates import CTX_SWARM_EMPTY
from utils.string_helper import fix_line_splitters

model = get_llm_chain()
embeddings = get_embeddings_model()


# For this tutorial we will use custom tool that returns pre-defined values for weather in two cities (NYC & SF)

from langchain_core.tools import tool


@tool
def get_weather(city: Literal["nyc", "sf"]):
    """Use this to get weather information."""
    if city == "nyc":
        return "It might be cloudy in nyc"
    elif city == "sf":
        return "It's always sunny in sf"
    else:
        raise AssertionError("Unknown city")


tools = [get_weather]

# We can add "chat memory" to the graph with LangGraph's checkpointer
# to retain the chat context between interactions

memory = MemorySaver()

# Define the graph

graph = create_react_agent(model, tools=tools, checkpointer=memory)


def print_stream(stream):
    for s in stream:
        message = s["messages"][-1]
        if isinstance(message, tuple):
            print(message)
        else:
            message.pretty_print()


config = {"configurable": {"thread_id": "1"}}
inputs = {"messages": [("user", "What's the weather in NYC?")]}


print_stream(graph.stream(inputs, config=config, stream_mode="values"))


inputs = {"messages": [("user", "What's it known for?")]}
print_stream(graph.stream(inputs, config=config, stream_mode="values"))
