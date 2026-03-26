# -*- coding: utf-8 -*-
"""
Minecraft tools for Baritone-like agent and Minecraft chat commands.

TODO:
- add chat status / inner command cooldowns / last calls statistics
- implement checking tools like @check block / @check player
"""

import os
import traceback
from typing import Dict, TypedDict

from agent.tools import tools_config
from agent.tools.control_tools import (
    _add_tool_error_log,
    _add_tool_event_waiter,
    _add_tool_result_log,
    _add_tool_run_log,
)
from data_schema.chat_structures import ToolEventWaiter
from data_schema.structure_templates import REPO_RESOURCE_PATH
from utils.minecraft_helper import PlayerStatus, get_nearby_players
from utils.prompt_helper import yaml_load

queue_send = tools_config.queue_send

TASK_COMMANDS_MAP = {
    "askpeace": "gesture",
    "walkthrough": "game walkthrough",
    "speedrun": "game walkthrough",
    "gamer": "game walkthrough",
    "skywars": "game sw",
    "sky_wars": "game sw",
    "wars": "game sw",
    "sky": "game sw",
    "sw": "game sw",
    "murdermystery": "game mm",
    "mm": "game mm",
    "murder": "game mm",
    "murder_mystery": "game mm",
    "mystery": "game mm",
    "shiftnearest": "t shift",
    "shift": "t shift",
    "breed": "t shift",
    "duck": "t shift",
    "adult": "t shift",
    "fuck": "t shift",
    "love": "t shift",
    "kiss": "t shift",
    "pokebutt": "t shift",
    "yandere": "t combat",
    "follow": "t follow",
    "find": "t follow",
    "grave": "t grave",
    "build": "t build",
    "stop": "forget",
    "sign": "t sign",
    "give": "t give",
    "get": "t get",
    "goto": "t goto",
    "hunt": "pursue",
    "kill": "pursue",
    "chase": "t punk",
    "attack": "pursue",
    "combat": "pursue",
    "beat": "pursue",
    "punk": "pursue",
    "damage": "pursue",
    "remove": "pursue",
    "strike": "pursue",
    "fight": "pursue",
    "reconnect": "stop",  # TODO ADD reconnect / rejoin =(
    "tp": "t pearl",
    "pearl": "t pearl",
    "enderpearl": "t pearl",
    "shoot": "t shoot",
    "bow": "t shoot",
    "build_grave": "t grave",
    "place_sign": "t sign",
    "smash": "t test mace",
}

SERVER_COMMANDS_MAP = {
    "rejoin": "hub",
    "exit": "hub",
    "leave": "hub",
    "stop": "hub",
    "request help": "mm m spawn AgressiveTeacher",
}

# not implemented yet
WHITELIST_COMMANDS = []
WHITELIST_ACTIONS = []
BLACKLIST_COMMANDS = [
    # "spawn",
    "ignore",
    "unignore",
    "stop",
    "reload",
    "restart",
    "gamerule",
    # "setblock",
]
BLACKLIST_ACTIONS = []  # ["stop", "game"]

# removed from commands for now
"""
        `/spawn` - teleport on spawn zone
        `/lobby` - exit current minigame / go to lobby (works only on minigame servers) 
"""

MC_COMMAND_PREFIX = "/"


MC_ROFL_COMMANDS = ["mute", "ban", "emute", "ignore", "voteban", "kick", "votemute"]


def _add_chat_event_waiter(call_id: int) -> bool:
    """Add default chat event waiter"""
    if call_id:
        return _add_tool_event_waiter(
            call_id,
            ToolEventWaiter(
                timeout=0.4,
                match_events=[{"type": "chat"}],
                # return_format=[{"field": "msg", "before": "", "after": "", "add_empty": False}]
            ),
        )  # match_events=[{"type": "chat"}]))
    return False


def _add_agent_event_waiter(call_id: int) -> bool:
    """Add default agent event waiter"""
    if call_id:
        return _add_tool_event_waiter(
            call_id,
            ToolEventWaiter(
                timeout=5,
                match_events=[
                    {"env": "minecraft", "type": "mc_executor_log", "isEvent": True}
                ],
                return_format=[
                    {
                        "field": "description",
                        "before": "",
                        "after": "",
                        "add_empty": False,
                    }
                ],
            ),
        )
    return False


def get_nearby_players_info() -> str:
    """
    Get list of nearby players.

    Returns:
        str info of players nearby
    """

    return ""


