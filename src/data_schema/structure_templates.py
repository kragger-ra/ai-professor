import asyncio
import json
import os
import sys
from queue import Queue

from data_schema.ctx_structures import CtxSwarmType, DummyLock

REPO_CODE_PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
REPO_ROOT_PATH = os.path.dirname(REPO_CODE_PATH)
REPO_DATA_PATH = os.path.join(REPO_ROOT_PATH, "data")
REPO_DEBUG_PATH = os.path.join(REPO_DATA_PATH, "debug")
REPO_RESOURCE_PATH = os.path.join(REPO_ROOT_PATH, "resources")
REPO_PROMPTS_PATH = os.path.join(REPO_RESOURCE_PATH, "Prompts")

FX_AUDIO_DIR = os.path.join(REPO_RESOURCE_PATH, "Audio", "fx")
FX_MANIFEST = os.path.join(FX_AUDIO_DIR, "fx_manifest.yml")

THOUGHTS_FORMAT = {
    "summary": "short overall summary of situation understanding",
    "focus_topic": "1 topic that we should focus on. For example it can be: players, spam, specific_nick, etc.",
    "restricted_topics": "the restricted topics that we should NOT TO TALK AND REPEAT anymore. Need to include all old topics (we should not repeat older topics). Example: game agent, hobbyhorsing, etc.",
    "plan": "1. Divided with numbers and separated by sentences. 2. List that conveys. N. Represents your current strategy.",
    "criticism": " Short and constructive self-criticism",
}


TOOL_CALLS_FORMAT = {
    "command_name_example_one": {
        "argument_name": "value",
        "other_argument": "other_value",
    },
    "command_name_example_two": {"argument_name": "value"},
}


RESPONSE_FORMAT = {
    "thoughts": THOUGHTS_FORMAT.copy(),
    "tool_calls": TOOL_CALLS_FORMAT.copy(),
    # "speak": "thoughts commentary to speak with your mouth on stream (VERY SHORT, NOT MORE than ~10 words)",
}


CTX_SWARM_EMPTY = {
    "ctx_chat": [],
    "chat_queue": [],
    "tts_queue": [],
    "fx_queue": Queue(),  # mp.Queue
    "votes": {},
    "env": {"actived": True, "filter_enabled": True, "youtube_social_enabled": True},
    "mood": float(0),
    "lock": DummyLock(),
    "ctx_host_lock": DummyLock(),
    "internal_command_queue": Queue(),
    "filter_input_queue": Queue(),
    "filter_output_queue": Queue(),
    "audio_feed_queue": Queue(),
    "vtube": {
        "NeedX": 0,
        "NeedY": 0,
        "eyeX": 0,
        "eyeY": 0,
        "state": "idle",  # "idle",
        "game_yawspeed": 0,
        "game_pitchspeed": 0,
    },
    "voice": {
        "text_chunk": "",  # chunk of text that is speaking now
        "is_speaking": False,  # is speaking now
        "interrupt": False,  # interrupt speaking
        "speak_entry": {
            "text": "",
            "emotion": "",
        },  # currently full speaking entry with emotion from speaking tts_queue
    },
    # MOVED TO ENV!!!
    # "nicknames": {
    #     "youtube": "Net Tyan",  # SELF_YOUTUBE_DISPLAYNAME
    #     "youtube_id": "NetTyan",  # SELF_YOUTUBE_CHANNEL_ID
    #     "twitch": "nettyan_ai",  # SELF_TWITCH_USERNAME
    #     "trovo": "NetTyan",   # SELF_TROVO_USERNAME
    #     "minecraft": "NetTyan",   # SELF_MINECRAFT_NICKNAME
    #     "discord": "Net Tyan",   # SELF_DISCORD_DISPLAYNAME
    #     "discord_full": "Net Tyan#4123",   # SELF_DISCORD_USERNAME
    # },
    "states": {
        "thoughts": THOUGHTS_FORMAT.copy(),  # TODO untested
        "summary": "",
        "plan": "",
        "personality": "professor_default",  # from resources/prompts/personalities_professor.yml
        "game_state": "System started, no info got in game, situation: neutral. Needs update!",
        "chat_state": "System started so chat is empty, situation in chat: neutral. Needs update!",
        "emotional_state": "Эмоция: Весёлая!\nСилы: Много!\nКомментарий: Пока ещё никто не успел испортить настроение, совсем недавно запущена. Needs update!",
    },
    "game": {
        "mc_last_chat_interact": "2023-04-01 00:00:00",  # ValueError: time data '00:00:00' does not match format '%Y-%m-%d %H:%M:%S'
        "mc_started": False,
        "ingame": False,
        "hasActiveTask": False,
        "near_threats": [],
        "held_item": "",
        "ground_block": "",
        "task_chain": "",
        "nearby_players": [],
    },
}

