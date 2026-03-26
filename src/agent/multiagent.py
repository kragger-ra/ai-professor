"""
MULTI-AGENT WRAPPER

Wraps Multiple agents and rules overall priority
"""

import os
import sys
import threading
import traceback
from typing import Optional

from agent.base_agent import BaseAgent
from agent.core_agent import CoreAgent
from agent.llm_clients.lc_clients import get_llm_chain
from agent.multi.planner_agent import PlannerAgent
from agent.multi.reaction_agent import ReactionAgent
from agent.tools import tools_config
from data_flow.ctx_handler import CtxHandler
from data_flow.ctx_host import CtxHost
from data_schema.ctx_structures import CtxSwarmType

if __name__ == "__main__":
    module_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, module_dir)
    from data_schema.structure_templates import create_ctx_swarm


class MultiAgent(BaseAgent):
    """
    Multi-agent wrapper that coordinates ReactionAgent, PlannerAgent and CoreAgent.

    Pattern: Planner decides strategy -> 3 ReactionAgent iterations -> 1 CoreAgent iteration -> repeat
    """

    def __init__(
        self,
        ctx_swarm: CtxSwarmType,
        ctx_handler: Optional[CtxHandler] = None,
        ctx_host: Optional[CtxHost] = None,
    ):
        """
        Initialize multi-agent wrapper

        Args:
            ctx_swarm: Context swarm
            ctx_handler: Context handler (shared between agents)
        """
        super().__init__(ctx_swarm, ctx_handler)

        if ctx_handler is None:
            self.ctx_handler = CtxHandler(ctx_swarm)
        else:
            self.ctx_handler = ctx_handler

        reaction_iterations = 3
        self.llm = get_llm_chain()
        self.reaction_iterations = reaction_iterations

        tool_bank = tools_config.init_tools_module(
            ctx_swarm, self.ctx_handler, new_llm=self.llm
        )
        if ctx_host is None:
            self.ctx_host = CtxHost(ctx_handler, tool_bank=tool_bank)
        else:
            self.ctx_host = ctx_host
        standart_agentic_kwargs = {
            "ctx_swarm": ctx_swarm,
            "ctx_handler": self.ctx_handler,
            "ctx_host": self.ctx_host,
            "tool_bank": tool_bank,
        }
        print("[MULTI-AGENT] Initializing PlannerAgent...")
        self.planner_agent = PlannerAgent(**standart_agentic_kwargs)
        print("[MULTI-AGENT] Initializing CoreAgent...")
        self.core_agent = CoreAgent(**standart_agentic_kwargs)
        print("[MULTI-AGENT] Initializing ReactionAgent...")
        self.reaction_agent = ReactionAgent(**standart_agentic_kwargs)

        self.initialized = True
        self.current_plan = None
        print("[MULTI-AGENT] Initialization complete")

    def run(self):
        """
        Main agent loop: Planner sets strategy, then alternates between reaction and core agents

        Pattern: Planner -> 3x ReactionAgent -> 1x CoreAgent -> repeat
        """
        print("[MULTI-AGENT] Starting multi-agent system")
        self.running = True
        iteration_count = 0

        while self.ctx_swarm["env"]["actived"] and self.running:
            try:
                if not self.initialized:
                    print("[MULTI-AGENT] NOT INITIALIZED")
                    continue

                # Run reaction agent iterations
                for i in range(self.reaction_iterations):
                    if not self.running or not self.ctx_swarm["env"]["actived"]:
                        break

                    print(
                        f"\n[MULTI-AGENT] === Reaction iteration {i+1}/{self.reaction_iterations} ==="
                    )
                    self.reaction_agent.step()
                    iteration_count += 1

                # Run core agent iteration
                if self.running and self.ctx_swarm["env"]["actived"]:
                    print(
                        f"\n[MULTI-AGENT] === Planning iteration (cycle {iteration_count}) ==="
                    )
                    self.planner_agent.step()
                    self.current_plan = self.planner_agent.last_plan
                    # For now, disable core agent
                    run_core_agent = False
                    if run_core_agent:
                        print(
                            f"\n[MULTI-AGENT] === Core iteration (after {iteration_count} reactions) ==="
                        )
                        self.core_agent.step()
                        iteration_count += 1

            except Exception as e:
                print(f"[MULTI-AGENT] Error: {e}")
                traceback.print_exc()

        print("[MULTI-AGENT] Stopped")

    def stop(self):
        """Stop all agents"""
        self.running = False
        if hasattr(self, "planner_agent"):
            self.planner_agent.stop()
        if hasattr(self, "reaction_agent"):
            self.reaction_agent.stop()
        if hasattr(self, "core_agent"):
            self.core_agent.stop()
        print("[MULTI-AGENT] Stopped all agents")

    def cleanup(self):
        """Clean up all agents"""
        if self.running:
            self.stop()
        if hasattr(self, "planner_agent"):
            self.planner_agent.cleanup()
        if hasattr(self, "reaction_agent"):
            self.reaction_agent.cleanup()
        if hasattr(self, "core_agent"):
            self.core_agent.cleanup()


if __name__ == "__main__":
    import multiprocessing as mp

    manager = mp.Manager()
    # Test the multi-agent
    ctx_swarm = create_ctx_swarm(manager)
    ctx_swarm["env"]["actived"] = True
    ctx_handler = CtxHandler(ctx_swarm=ctx_swarm)

    def console_loop():
        while True:
            cmd = input("Enter command: ")
            if cmd == "stop":
                agent.stop()
                break
            else:
                ctx_handler.add_message(cmd)
                print("ctx chat", ctx_handler.get_ctx_chat(dict_format=True, limit=5))

    s = threading.Thread(target=console_loop, daemon=True)
    s.start()
    agent = MultiAgent(ctx_swarm, ctx_handler=ctx_handler)
    agent.run()
