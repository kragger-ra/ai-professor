"""

old Autogpt approach:
- src/agent/
  - suprevisor_agent.py - Main agent implementation using AutoGPT
  - autogpt/ - Core AutoGPT implementation
    - agent.py - Main agent loop and execution logic
    - prompt.py - Custom prompt management
    - prompt_generator.py - Custom prompt generation with state tracking
    - output_parser.py - JSON output parsing
  - tools/tools.py - Tool definitions (voice, chat, minecraft controls)
  - tools/*.py - Other tools
  - rag.py - RAG system for knowledge retrieval
  - monologue_agent.py - Voice speaking handling

Maximum simplify the logic and implement simple smolagents approach based on this autogpt approach.
Tools you can use from existing, search for codebase for convert to smolagent format tools

Smolagents is a framework for agents.
You can see some approaches for experiments in src/experiments/agent/smo*.py

(DO NOT REMOVE UPPER TEXT)


Simple implementation of smooth agents approach with single agent.
This is a test setup trying to minimize token context and tool complexity.

ISSUES:
not added system status for tools, for example executor agent (called resources in old prompt constructors).
not added game state
trigger not work (when waits for timeout its forever)
not added personality propmpt

"""

import asyncio
import logging
import os
import sys
from typing import Optional

from smolagents import LiteLLMModel, ToolCallingAgent, tool

# Add src to path for imports
if __name__ == "__main__":
    module_dir = os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    )
    sys.path.insert(0, module_dir)

import agent.tools.tools as tools_class
from agent.llm_clients.smo_clients import get_smo_llm
from config_schema.general import get_secret
from data_flow.ctx_handler import CtxHandler
from data_schema.event_convert import convert_to_chat_message
from data_schema.structure_templates import CTX_SWARM_EMPTY, create_ctx_swarm
from utils.format_helper import format_events_for_llm

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Convert existing tools to smolagents format
tools_class.tool = tool
tools_class.ctx_swarm = CTX_SWARM_EMPTY
raw_tools = tools_class.AGENT_SUPERVISOR_TOOLS_RAW
tools = []
for raw_tool in raw_tools:
    tool_item = tool(raw_tool)
    logger.info(f"Converted tool: {tool_item.name}")
    tools.append(tool_item)


class ChatAgent:
    """Simple chat agent focused on responding to messages."""

    def __init__(self, ctx_swarm: dict):
        self.ctx_swarm = ctx_swarm
        tools_class.ctx_swarm = ctx_swarm  # Update tools context
        self.handler = CtxHandler(ctx_swarm)

        # Initialize LLM
        self.model = get_smo_llm()
        self.running = False
        # Initialize agent with converted tools
        self.agent = ToolCallingAgent(
            tools=tools,
            model=self.model,
        )

    async def wait_for_trigger(self, timeout: float = 15.0) -> Optional[dict]:
        """Wait for message that should trigger agent response."""

        #  (this shit not work)
        def check_message(msg):
            # Convert to standard format
            event = convert_to_chat_message(msg)

            # Ignore self messages
            if event.additional_fields.get("self", False):
                return False

            # React to chat messages and game events
            if event.type in ["chat", "death", "kill"]:
                if event.type == "chat" and not event.user:
                    return False
                return True

            return False

        try:
            event = await asyncio.wait_for(
                self.handler.wait_for(check_message), timeout
            )
            return event
        except asyncio.TimeoutError:
            return None

    def stop(self):
        self.running = False

    def is_running(self):
        return self.running

    async def run_async(self):
        """Main agent loop."""
        logger.info("Starting chat agent")
        self.running = True
        while self.ctx_swarm["env"]["actived"] and self.running:
            # Wait for trigger event (this shit not work)
            # trigger = await self.wait_for_trigger()
            # if not trigger:
            #     continue

            # Format context for LLM
            context = format_events_for_llm(self.ctx_swarm["ctx_chat"])
            prompt = f"""You are NetTyan, a virtual streamer.
            Current chat context:
            {context}
            
            What should you do in response? Reply with commands."""

            # Generate response using agent
            try:
                response = self.agent.run(prompt)
                logger.debug(f"Agent response: {response}")
            except Exception as e:
                logger.error(f"Error running agent: {e}")
                continue

    def run(self):
        asyncio.run(self.run_async())


def main():
    """Run the agent."""
    # Initialize context
    ctx_swarm = create_ctx_swarm()
    ctx_swarm["env"]["actived"] = True

    # Create and run agent
    agent = ChatAgent(ctx_swarm)
    agent.run()


if __name__ == "__main__":
    main()