AGENT_SUPERVISOR_GOALS = [
    "Be smart and efficient",
    "Do not repeat your previous messages. ATTENTION this is important!",
    "Do not violate any laws and twitch rules",
]
CTX_CHAT_SAMPLE = [
    {
        "date": "2025-01-05 03:17:49",
        "env": "minecraft",
        "msg": "MurderMystery » Игрока pafa_2509 убили! Но кто?",
        "processing_timestamp": 1736021869741087200,
        "user": None,
    },
    {
        "date": "2025-01-05 03:17:52",
        "description": " killed you!!! =(",
        "env": "minecraft",
        "happiness_score": -3,
        "isEvent": True,
        "processing_timestamp": 1736021872593136100,
        "type": "death",
        "user": "Chochok",
    },
    {
        "date": "2025-01-05 03:17:53",
        "env": "minecraft",
        "msg": "Привет всем новеньким",
        "precision": "exact",
        "processing_timestamp": 1736021873965839300,
        "self": True,
        "server": "mc.musteryworld.net",
        "serverMode": "murdermystery",
        "user": "NetTyan",
    },
    {
        "date": "2025-01-05 03:17:58",
        "env": "minecraft",
        "msg": "MurderMystery » Игрока ZlambardZ убили! Но кто?",
        "processing_timestamp": 1736021878635304600,
        "user": None,
    },
]


PRIVATE_MESSAGE_TOOL_FEW_SHOT_EXAMPLES = [
    {
        "request": "Say hello to the user Lexa",
        "params": {"message": "hello, Lexa", "user": "Lexa"},
    },
    {
        "request": "Answer vika to her question about your age.",
        "params": {"message": "Vika, I am 20. And you?", "user": "Lexa", "reply": True},
    },
]


def create_locks_for_ctx_swarm(ctx_swarm: dict, manager) -> None:
    """Create and add locks for each variable in ctx_swarm"""
    # Get all keys first to avoid modifying during iteration
    names = list(ctx_swarm.keys())
    for name in names:
        if name != "ctx_lock":  # Skip the main lock
            lock_name = f"{name}_lock"
            if lock_name not in ctx_swarm:  # Don't recreate existing locks
                ctx_swarm[lock_name] = manager.Lock()
                # print("added lock for", name, "val", lock_name)
                # really useful debug!


def create_ctx_swarm(manager=None, old_swarm_dict=None) -> CtxSwarmType:
    if manager is None:
        import multiprocessing as mp

        manager = mp.Manager()
    if old_swarm_dict is None:
        old_swarm_dict = CTX_SWARM_EMPTY.copy()

    ctx_swarm = {}

    # Convert values to manager proxies
    for key, value in old_swarm_dict.items():
        if isinstance(value, dict):
            ctx_swarm[key] = manager.dict(value)
        elif isinstance(value, list):
            ctx_swarm[key] = manager.list(value)
        elif isinstance(value, Queue) or isinstance(value, asyncio.Queue):
            ctx_swarm[key] = manager.Queue()
        elif isinstance(value, DummyLock):
            # Create a new lock instead of converting DummyLock
            ctx_swarm[key] = manager.Lock()
        elif isinstance(value, float):
            ctx_swarm[key] = manager.Value("d", value)
        elif isinstance(value, bool):
            ctx_swarm[key] = manager.Value("b", value)
        elif isinstance(value, int):
            ctx_swarm[key] = manager.Value("i", value)
        elif isinstance(value, str):
            ctx_swarm[key] = value  # Strings are immutable, no need for proxy
        else:
            ctx_swarm[key] = value
        # print(
        #     "added ctx swarm key",
        #     key,
        #     "val",
        #     ctx_swarm[key],
        #     "valtype",
        #     type(ctx_swarm[key]),
        # )
    # Create locks for all variables
    create_locks_for_ctx_swarm(ctx_swarm, manager)

    return ctx_swarm
