import os
import sys
import time
from multiprocessing import Manager

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.tools.tools import chat_simple, mc_send
from data_flow.ctx_handler import CtxHandler
from data_schema.structure_templates import create_ctx_swarm


def test_chat_queue():
    # Create proper managed context
    manager = Manager()
    ctx_swarm = create_ctx_swarm(manager)

    # Create handler
    ctx_handler = CtxHandler(ctx_swarm)

    # Initialize tools with proper context
    import agent.tools.tools as tools

    tools.ctx_swarm = ctx_swarm

    # Test messages
    messages = ["Test message 1", "Test message 2", "Test message 3"]

    print("\nTesting direct mc_send:")
    for msg in messages:
        print(f"\nSending: {msg}")
        mc_send(msg)
        print("Queue state:", list(ctx_swarm["chat_queue"]))
        time.sleep(1)

    print("\nTesting chat_simple:")
    for msg in messages:
        print(f"\nSending: {msg}")
        chat_simple(msg)
        print("Queue state:", list(ctx_swarm["chat_queue"]))
        time.sleep(1)


if __name__ == "__main__":
    test_chat_queue()
