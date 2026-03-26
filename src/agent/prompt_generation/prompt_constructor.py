"""Prompt constructor for agent response generation.
Based on tools and status tools, compatible with langchain and smolagents.
Creating the prompt for the agent to generate the response.

Based on tools and status tools.

Should be compatible with langchain and smolagents.

SIMPLIEST approach

test should be in tests/prompt_construct_test.py

There should be ALL prompt-constructing logic merged from:
from agent/autogpt/prompt.py,
agent/autogpt/prompt_generator.py
and finally agent/autogpt/agent.py
, but TOO more simplier and easy configurable for other output types, for example list[dict] or list[langchain BaseMessage]

In inputs it should get:
rag_model,
current tools list


"""

import json
import random
import time
from dataclasses import dataclass
from threading import Thread
from typing import Any, Dict, List, Optional, Tuple, Union

from langchain_core.messages import (
    BaseMessage,
    HumanMessage,
    SystemMessage,
    convert_to_messages,
)

from agent.prompt_generation.idea_suggestor import get_cringe_tag, get_random_idea
from agent.tools.dialogue_tools import _get_user_data
from agent.tools.status_tools import (
    get_game_status,
    get_plan,
    get_tool_status,
)
from agent.tools.tool_executor import get_tool_fewshots
from config_schema.general import get_name, get_secret
from data_flow.ctx_handler import CtxHandler

# from data_flow.database import StreamerDatabase
from data_schema.chat_structures import (
    CtxEventBase,
    MentionedUser,
    UserData,
    default_event_check,
    interrupt_event_check,
)
from data_schema.ctx_structures import CtxSwarmType
from data_schema.tool_structures import ToolRecord
from utils.format_helper import (
    format_events_for_rag,
    format_events_with_roles,
    openai_chat_to_str,
)
from utils.minecraft_helper import PlayerStatus, get_nearby_players
from utils.prompt_helper import prompt_load
from utils.vision_helper import get_actual_frame

# TODO add to config general names that we EVERYTIME can easyly get

SELF_NAME = get_name()


