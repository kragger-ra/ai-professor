"""Tests for prompt constructor functionality."""
from multiprocessing import Manager
import sys
import os
import time

sys.path.insert(
    0,
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "src"
    ),
)

from agent.rag import RagModel
from agent.tools.tools import AGENT_SUPERVISOR_TOOLS, execute_tool_query
from agent.tools.dialogue_tools import _save_user_summary, get_user_summary

from agent.prompt_generation.prompt_constructor import construct_prompt_messages
from data_flow.ctx_handler import CtxHandler
from data_schema.structure_templates import create_ctx_swarm
from utils.structure_helper import load_ctx_chat_sample

from utils.debug import print_messages


def test_prompt_constructor():
    """Simple test for prompt constructor with print verification"""
    tools = AGENT_SUPERVISOR_TOOLS
    manager = Manager()
    
    ctx_swarm = create_ctx_swarm(manager)
    load_ctx_chat_sample(new_ctx_chat=ctx_swarm["ctx_chat"], realtime=True)
    ctx_handler = CtxHandler(ctx_swarm)
    print(f"Loaded {len(ctx_swarm['ctx_chat'])} chat messages.")
    rag_model = RagModel()
    from agent.tools import tools_config
    tools_config.init_tools_module(ctx_swarm, None, ctx_handler, tools_format="langchain")
    # Test messages format
    print("\nTesting messages format:")
    # result = # construct_prompt("", tools, ctx_swarm)
    result = construct_prompt_messages(tools, ctx_handler, rag_model=rag_model, output_format="langchain", tool_use_format="command",
                                       #goal="Use tools. Use as more as you can."
                                       )
    print(f"Messages result type: {type(result)}")
    print_messages(result)
    # print(f"First message content preview: {result}...")

    print("======== END ======")

    # print(execute_tool_query([{"role": "system", "content": " HFSDHFGJH JHGJHHJ say 123"}]))
    print(execute_tool_query(result))
    print(ctx_swarm["ctx_chat"])
    print(get_user_summary('koldyn_2_'))
    print(_save_user_summary('koldyn_2_', 'test'))
    print(get_user_summary('koldyn_2_'))
    time.sleep(10)
    print("10 secs left")
    ctx_handler.shutdown()
    manager.shutdown()
    

    exit()
    # Test dict format
    # print("\nTesting dict format:")
    # result = construct_prompt_messages(tools, ctx_swarm, output_format="dicts")
    # print(f"Dict result type: {type(result)}")
    # print(f"First dict content preview: {result}...")
    # 
    # # Test string format
    # print("\nTesting string format:")
    # result = construct_prompt_messages(tools, ctx_swarm, output_format="string")
    # print(f"String result type: {type(result)}")
    # print(f"String content preview: {result}...")

if __name__ == "__main__":
    test_prompt_constructor()