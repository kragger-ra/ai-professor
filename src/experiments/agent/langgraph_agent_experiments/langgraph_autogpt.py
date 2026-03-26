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

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )
    from data_schema.structure_templates import CTX_SWARM_EMPTY
    from utils.structure_helper import load_ctx_chat_sample

    # ctx_chat = load_ctx_chat_sample()  # fixed ctx chat

    ctx_swarm = CTX_SWARM_EMPTY.copy()
    ctx_swarm["ctx_chat"] = []
    ctx_chat = ctx_swarm["ctx_chat"]
    ctx_state = ctx_swarm["states"]
    load_ctx_chat_sample(realtime=True, new_ctx_chat=ctx_chat, add_time=10)


from agent.llm_clients.lc_clients import get_embeddings_model, get_llm_chain
from config_schema.general import get_secret
from data_schema.structure_templates import CTX_SWARM_EMPTY
from utils.string_helper import fix_line_splitters


class AgentState(TypedDict):
    messages: List[BaseMessage]
    next_steps: List[str]
    current_plan: str
    reasoning: str


def create_agent():
    """Create a simple AutoGPT-like agent using LangGraph"""

    # Initialize LLM
    llm = get_llm_chain()

    # Create system prompt
    base_prompt = """You are a helpful AI assistant that breaks down tasks into steps and executes them.
    You maintain a plan and reasoning about your actions.
    
    Current state of the world:
    {context}
    
    Current plan: {current_plan}
    Previous reasoning: {reasoning}
    
    Think about your next steps carefully."""

    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", base_prompt),
            MessagesPlaceholder(variable_name="messages"),
            ("human", "{input}"),
        ]
    )

    # Define nodes
    def think(state: AgentState) -> AgentState:
        """Process current state and update thinking"""
        messages = state["messages"]

        # Get context from chat history
        context = "\n".join([str(m.content) for m in messages[-5:] if m.content])

        result = llm.invoke(
            prompt.format(
                context=context,
                current_plan=state["current_plan"],
                reasoning=state["reasoning"],
                messages=messages,
                input="What should I do next?",
            )
        )

        # Update state with new thinking
        return {**state, "reasoning": result.content, "messages": messages + [result]}

    def plan(state: AgentState) -> AgentState:
        """Create or update plan based on current thinking"""
        next_steps = state["reasoning"].split("\n")
        return {
            **state,
            "next_steps": next_steps,
            "current_plan": f"Current steps:\n{state['reasoning']}",
        }

    # Create graph
    workflow = StateGraph(AgentState)

    # Add nodes
    workflow.add_node("think", think)
    workflow.add_node("plan", plan)

    # Add edges
    workflow.add_edge("think", "plan")
    workflow.add_edge("plan", END)

    # Set entry point
    workflow.set_entry_point("think")

    # Compile
    graph = workflow.compile()

    return graph


def run_agent(query: str):
    """Run the agent with an initial query"""

    # Create initial state
    initial_state: AgentState = {
        "messages": [],
        "next_steps": [],
        "current_plan": "",
        "reasoning": "",
    }

    # Create and run graph
    graph = create_agent()
    for output in graph.stream(initial_state):
        print("State update:", output)


if __name__ == "__main__":
    # Test the agent
    run_agent("Help me break down the task of cleaning my room")
