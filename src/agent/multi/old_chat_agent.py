"""
UNTESTED & UN...
Simple chat agent

Follows the same structure and pipeline as CoreAgent:
- uses construct_prompt_messages to build LLM prompt with tools and context
- uses tools.execute_tool_query (tool executor toolkit) for streaming output
    and tool calls
"""

import importlib
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Optional

from data_flow.ctx_host import CtxHost
from data_schema.ctx_structures import CtxSwarmType

if __name__ == "__main__":
    module_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
    sys.path.insert(0, module_dir)
    from data_schema.structure_templates import create_ctx_swarm

from agent.llm_clients.lc_clients import get_llm_chain
from agent.prompt_generation.prompt_constructor import (
    SmartEventWaiter,
    construct_prompt_messages,
)
from agent.rag import RagModel
from agent.tools import tools_config
from agent.tools.tools import execute_tool_query, get_tool_records
from data_flow.ctx_handler import CtxHandler
from utils.debug import print_messages


class ChatAgent:
    """Minimal chat agent built on the existing pipeline and tool executor."""

    def __init__(
        self, ctx_swarm: CtxSwarmType, ctx_handler: Optional[CtxHandler] = None
    ):
        self.initialized = False
        self.ctx_swarm = ctx_swarm
        self.ctx_handler = ctx_handler or CtxHandler(ctx_swarm)

        # LLM and helpers
        self.llm = get_llm_chain()
        self.rag_model = RagModel()

        # Tools init (shared global tool bank)
        tool_bank = tools_config.init_tools_module(
            ctx_swarm, self.ctx_handler, new_llm=self.llm
        )

        # Host wraps queues/state
        self.ctx_host = CtxHost(self.ctx_handler, tool_bank=tool_bank)

        self.running = False
        self.initialized = True

    @contextmanager
    def cleanup_context(self):
        try:
            yield self
        finally:
            self.cleanup()

    def cleanup(self):
        if self.running:
            self.stop()
        if hasattr(self, "llm"):
            del self.llm
        if hasattr(self, "rag_model"):
            del self.rag_model
        if hasattr(self, "ctx_host"):
            del self.ctx_host
        # Reset tools config globals
        importlib.reload(tools_config)

    def reload(self):
        """Safely reload the agent and tools"""
        with self.cleanup_context():
            importlib.reload(sys.modules["agent.tools.tools"])  # type: ignore
            importlib.reload(sys.modules["agent.tools.tools_config"])  # type: ignore
            importlib.reload(sys.modules[__name__])
            self.__init__(self.ctx_swarm, self.ctx_handler)

    def stop(self):
        self.running = False

    def is_running(self) -> bool:
        return self.running

    def run(self):
        """Main chat loop using the shared pipeline and tool executor."""
        print("Starting simple chat agent")
        self.running = True
        self.ctx_swarm["fx_queue"].put("starting")
        while self.ctx_swarm["env"]["actived"] and self.running:
            try:
                if not self.initialized:
                    print("[DEBUG CHAT AGENT] NOT INITIALIZED")
                    time.sleep(0.5)
                    continue

                messages, response_starting = construct_prompt_messages(
                    get_tool_records(),
                    self.ctx_handler,
                    rag_model=self.rag_model,
                    output_format="langchain",
                    tool_use_format="command",
                )

                if self.ctx_swarm["env"].get("debug_print_prompt", False):
                    print("Context messages:")
                    print_messages(messages)

                smart_event_waiter = SmartEventWaiter(ctx_handler=self.ctx_handler)
                self.ctx_swarm["fx_queue"].put("thinking")
                response = execute_tool_query(
                    messages,
                    should_interrupt=smart_event_waiter.check,
                    response_starting=response_starting,
                )
                smart_event_waiter.shutdown()

                print(f"Agent response:\n---\n{response}\n---\n")

            except Exception as e:
                print(f"Error running chat agent: {e}")
                traceback.print_exc()
                time.sleep(5)


if __name__ == "__main__":
    import multiprocessing as mp

    manager = mp.Manager()
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
                print(
                    "ctx chat",
                    ctx_handler.get_ctx_chat(dict_format=True, limit=5),
                )

    s = threading.Thread(target=console_loop, daemon=True)
    s.start()
    agent = ChatAgent(ctx_swarm, ctx_handler=ctx_handler)
    agent.run()
