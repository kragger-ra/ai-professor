"""

CORE AGENT

supports streaming output

tools like !tool 123
/command minecraft
@aget action
> speak *emotion*
"""

import importlib
import os
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from typing import Optional

from agent.base_agent import BaseAgent
from data_flow.ctx_host import CtxHost
from data_schema.ctx_structures import CtxSwarmType
from data_schema.tool_structures import ToolBankType

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


class CoreAgent(BaseAgent):
    """Core agent for using with custom command and tool structures."""

    def __init__(
        self,
        ctx_swarm: CtxSwarmType,
        ctx_handler: Optional[CtxHandler] = None,
        ctx_host: Optional[CtxHost] = None,
        tool_bank: Optional[ToolBankType] = None,
    ):
        """Initialize the agent with context swarm"""
        super().__init__(ctx_swarm, ctx_handler)
        if ctx_handler is None:
            self.ctx_handler = CtxHandler(ctx_swarm)
        else:
            self.ctx_handler = ctx_handler

        # Initialize LLM
        self.llm = get_llm_chain()
        try:
            self.rag_model = RagModel()
        except Exception as e:
            print(f"[CoreAgent] Error initializing RagModel: {str(e)}")
            traceback.print_exc()
            self.rag_model = None
            print("[CoreAgent] Continuing without RAG model, setting it to None.")

        if tool_bank is not None:
            self.tool_bank = tool_bank
        else:
            self.tool_bank = tools_config.init_tools_module(
                ctx_swarm, self.ctx_handler, new_llm=self.llm
            )
        print("tool bank init")
        if ctx_host is None:
            self.ctx_host = CtxHost(ctx_handler, tool_bank=self.tool_bank)
        else:
            self.ctx_host = ctx_host
        self.initialized = True

    @contextmanager
    def cleanup_context(self):
        """Context manager for cleanup"""
        try:
            yield self
        finally:
            self.cleanup()

    def cleanup(self):
        """Clean up resources"""
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
            # Reload all dependent modules
            importlib.reload(sys.modules["agent.tools.tools"])
            importlib.reload(sys.modules["agent.tools.tools_config"])
            importlib.reload(sys.modules[__name__])

            # Reinitialize
            self.__init__(self.ctx_swarm, self.ctx_handler)

    def stop(self):
        """Stop the agent"""
        self.running = False

    def is_running(self):
        """Check if agent is running"""
        return self.running

    def step(self):
        """Run a single iteration of the agent"""
        try:
            if not self.initialized:
                print("[DEBUG CORE AGENT] NOT INITIALIZED")
                return
            # self.ctx_swarm["fx_queue"].put("ready")
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
            # Get response from LLM
            smart_event_waiter = SmartEventWaiter(ctx_handler=self.ctx_handler)
            self.ctx_swarm["fx_queue"].put("thinking")
            t_start = time.time()
            response = execute_tool_query(
                messages,
                should_interrupt=smart_event_waiter.check,
                response_starting=response_starting,
            )
            llm_elapsed_ms = int((time.time() - t_start) * 1000)
            smart_event_waiter.shutdown()

            print(f"Agent response:\n---\n{response}\n---\n")

            # Push interaction data to shared state for the main-process poller
            if response:
                last_query = ""
                ctx_chat = self.ctx_handler.get_ctx_chat(dict_format=True, limit=1)
                if ctx_chat:
                    last_entry = ctx_chat[-1]
                    if isinstance(last_entry, dict):
                        last_query = last_entry.get("msg", "")
                self.ctx_swarm["env"]["last_interaction"] = {
                    "query": last_query,
                    "response": str(response),
                    "response_time_ms": llm_elapsed_ms,
                    "emotion": "neutral",
                }
            # print(f"Messages state AFTER response")
            # print_messages(messages)

        except Exception as e:
            print(f"Error running agent: {e}")
            traceback.print_exc()
            time.sleep(10)

    def run(self):
        """Main agent loop"""
        print("Starting simple chat agent")
        self.running = True
        self.ctx_swarm["fx_queue"].put("starting")
        while self.ctx_swarm["env"]["actived"] and self.running:
            self.step()


if __name__ == "__main__":
    import multiprocessing as mp

    from data_schema.structure_templates import create_ctx_swarm

    manager = mp.Manager()
    # Test the agent
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
                # print("ctx chat", ctx_handler.get_ctx_chat(limit=5, validate=False, raw=True, dict_format=True))

    s = threading.Thread(target=console_loop, daemon=True)
    s.start()
    agent = CoreAgent(ctx_swarm, ctx_handler=ctx_handler)
    agent.run()