@dataclass
class UserInfo:
    """For adorable string representation of found user info"""

    name: str
    chat_mentioned: Optional[MentionedUser] = None
    user_data: Optional[UserData] = None
    mc_player_status: Optional[PlayerStatus] = None
    priority: float = 0

    def _format_float(self, value: float) -> str:
        """Format float values with 1 decimal place, handle non-float values"""
        if value is None:
            return "?"
        try:
            return f"{float(value):.1f}"
        except (ValueError, TypeError):
            return str(value)

    def _dist_to_str(self, distance: float) -> str:
        """Format distance into strings like <5 - TOO CLOSE, ..."""
        if distance is None:
            return ""
        if distance < 1:
            return "IN YOU"
        if distance < 5:
            return "TOO CLOSE"
        if distance < 10:
            return "close"
        if distance < 20:
            return "near"
        return "far"

    def __str__(self):
        """Format user information in a structured way

        Userdata available:
        | --
        | Player Chochok:
        | No summary stored
        | Actived in chat 51.6s ago, 1 messages
        | Health: 18.0
        | Gamemode: survival
        | Can be attacked
        | Located at blockPos 72, 71, 111 (7.1m from you)
        | On block minecraft:cobblestone
        | Holding Harmless minecraft:goat_horn
        | Can be attacked
        | --
        | Player NetTyan:
        | No summary stored
        | Actived in chat 15.4s ago, 22 messages
        | Health: 20.0
        User я:
        | No summary stored
        | Actived in chat 4.0m ago, 1 messages
        | --
        | User Ошибка:
        | No summary stored
        | Actived in chat 2.1m ago, 1 messages
        |

        """

        # Add header with user/player designation
        prefix = "Player" if self.mc_player_status else "User"
        record_name = f"{prefix} '{self.name}'"
        lines = []
        game_lines = []
        is_self = False
        if self.name == SELF_NAME:
            is_self = True
            lines.append(f"!! is yourself, {self.name} !!")

        # Add user summary if available
        if self.chat_mentioned:
            if not is_self:
                user_data = _get_user_data(self.name)

                user_summary = user_data["summary"] if user_data else ""
                user_rank = user_data["rank"] if user_data else 3
                if user_summary:
                    lines.append(user_summary)
                else:
                    lines.append("No summary saved =(")
                if user_rank:
                    lines.append(
                        f"Rank: {str(round(user_rank))} of 5 (rank '{get_cringe_tag(user_rank)}')"
                    )
            events = self.chat_mentioned["binded_events"]
            if events:
                ev = events[-1]
                if ev.get("env", False):
                    lines.append(f"Platform: {ev['env']}")
            # Add chat activity
            lines.append(
                f"Chat activity {self.chat_mentioned['last_activity_string']} {self.chat_mentioned['found_count']} times"
            )

        if not self.mc_player_status:
            game_lines.append("Game: NOT IN GAME, ONLY IN CHAT!!!")
        else:
            status = self.mc_player_status

            # Health
            if status["health"] is not None:
                game_lines.append(f"Health: {self._format_float(status['health'])}")

            # Gamemode
            if status["gamemode"]:
                game_lines.append(f"Gamemode: {status['gamemode']}")

            # Location
            location = []
            if status["position"]:
                location.append(f"Located at blockPos {status['position']}")
            if not is_self and status["distance"] is not None:
                location.append(
                    f"({self._format_float(status['distance'])}m from you, {self._dist_to_str(status['distance'])})"
                )
            if location:
                game_lines.append(" ".join(location))

            # Ground block
            if status["ground_block"]:
                game_lines.append(f"On block {status['ground_block']}")

            # Equipment and weapon threat
            if status["hand_item"]:
                held_item = []
                if status["weapon_threat"]:
                    held_item.append(status["weapon_threat"])
                held_item.append(status["hand_item"])
                game_lines.append(f"Holding {' '.join(held_item)}")

            # Combat status
            combat_flags = []
            if status["in_combat"]:
                combat_flags.append("In combat")
            if status["attackable"]:
                combat_flags.append("Attackable")
            if combat_flags:
                game_lines.append(", ".join(combat_flags))

            # Looking status
            if not is_self and status["is_looking_at_you_prob"] > 0.7:
                lines.append("Was looking at you")

            if (
                not is_self
                and status["is_looking_at_you_prob"] > 0.5
                and status["distance"] is not None
                and status["distance"] < 10
                and status["weapon_threat"].lower() != "harmless"
            ):
                lines.append("IS A THREAT FOR YOU! MAY ATTACK YOU!")
            # Chat status if not mentioned earlier
            if not self.chat_mentioned:
                lines.append("Not chatted recently")
        general_lines_string = "Info{" + ", ".join(lines) + "}"
        game_lines_string = ""
        if game_lines:
            game_lines_string = "GameData{" + ", ".join(game_lines) + "}"
        result = (
            record_name
            + ": [\n"
            + general_lines_string
            + ",\n"
            + game_lines_string
            + "\n]"
        )
        return result


def get_users_info(
    ctx_swarm: dict,
    chat_users: Dict[str, MentionedUser],
    focused_user: str = "",
) -> str:
    """Get users info for prompt

    Prioritizes users based on:
    - Focused user (highest priority)
    - Minecraft players in view
    - Recently active chat users
    - Other chat users

    Args:
        ctx_swarm: Context swarm with game state
        chat_users: Dict of chat users and their mention counts
        focused_user: Currently focused user name

    Returns:
        Formatted string with up to 5 most relevant users
    """
    user_info: List[UserInfo] = []

    # Process Minecraft players (highest base priority)
    nearby_players = get_nearby_players(ctx_swarm)
    for player_name, status in nearby_players.items():
        # Base priority: 50
        # +50 if focused
        # +20 if close (< 10m)
        # +10 if active in chat
        priority = 50
        if player_name == focused_user:
            priority += 50
        if status["distance"] and status["distance"] < 10:
            priority += 100 * (10 - status["distance"])
        if player_name in chat_users:
            priority += 10
            chat_mention = chat_users[player_name]
        else:
            chat_mention = None

        info = UserInfo(
            name=player_name,
            mc_player_status=status,
            chat_mentioned=chat_mention,
            priority=priority,
        )
        user_info.append(info)

    # Add remaining chat users
    for user_name, mention in chat_users.items():
        if not any(ui.name == user_name for ui in user_info):
            # Base priority: 25
            # +50 if focused
            # +10 per recent message (max +30)
            priority = 25
            if user_name == focused_user:
                priority += 50
            if mention["found_count"] > 0:
                priority += min(mention["found_count"] * 10, 30)

            info = UserInfo(name=user_name, chat_mentioned=mention, priority=priority)
            user_info.append(info)

    # Sort by priority and limit to 5 most important
    user_info.sort(key=lambda x: (-x.priority))
    user_info = user_info[:5]
    # user_info = list(reversed(user_info))  # Restoring user_info to reversed order
    if not user_info:
        return "No users info available"

    return "\n----\n".join(
        f"{str(i)}) " + str(info) for i, info in enumerate(user_info)
    )