def get_player_status(player: str) -> PlayerStatus:
    """
    Get player status by name.
    Args:
        player: String, name of player.

    Returns:
        PlayerStatus: Dictionary with player status fields.
    """
    # FAR TODO add pipeline getting precise from minebridge minebridge_query_queue.put("get_player_status", player)

    near = get_nearby_players(tools_config.ctx_swarm)

    if len(near) > 1:  # self
        for p in near:
            if p["name"] == player:
                return p
    return {}


def _is_rofl_command(command: str) -> bool:
    return False  # disabled this...
    for rofl_cmd in MC_ROFL_COMMANDS:
        if command.startswith(rofl_cmd):
            return True
    return False


# TODO EXTRA VARIOUS!!!
# move command examples logic from docstring to something other


def minecraft_command(command: str) -> bool:
    """
    Runs minecraft server standart commands (do the /command in game).

    Args:
        command: String, text one of minecraft server ingame command.
    """
    call_id = _add_tool_run_log("minecraft_command", {"command": command})
    command_prefix = MC_COMMAND_PREFIX
    try:
        command = command.strip()
        if command and len(command) > 0:
            if command[0] == "/":
                command = command[1:]
            if command[0] == "@":  # mda...
                return agent_action(command[1:])
        if command:
            if command in list(SERVER_COMMANDS_MAP.keys()):
                command = SERVER_COMMANDS_MAP[command]

            if len(command) > 5:
                if _is_rofl_command(command):
                    # DISABLED CMD, with just chat !cmd like a rofl
                    command_prefix = "!"
                    # tools_config.ctx_swarm["fx_queue"].put("banword")
                elif command.startswith("ban"):
                    try:
                        # tools_config.ctx_swarm["fx_queue"].put("banword")
                        command = command.replace("ban", "tempban")
                        command = command.split(" ")
                        nick = command[1]
                        reason = " ".join(command[2:])

                        command = "tempban " + nick + " 20s " + reason
                        print("[EXECUTING BAN COMMAND]", command)
                    except Exception as e:
                        print(f"Error while parsing ban command: {e}")
                        traceback.print_exc()

            final_split = command.split(" ")
            if len(final_split) > 0:
                command_name = final_split[0].lower()
                if command_name in BLACKLIST_COMMANDS:
                    print(
                        "[MC CMD TOOL] TRIED TO RUN BLACKLISTED "
                        + command_name
                        + " COMMAND!"
                    )
                    _add_tool_result_log(
                        "minecraft_command",
                        {"returned": "Command blacklisted", "call_id": call_id},
                    )
                    return False

            if len(command) > 200:
                command = command[:200]

            result = queue_send(
                "chat_queue", [command_prefix + command], ignore_queue=True
            )
            _add_tool_result_log(
                "minecraft_command", {"returned": "Command sent", "call_id": call_id}
            )
            _add_chat_event_waiter(call_id)
            return result
    except Exception as e:
        _add_tool_error_log(
            "minecraft_command", {"returned": str(e), "call_id": call_id}
        )
    return False


def minecraft_command_tool_status() -> str:
    """
    Get status of the minecraft command tool. Returns the server relevant commands that can be executed
    TODO: should show server chat/command cooldows
    """

    server_ip = tools_config.ctx_swarm["game"].get("server", "")

    # dict: key = command name, value = command patterns with description
    command_patterns: Dict[str, str] = yaml_load(
        os.path.join(
            REPO_RESOURCE_PATH, "Customization", "minecraft_command_patterns.yml"
        )
    )

    # dict: key = server ip, value = dict[command patterns list, description]
    server_bank: Dict[str, Dict[str, str]] = yaml_load(
        os.path.join(REPO_RESOURCE_PATH, "Customization", "minecraft_server_bank.yml")
    )

    command_examples = ""
    if not server_ip:
        server_ip = "default"
    if server_ip and server_ip in server_bank:
        command_examples = ""
        server_entry = server_bank[server_ip]
        server_command_patterns = server_entry.get("commands", [])
        for command_pattern in server_command_patterns:  # e.g. administrative
            pattern_examples = command_patterns.get(command_pattern, "")
            if pattern_examples:
                command_examples += f"\n{command_pattern} commands:\n{pattern_examples}"
        # TODO ideally put logic in command_description key, and overall info put somewhere near separated server info description
        base_description = server_entry.get("description", "")
        commands_description = server_entry.get("commands_description", "")
        description = (
            (base_description + "\n" + commands_description)
            if base_description
            else commands_description
        )
        if description:
            return (
                f"{command_examples}\n"
                f"Current server ip - {server_ip}. "
                f"Description: {description}"
            )
    return command_examples


