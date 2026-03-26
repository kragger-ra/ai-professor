"""
Planner Agent - Strategic decision maker for multi-agent system

Returns high-level plans and pipeline selection based on current situation
"""

import time
import traceback
from typing import Optional

from agent.base_agent import BaseAgent
from agent.llm_clients.lc_clients import get_llm_chain
from agent.prompt_generation.prompt_constructor import (
    SmartEventWaiter,
    get_game_status,
    get_users_info,
)
from config_schema.general import get_name
from data_flow.ctx_handler import CtxHandler
from data_flow.ctx_host import CtxHost
from data_schema.chat_structures import CtxEventBase, default_event_check
from data_schema.ctx_structures import CtxSwarmType
from data_schema.tool_structures import ToolBankType
from utils.debug import print_messages
from utils.format_helper import format_events_with_roles


class PlannerAgent(BaseAgent):
    """
    Planner agent - Strategic decision maker

    Analyzes situation and returns:
    - Description of current situation
    - Criticism of current approach
    - Short-term plan
    - Pipeline selection (reaction/game/battle)
    """

    def __init__(
        self,
        ctx_swarm: CtxSwarmType,
        ctx_handler: Optional[CtxHandler] = None,
        ctx_host: Optional[CtxHost] = None,
        tool_bank: Optional[ToolBankType] = None,
    ):
        """Initialize planner agent"""
        super().__init__(ctx_swarm, ctx_handler)
        if ctx_handler is None:
            self.ctx_handler = CtxHandler(ctx_swarm)
        else:
            self.ctx_handler = ctx_handler

        # Lightweight LLM for planning
        self.llm = get_llm_chain()
        self.self_name = get_name()

        if tool_bank is not None:
            self.tool_bank = tool_bank
        else:
            from agent.tools import tools_config

            self.tool_bank = tools_config.init_tools_module(
                ctx_swarm, self.ctx_handler, new_llm=self.llm
            )

        if ctx_host is None:
            self.ctx_host = CtxHost(ctx_handler, tool_bank=self.tool_bank)
        else:
            self.ctx_host = ctx_host

        self.initialized = True
        self.last_plan = None

    def plan(self, trigger_event: Optional[CtxEventBase] = None) -> dict:
        """
        Generate strategic plan based on current situation

        Args:
            trigger_event: Optional triggering event

        Returns:
            dict with keys: description, criticism, plan, pipelines
        """
        if not self.initialized:
            return {
                "description": "Not initialized",
                "criticism": "Agent not ready",
                "plan": "Wait for initialization",
                "pipelines": ["reaction"],
            }

        # Build planning prompt
        system_prompt = """You are a strategic planner for an AI agent. Analyze the situation and provide:

1. Description: Brief overview of current situation (2-3 sentences)
2. Criticism: What could be improved in current approach (1-2 sentences)
3. Plan: Short-term focus areas (3-5 bullet points, NOT detailed steps)
4. Choose pipeline: Select one or more from:
   - reaction (texting, answering questions, casual interaction)
   - game (complex game actions, exploration, building)
   - battle (combat actions with warrior-like responses)

Output format:
Description:
[situation description]

Criticism:
[constructive criticism]

Plan:
- [focus area 1]
- [focus area 2]
- [focus area 3]

Choose pipeline:
[pipeline1, pipeline2, ...]
"""

        # Get context
        messages_dicts, mentioned_users = format_events_with_roles(
            self.ctx_handler.get_ctx_chat(validate=True, dict_format=True, limit=30),
            trigger_event_id=(
                trigger_event.processing_timestamp if trigger_event else None
            ),
            return_mentioned_users=True,
            tool_call_format="text",
        )

        # Get users and game status
        users_info = get_users_info(
            ctx_swarm=self.ctx_swarm, chat_users=mentioned_users
        )
        game_status = get_game_status()

        # Build context
        situation_context = f"""# Current Situation:
## Game Status:
{game_status}

## Nearby Users & Players:
{users_info}

## Recent Events:
"""

        # Build messages
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": situation_context},
        ]

        # Add recent events
        if messages_dicts:
            messages.extend(messages_dicts[-10:])  # Last 10 events for context

        messages.append(
            {
                "role": "user",
                "content": "Based on the above situation, provide your strategic analysis and plan.",
            }
        )

        print("\n[PLANNER] Generating strategic plan...")
        print_messages(messages)

        # Generate plan
        response_text = ""
        try:
            # disabling for planner
            # smart_event_waiter = SmartEventWaiter(ctx_handler=self.ctx_handler)

            for chunk in self.llm.stream(messages):
                chunk_text = chunk.content if hasattr(chunk, "content") else str(chunk)
                print(chunk_text, end="", flush=True)
                response_text += chunk_text

                # if smart_event_waiter.check():
                #     print("\n[PLANNER] Interrupted by event")
                #     break

            print()
            # smart_event_waiter.shutdown()

        except Exception as e:
            print(f"\n[PLANNER] Error during streaming: {e}")
            response = self.llm.invoke(messages)
            response_text = (
                response.content if hasattr(response, "content") else str(response)
            )
            print(response_text)

        # Parse response
        plan_data = self._parse_plan_response(response_text)
        self.last_plan = plan_data

        print(f"\n[PLANNER] Plan generated: {plan_data['pipelines']}")
        return plan_data

    def _parse_plan_response(self, response: str) -> dict:
        """Parse the LLM response into structured plan"""
        lines = response.strip().split("\n")

        result = {
            "description": "",
            "criticism": "",
            "plan": "",
            "pipelines": ["reaction"],  # Default fallback
        }

        current_section = None

        for line in lines:
            line_lower = line.lower().strip()

            if line_lower.startswith("description:"):
                current_section = "description"
                line = line[len("description:") :].strip()
            elif line_lower.startswith("criticism:"):
                current_section = "criticism"
                line = line[len("criticism:") :].strip()
            elif line_lower.startswith("plan:"):
                current_section = "plan"
                line = line[len("plan:") :].strip()
            elif line_lower.startswith("choose pipeline:"):
                current_section = "pipelines"
                line = line[len("choose pipeline:") :].strip()

            if current_section and line.strip():
                if current_section == "pipelines":
                    # Parse pipeline list
                    pipelines = []
                    for pipeline in ["reaction", "game", "battle"]:
                        if pipeline in line_lower:
                            pipelines.append(pipeline)
                    if pipelines:
                        result["pipelines"] = pipelines
                else:
                    if result[current_section]:
                        result[current_section] += "\n" + line
                    else:
                        result[current_section] = line

        return result

    def step(self):
        """Run a single planning iteration"""
        try:
            print("[PLANNER] Starting planner (without trigger)...")

            # Get latest event for planner
            # event: CtxEventBase = self.ctx_handler.get_ctx_chat(limit=1)
            # we DONT need trigger event for planner!!!

            plan = self.plan()
            print("\n[PLANNER] === STRATEGIC PLAN ===")
            print(f"Description: {plan['description']}")
            print(f"Criticism: {plan['criticism']}")
            print(f"Plan: {plan['plan']}")
            print(f"Pipelines: {plan['pipelines']}")
            print("[PLANNER] === END PLAN ===\n")

        except Exception as e:
            print(f"[PLANNER] Error: {e}")
            traceback.print_exc()

    def run(self):
        """Main loop"""
        print("[PLANNER] Starting...")
        self.running = True

        while self.ctx_swarm["env"]["actived"] and self.running:
            self.step()

    def stop(self):
        """Stop the agent"""
        self.running = False
        print("[PLANNER] Stopped")

    def cleanup(self):
        """Clean up resources"""
        if self.running:
            self.stop()
        if hasattr(self, "llm"):
            del self.llm
