import os
import sys
from typing import Annotated, Dict, List, TypedDict
from uuid import UUID

import faiss
from langchain_community.chat_models import ChatOpenAI
from langchain_community.docstore import InMemoryDocstore
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.runnables import RunnableLambda, RunnablePassthrough
from langchain_core.utils.function_calling import convert_to_openai_function
from langchain_openai import ChatOpenAI
from langgraph.graph import END, Graph, StateGraph

if __name__ == "__main__":  # add module imports for this one-file testing
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )

from agent.llm_clients.lc_clients import get_embeddings_model, get_llm_chain
from config_schema.general import get_secret
from data_schema.structure_templates import CTX_SWARM_EMPTY
from utils.string_helper import fix_line_splitters

llm = get_llm_chain()
embeddings = get_embeddings_model()

# Initialize vectorstore
embedding_size = 1024
index = faiss.IndexFlatL2(embedding_size)
vectorstore = FAISS(embeddings.embed_query, index, InMemoryDocstore({}), {})


# State definition
class AgentState(TypedDict):
    messages: Annotated[List[BaseMessage], "Chat messages"]
    next_agent: Annotated[str, "Next agent to run"]
    context: Annotated[Dict, "Shared context"]


# Agent nodes
def chooser(state: AgentState) -> AgentState:
    """Choose next agent based on context"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are a task chooser that selects between Commander and Minecrafter agents.",
            ),
            MessagesPlaceholder(variable_name="messages"),
            (
                "human",
                "Based on the context, which agent should handle this next? Options: commander, minecrafter",
            ),
        ]
    )

    chain = prompt | llm
    response = chain.invoke({"messages": state["messages"]})

    state["next_agent"] = response.content.lower()
    return state


def commander(state: AgentState) -> AgentState:
    """Entertainment and community management agent"""
    prompt = ChatPromptTemplate.from_messages(
        [
            (
                "system",
                "You are the Commander agent focused on entertainment and community.",
            ),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    chain = prompt | llm
    response = chain.invoke({"messages": state["messages"]})

    state["messages"].append(response)
    return state


def minecrafter(state: AgentState) -> AgentState:
    """Minecraft gameplay agent"""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "You are the Minecrafter agent focused on gameplay decisions."),
            MessagesPlaceholder(variable_name="messages"),
        ]
    )

    chain = prompt | llm
    response = chain.invoke({"messages": state["messages"]})

    state["messages"].append(response)
    return state


# Build graph
def build_agent_graph(context: Dict = CTX_SWARM_EMPTY):
    # Create graph with state
    workflow = StateGraph(AgentState)

    # Add agent nodes
    workflow.add_node("chooser", chooser)
    workflow.add_node("commander", commander)
    workflow.add_node("minecrafter", minecrafter)

    # Add edges
    workflow.add_edge("chooser", "commander")
    workflow.add_edge("chooser", "minecrafter")
    workflow.add_edge("commander", "chooser")
    workflow.add_edge("minecrafter", "chooser")

    # Set entry point
    workflow.set_entry_point("chooser")

    # Compile
    graph = workflow.compile()

    return graph


if __name__ == "__main__":
    # Test graph
    graph = build_agent_graph()

    state = {"messages": [], "next_agent": "chooser", "context": CTX_SWARM_EMPTY}

    for output in graph.stream(state):
        print("Step: " + str(output).replace("\r\n", "\n").replace("\\n", "\n"))
        print(" ================ =============== =============== ")