def get_tool_definitions(tools: List[ToolRecord], tool_use_format="command") -> str:
    """Text tool definitions for prompt"""
    # TODO
    # prettify args schema, not stupid arg1{title=lol, type=string}
    tools_desc = []
    for i, t in enumerate(tools):
        i += 1
        tools_desc.append(f"""## {str(i)}. {t["name"]}: {t["description"]}""")
        if t.get("args"):
            tools_desc.append(f""", args json schema: {json.dumps(t["args"])}""")
        tool_fewshots = get_tool_fewshots(t["name"], tool_use_format)
        if tool_fewshots:
            tools_desc.append(f"""How to use {t["name"]}:""")
            # TODO add fewshots examples into resources/Prompts/tool_fewshots_custom.yaml
            # TODO format fewshots like tool usage. Situation, tool usage in chosen format, result
            tools_desc.append(tool_fewshots)
        tool_status = get_tool_status(t["name"])
        if tool_status:
            tools_desc.append(f"""{t["name"]} current status: {tool_status}""")
    tools_prompt = "\n".join(tools_desc)
    return tools_prompt


def get_response_format(tool_use_format: str) -> str:
    """Get response format for prompt"""
    return prompt_load("tool_use_format", tool_use_format)


def construct_prompt(
    rag_context: Optional[str],
    tools: List[ToolRecord],
    ctx_swarm: CtxSwarmType,
    chat_users,
    focused_user="",
    tool_use_format: str = "command",
) -> str:
    """
    Constructs a prompt based on current tools and system state.

    Args:
        rag_context: rag_context for context enrichment
        tools: List of available tools
        ctx_swarm: Current context and state information

    Returns:
        str: constructed prompt
    """
    # Get system template from personalities
    system_template = prompt_load(
        "personalities", ctx_swarm["states"].get("personality", "streamer_abstract")
    )
    # "megabattle_yandere")

    # Get current system status
    # tools_status = status_tools.status(ctx_swarm)

    # Get RAG context if available
    # rag_context = rag_model.explain(ctx_swarm.get("ctx_chat", [])) if rag_model else ""

    tools_prompt = get_tool_definitions(tools=tools)
    # Build main prompt content
    final_rag_context = (
        "\n\n## Some vocabulary explanations:\n" + rag_context if rag_context else ""
    )
    prompt_content = [
        system_template,
        "\n# Response format:",
        get_response_format(tool_use_format),
        "\n# Available Tools:",
        tools_prompt,
        "\n# Current your MBA AutoClef (Minecraft Baritone Agent) system status:",
        get_game_status(),
        "\n# Userdata available:",
        get_users_info(
            ctx_swarm=ctx_swarm, chat_users=chat_users, focused_user=focused_user
        ),
        "\n## Your last thoughts and plans (can be unrelevant):",
        get_plan(),
        final_rag_context,
    ]

    return "\n".join(prompt_content)


def create_chat_from_prompt(prompt: str, role: str = "system") -> List[Dict]:
    return [{"role": role, "content": prompt}]


def convert_message(prompt: str, output_format: str = "langchain") -> List[BaseMessage]:
    """Converts a prompt string to Langchain Messages format"""
    if output_format == "langchain":
        return [SystemMessage(content=prompt)]
    elif output_format == "dicts":
        return [{"role": "system", "content": prompt}]
    else:  # string
        return prompt


