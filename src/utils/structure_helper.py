import json
import os
import pickle
import random
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Sequence, Union

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from data_schema.structure_templates import REPO_DATA_PATH, REPO_DEBUG_PATH


def load_json(path: str) -> Sequence | Dict:
    load_dict = {}
    with open(path, "r", encoding="utf-8") as file:
        load_dict = json.load(file)
    return load_dict


def load_ctx_chat_sample(
    realtime: bool = False,
    new_ctx_chat: Sequence = None,
    add_time: float = 5,
    add_first: int = 5,
) -> Union[None, Sequence[dict]]:
    """
    VARIOUS NOTE: inplace opearion if realtime=True, otherwise returns ctx_chat
    Update timestamps in chat context data, either in real-time or statically.
    This function loads chat context from a JSON file and updates timestamps for each message.
    In real-time mode, it runs in a separate thread and continuously updates new messages.
    In static mode, it updates all messages at once and returns the context.
    Args:
        realtime (bool, optional): Whe
        add_time (float, optional): Base time offset in seconds to adther to update timestamps in real-time. Defaults to False.
        new_ctx_chat (Sequence, optional): List to store new chat context in real-time mode.
            Required if realtime=True. Defaults to None.d between messages.
            Defaults to 5.
    Returns:
        Sequence[dict]: Updated chat context messages with new timestamps (only in static mode).
            In real-time mode, messages are added to new_ctx_chat instead.
    Note:
        The function loads chat context from 'ctx_chat_sample.json' in the debug directory.
        Each message gets updated with:
        - 'date': Formatted datetime string
        - 'processing_timestamp': Nanosecond timestamp
    """
    ctx_chat: Sequence[dict] = load_json(os.path.join(REPO_DEBUG_PATH, "ctx_chat.json"))

    def update_ctx_chat():
        nonlocal add_time
        time_point = datetime.now()
        for i, item in enumerate(ctx_chat):

            offset_time = add_time + random.choice([0.5, 0.1, 1, 2])
            now = datetime.now()
            if realtime:
                time_point = now + (now - time_point)
                if i <= add_first:
                    pass
                else:
                    time.sleep(offset_time)
            else:
                time_point = now - timedelta(seconds=offset_time + add_time)
            item.update(
                {
                    "date": time_point.strftime("%Y-%m-%d %H:%M:%S"),
                    "processing_timestamp": int(time_point.timestamp() * 1000000000),
                }
            )
            if realtime:
                # add to list of new ctx_chat
                new_ctx_chat.append(item)
                print("[Debug ctx chat] added new event", item)
            else:
                ctx_chat[i] = item

    if realtime:
        updater_thread = threading.Thread(target=update_ctx_chat, daemon=True)
        updater_thread.start()
    else:
        update_ctx_chat()
        return ctx_chat


def load_swarm():
    CTX_SWARM_PATH_PKL = os.path.join(REPO_DATA_PATH, "internal", "ctx_swarm.pkl")
    return pickle.load(open(CTX_SWARM_PATH_PKL, "rb"))


def save_swarm(ctx_swarm: dict):

    # TODO dictify proxy objects
    ctx_swarm_primitive = {}
    # for key, value in ctx_swarm.items():
    #     ctx_swarm_primitive[key] = value

    # NOW SAVING ONLY CTX CHAT
    need_save = False
    for ctx_obj_str in ["ctx_chat"]:  # maybe later add something list-like
        ctx_obj = ctx_swarm.get(ctx_obj_str, [])
        if len(ctx_obj) > 0:
            # convert listProxy -> list
            ctx_swarm_primitive[ctx_obj_str] = list(ctx_obj)
            if len(ctx_swarm_primitive[ctx_obj_str]) > 50:  # remove too many data
                ctx_swarm_primitive[ctx_obj_str] = ctx_swarm_primitive[ctx_obj_str][
                    -50:
                ]
            need_save = True
    if need_save:

        CTX_SWARM_SAVE_PATH = os.path.join(REPO_DATA_PATH, "internal")
        pickle.dump(
            ctx_swarm_primitive,
            open(os.path.join(CTX_SWARM_SAVE_PATH, "ctx_swarm.pkl"), "wb"),
        )


if __name__ == "__main__":
    # print(load_ctx_chat_sample())
    ctx_chat = []
    load_ctx_chat_sample(realtime=True, new_ctx_chat=ctx_chat, add_time=5)
    while True:
        # if len(ctx_chat) > 0:
        #     print("Latest event:", ctx_chat[-1])
        time.sleep(10)
