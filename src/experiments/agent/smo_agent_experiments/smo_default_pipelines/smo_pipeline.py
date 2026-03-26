"""

BAD AI GENERATED
NON TESTED
DONT USE

Simple smolagents pipeline approach experiment.

Core concept:
1. BasePipelineStage processes events and can pass data to next stage
2. Main pipeline has stages for analyzing input -> selecting tools -> executing actions
3. Single LLM instance shared between stages for efficiency

Basic workflow:
1. Event triggers pipeline
2. Analyzer stage determines event type and context
3. Tool selector stage chooses relevant tool group
4. Action executor stage runs selected tools
"""

import asyncio
import os
import re
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence
from warnings import deprecated

from smolagents import LiteLLMModel, tool
from smolagents.agents import ToolCallingAgent

if __name__ == "__main__":  # add module imports for this one-file testing
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )

from agent.llm_clients.smo_clients import get_smo_llm
from agent.tools.minecraft_tools import agent_action, minecraft_command
from agent.tools.tools import speak

# Global tools registry - sorted by category
TOOL_GROUPS = {
    "minecraft": [agent_action, minecraft_command],
    "voice": [speak],
}

# Initialize LLM
model = get_smo_llm()


@dataclass
class PipelineContext:
    """Shared context passed between pipeline stages"""

    raw_event: Dict
    event_type: str = ""
    selected_tools: List[str] = None
    action_results: List[str] = None


class BasePipelineStage:
    """Base class for pipeline stages"""

    def __init__(self, model=None):
        self.model = model

    async def process(self, context: PipelineContext) -> PipelineContext:
        """Process the context and return updated version"""
        raise NotImplementedError


class EventAnalyzer(BasePipelineStage):
    """First stage: Analyzes incoming event to determine type and relevance"""

    async def process(self, context: PipelineContext) -> PipelineContext:
        event = context.raw_event

        # Simple event type detection
        if event.get("type") == "kill" or event.get("type") == "death":
            context.event_type = "game_event"
        elif event.get("msg"):
            context.event_type = "chat_message"
        else:
            context.event_type = "other"

        return context


class ToolSelector(BasePipelineStage):
    """Second stage: Selects relevant tool group based on event type"""

    async def process(self, context: PipelineContext) -> PipelineContext:
        if context.event_type == "game_event":
            context.selected_tools = TOOL_GROUPS["minecraft"] + TOOL_GROUPS["voice"]
        elif context.event_type == "chat_message":
            context.selected_tools = TOOL_GROUPS["voice"] + TOOL_GROUPS["minecraft"]
        else:
            context.selected_tools = TOOL_GROUPS["voice"]

        return context


class ActionExecutor(BasePipelineStage):
    """Final stage: Executes actions using selected tools"""

    async def process(self, context: PipelineContext) -> PipelineContext:
        if not context.selected_tools:
            return context

        agent = ToolCallingAgent(tools=context.selected_tools, model=self.model)

        # Generate prompt based on event type
        if context.event_type == "game_event":
            prompt = f"Handle game event: {str(context.raw_event)}"
        elif context.event_type == "chat_message":
            prompt = f"Respond to chat message: {str(context.raw_event)}"
        else:
            prompt = f"Process event: {str(context.raw_event)}"

        result = agent.run(prompt)
        context.action_results = [result]

        return context


@deprecated
class Pipeline:
    """Main pipeline that coordinates stages"""

    def __init__(self, model):
        self.stages = [EventAnalyzer(model), ToolSelector(model), ActionExecutor(model)]

    async def process_event(self, event: Dict) -> PipelineContext:
        context = PipelineContext(raw_event=event)

        for stage in self.stages:
            context = await stage.process(context)

        return context


async def test_pipeline():
    """Test the pipeline with example events"""
    pipeline = Pipeline(model)

    # Test events
    events = [
        {"type": "kill", "user": "TestPlayer", "happiness_score": 1},
        {"msg": "hello bot", "user": "ChatUser", "server": "test"},
    ]

    for event in events:
        print(f"\nProcessing event: {event}")
        result = await pipeline.process_event(event)
        print(f"Pipeline results: {result}")


if __name__ == "__main__":
    asyncio.run(test_pipeline())