DEFAULT_GOAL = f"""So, {SELF_NAME}, use tools and follow your main and secret goals. Good luck, darling, and remember to follow tool prefix command format like `!command args`, every command on new line!
Remember to use /minecraft command, @agent action, >speak prefixes and !another other commands to run commands and to run other commands like `!plan <your new plan>`. 
Dear, DONT FORGET TO STORE INFORMATION: big string arguments use "quotes": `!save_user_info <player> "<summary>"`.
\n[INSERTED AI MAINFRAME PERSONAL REMINDER CODE]\ndouble-check: never self-repeat || user (you are talking) REAL exists and actived || correct response format || you are {SELF_NAME}, female. || Русский язык
Start response with command now, your developer team believe you so much, darling!"""
# STRING like in format_helper in assistant role {event_type_name} [{timestamp}] {user_str}
DEFAULT_UNFINISHED_REPSONSE = f"TOOLS [NOW] {SELF_NAME} (YOU)\nResponse:\n```commands\n!focus fullfill user requests, commenting situation, no stupid greetings\n"
DEFAULT_UNFINISHED_REPSONSE_THINKING = ""
DEFAULT_UNFINISHED_REPSONSE_STARTING = "!situation "


class SmartEventWaiter:
    def __init__(self, ctx_handler: CtxHandler, delay: float = 5):
        self.handler: CtxHandler = ctx_handler
        self.delay: float = delay
        self.caught: bool = False
        self.activated: bool = True
        self.thread: Thread = Thread(target=self._wait_loop, daemon=False)
        self.caught_event: Union[CtxEventBase, None] = None
        self.thread.start()

    def check(self) -> bool:
        if self.caught:
            self.caught = False
            return True
        return False

    def _wait_loop(self) -> None:
        if self.delay > 0:
            event = self.handler.wait_for_sync(
                check=interrupt_event_check, timeout=self.delay, raise_timeout=False
            )
            if event:
                self.caught = True
                self.caught_event = event
                return
            # time.sleep(self.delay)
        while self.activated:
            self._wait()

    def _wait(self) -> Union[CtxEventBase, None]:
        event: Union[CtxEventBase, None] = self.handler.wait_for_sync(
            timeout=15.0, raise_timeout=False
        )
        if event and event.processing_timestamp != -1:
            self.caught = True
            self.caught_event = event
        return event

    def shutdown(self):
        self.activated = False
        # self.thread.join()

    def __exit__(self, *args, **kwargs):
        self.shutdown()


