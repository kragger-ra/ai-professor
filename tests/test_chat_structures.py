import asyncio
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_flow.ctx_handler import CtxHandler
from data_schema.structure_templates import create_ctx_swarm
from utils.structure_helper import load_ctx_chat_sample


async def test_kill_event():
    """Test subscribing to and handling kill events using sample data"""

    # Initialize handler with sample data
    from multiprocessing import Manager

    manager = Manager()
    ctx_chat = manager.list()
    load_ctx_chat_sample(
        realtime=True, new_ctx_chat=ctx_chat, add_first=0
    )  # inplace operation
    ctx_swarm = create_ctx_swarm(manager, old_swarm_dict={"ctx_chat": ctx_chat})
    handler = CtxHandler(ctx_swarm)

    # Define message checker function
    def is_kill_message(m):
        print("checking ev", m)
        return m.type.startswith("kill") if m.type else False

    # Test wait_for with timeout
    # try:
    #     kill_msg = await handler.wait_for(is_kill_message, timeout=1.0)
    #     print("Unexpected: found kill message before timeout")
    # except asyncio.TimeoutError:
    #     print("Expected timeout occurred while waiting for kill message")
    #
    # Add a kill message
    kill_event = {
        "msg": "kill",
        "user": "tester",
        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "processing_timestamp": time.time_ns(),
        "type": "kill",
        "lol": "testField",
    }

    print("Initial state:", handler.ctx_chat, ctx_chat)

    executor = ThreadPoolExecutor()

    def add_msg():
        time.sleep(3)
        print("Adding kill message", handler.add_message(kill_event))
        time.sleep(1)
        for i, msg in enumerate(ctx_chat):
            print(i, msg)
            if kill_event["processing_timestamp"] == msg["processing_timestamp"]:
                print("Found kill message in ctx_chat")
                msg["filter_results"] = True
                ctx_chat[i] = msg
                break
        print("Message added, current state:", handler.ctx_chat)
        print(type(handler.ctx_chat))

    future = executor.submit(add_msg)

    # Wait for the kill message
    try:
        kill_msg = await handler.wait_for(is_kill_message, timeout=10.0)
        # kill_msg = handler.wait_for_sync(is_kill_message, timeout=5.0)
        print("Successfully caught kill message:", kill_msg)
    except (asyncio.TimeoutError, TimeoutError):
        print("Unexpected: timeout while waiting for existing kill message")

    # future.result(timeout=3)
    print("==end of code==", type(handler.ctx_chat), type(ctx_chat))


if __name__ == "__main__":
    asyncio.run(test_kill_event())