def agent_action_tool_status() -> str:
    """
    Get status of the minecraft agent action tool.

    Returns:
        str, the list of server relevant actions that can be executed.
    """
    server_ip = tools_config.ctx_swarm["game"].get("server", "")
    print("DEBUG SERVER IP +=======" + server_ip)
    action_patterns: Dict[str, str] = yaml_load(
        os.path.join(
            REPO_RESOURCE_PATH, "Customization", "minecraft_action_patterns.yml"
        )
    )

    server_bank: Dict[str, Dict[str, str]] = yaml_load(
        os.path.join(REPO_RESOURCE_PATH, "Customization", "minecraft_server_bank.yml")
    )

    action_examples = ""
    if not server_ip:
        server_ip = "default"
    if server_ip and server_ip in server_bank:
        server_entry = server_bank[server_ip]
        server_action_patterns = server_entry.get("actions", [])
        for action_pattern in server_action_patterns:
            pattern_examples = action_patterns.get(action_pattern, "")
            if pattern_examples:
                action_examples += f"\n{action_pattern} actions:\n{pattern_examples}"
        description = server_entry.get("actions_description", "")
        if description:
            return f"{action_examples}\nCurrent server ip - {server_ip}. Description: {description}"
    return action_examples


# TODO add command chains like:
# @game murder -> disconnect -> join mysteryworld -> mm mode


def agent_action(action: str) -> bool:
    """
    Runs minecraft Baritone agent task executor action.

    Args:
        action: String, text of action that should be executed using your automatic minecraft agent based on Baritone pathfinder and ierarchical task chain system.

    Action examples:
    Use when situation is relevant. For example @strike when target has no weapon or low hp, and @askpeace when you has no weapon or low hp.
    <player> should be a string, simple valid player nickname WITHOUT any brackets or other enclosing or non-latin symbols.

    """
    # , @status removed, agent not need it
    call_id = _add_tool_run_log("agent_action", {"action": action})
    try:
        action = action.strip()
        if action and len(action) > 0:
            if action[0] == "@":
                action = action[1:]
            if action[0] == "/":  # mda...
                return minecraft_command(action[1:])
        if action:
            splitted_command = action.split(" ")
            if len(splitted_command) > 1:
                command_name = splitted_command[0].lower()
                command_args = splitted_command[1:]
                if command_name in list(TASK_COMMANDS_MAP.keys()):
                    if command_name == "love":
                        command_args.append("forward")
                    elif command_name == "askpeace":
                        command_args.append("disagree")
                    command_name = TASK_COMMANDS_MAP[command_name]
                action = command_name + " " + " ".join(command_args)
            else:
                if action in list(TASK_COMMANDS_MAP.keys()):
                    action = TASK_COMMANDS_MAP[action]
            final_split = action.split(" ")
            if len(final_split) > 0 and final_split[0] == "t":
                final_split = final_split[1:]
            if len(final_split) > 0:
                command_name = final_split[0].lower()
                if command_name in BLACKLIST_ACTIONS:
                    print(
                        "[MC ACT TOOL] TRIED TO RUN BLACKLISTED "
                        + command_name
                        + " ACTION!"
                    )
                    _add_tool_result_log(
                        "agent_action",
                        {"returned": "Agent action not sent", "call_id": call_id},
                    )
                    return False

            if len(action) > 200:
                action = action[:200]
            result = queue_send("chat_queue", ["@" + action], ignore_queue=True)
            _add_tool_result_log(
                "agent_action", {"returned": "Agent action sent", "call_id": call_id}
            )
            # INVESTIGATE WHY NOT WORKING!
            _add_agent_event_waiter(call_id)
            # _add_tool_event_waiter(
            #     call_id,
            #     tool_event_waiter=ToolEventWaiter(
            #         timeout=3,
            #         match_events=[{"type": "mc_executor_log"}],
            #         # {"env": "minecraft", "type": "mc_executor_log", "isEvent": True}
            #         # return_format=[{"field": "msg", "before": "", "after": "", "add_empty": False}]
            #     ),
            # )
            # TODO, need to check first output from autoclef logs
            # _add_tool_event_waiter
            return result
    except Exception as e:
        _add_tool_error_log("agent_action", {"returned": str(e), "call_id": call_id})
    return False


MC_CONTROL_TOOLS = [agent_action, minecraft_command]