def construct_prompt_messages(
    tools: List[ToolRecord],
    ctx_handler: CtxHandler,
    wait_for_trigger: bool = True,
    rag_model: Any = None,
    output_format: str = "langchain",
    tool_use_format="command",
    goal: str = None,
    unfinished_response: str = DEFAULT_UNFINISHED_REPSONSE,
    response_starting: str = DEFAULT_UNFINISHED_REPSONSE_STARTING,
) -> Tuple[Union[List[BaseMessage], List[Dict], str], str]:
    """
    Constructs a prompt based on current tools and system state.

    Args:
        rag_model: RAG model for context enrichment
        tools: List of available tools
        ctx_swarm: Current context and state information
        output_format: One of "langchain", "dicts", or "string"

    Returns:
        Constructed prompt in requested format
    """

    #######################
    # WAITING FOR TRIGGER #
    #######################

    rag_context = ""
    try:
        if wait_for_trigger:
            print("[AGENT] Waiting for trigger...")
            check_start_time = time.time()

            def extended_wait_check(event: CtxEventBase) -> bool:
                """Check function dont trigger while we have messages to say or print"""

                def check_timeout():
                    return time.time() - check_start_time > 30.0

                # dont trigger while we have messages to say or print
                if len(ctx_handler.ctx_swarm["chat_queue"]) > 1 and not check_timeout():
                    return False
                if len(ctx_handler.ctx_swarm["tts_queue"]) > 1 and not check_timeout():
                    return False
                if default_event_check(event):
                    return True

            # Check for trigger events using handler
            event: Union[CtxEventBase, None] = ctx_handler.wait_for_sync(
                check=extended_wait_check, timeout=15.0, raise_timeout=False
            )
            event_id = -1
        else:
            event = None
            event_id = -1
        if event:
            print(f"[AGENT] Triggered by event: {event}")
            event_id = event.processing_timestamp  # ("processing_timestamp", -1)

        else:
            print("[AGENT] No trigger event found")
    except Exception as e:
        print(f"[AGENT] Error waiting for trigger event: {e}")
        event = None
        event_id = -1
    rag_context = ""
    try:
        if rag_model is not None:
            for_rag_events = []
            # get last event
            for_rag_events = ctx_handler.get_ctx_chat(
                dict_format=True, limit=3 if event is None else 2
            )
            if event is not None:
                for_rag_events = ctx_handler.get_ctx_chat(dict_format=True, limit=2)
                for_rag_events.append(event.to_dict())
            else:
                for_rag_events = ctx_handler.get_ctx_chat(dict_format=True, limit=3)
            if for_rag_events:
                rag_context = rag_model.explain(format_events_for_rag(for_rag_events))
            if not rag_context:
                rag_context = ""
            else:
                rag_context = "Some vocabulary explanation:\n\n" + rag_context + "\n\n"
            # print("RAG CONTEXT DEBUG", rag_context)
    except Exception as e:
        print(f"[AGENT] Error getting RAG context: {e}")
        rag_context = ""

    # Format context for prompt
    messages_dicts, mentioned_users = format_events_with_roles(
        # TODO untested
        ctx_handler.get_ctx_chat(
            validate=True, dict_format=True, limit=50
        ),  # self.ctx_swarm["ctx_chat"]
        trigger_event_id=event_id,
        return_mentioned_users=True,
    )

    prompt = construct_prompt(
        rag_context,
        tools,
        ctx_swarm=ctx_handler.ctx_swarm,
        chat_users=mentioned_users,
        # focused_user=,
        tool_use_format=tool_use_format,
    )

    personality = ctx_handler.ctx_swarm["states"].get(
        "personality", "streamer_abstract"
    )
    # TODO improve
    idea_suggestion = ""
    # chance 0.4
    if random.random() < 0.4:
        idea_suggestion = "\n" + get_random_idea(
            personality, False if "yandere" in personality else True
        )
    if goal is None:
        goal = DEFAULT_GOAL + "\n" + idea_suggestion
    else:
        goal = goal + "\n" + idea_suggestion
    goal_message = (
        f"""\n\n\n# === CONTROL MAINFRAME SUGGESTIONS ===\n{goal}""" if goal else ""
    )
    if len(messages_dicts) > 0:
        prompt += (
            "\n\n======= Last chat messages and other platform events START ======"
        )
        messages = create_chat_from_prompt(prompt)
        messages.extend(
            messages_dicts
            + create_chat_from_prompt(
                "======= Last chat messages and other platform events END ======"
                + goal_message,
                role="user",
            )
        )
    else:
        messages = create_chat_from_prompt(prompt + goal_message)

    # add image to main prompt if it is vision llm
    is_vision_llm = get_secret("CORE_LLM_MODEL_NAME") == get_secret(
        "VISION_LLM_MODEL_NAME"
    )
    if is_vision_llm:
        frame = get_actual_frame()
        if frame:
            messages.append(
                HumanMessage(
                    content=[
                        {
                            "type": "text",
                            "text": "Your current game screenshot (10 sec ago)",
                        },
                        {"type": "image_url", "image_url": {"url": frame}},
                        # or with base64: {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
                    ]
                )
            )
        else:
            print(
                "[PROMPT CONSTRUCTOR] Warning: vision LLM enabled, but no frame available, start OBS and turn on websocket"
            )

    thinking_llm = get_secret("CORE_LLM_REASONNING") != "NONE"  # for deepseek

    if unfinished_response:
        if thinking_llm:
            # unfinished_response = ""
            response_starting = ""
            unfinished_response_message = ""
            # unfinished_response_message = (
            #     "<think>"  # DEFAULT_UNFINISHED_REPSONSE_THINKING
            # )
        else:
            unfinished_response_message = unfinished_response + response_starting
        if unfinished_response_message:
            messages.extend(
                create_chat_from_prompt(
                    unfinished_response_message,
                    role="assistant",
                )
            )

    # add last hint for tool use format direct example:
    # if tool_use_format == "command"
    if output_format == "langchain":
        messages = convert_to_messages(messages)
    elif output_format == "string":
        return openai_chat_to_str(messages)
    return messages, response_starting
