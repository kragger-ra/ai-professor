from typing import Any, OrderedDict, TypedDict, get_type_hints


def auto_convert_value(value: str, target_type: type) -> Any:
    """Convert string value to target type"""
    if target_type == bool:
        return bool(value) if value.lower() != "false" else False
    return target_type(value)


def parse_with_hints(
    data: dict[str, str], typed_dict_class: type[dict], raise_errors=False
) -> dict:
    """Parse dictionary using TypedDict hints"""
    hints = get_type_hints(typed_dict_class)
    result_dict = {}
    for key in hints.keys():
        try:
            result_dict[key] = auto_convert_value(data[key], hints[key])
        except (IndexError, KeyError, ValueError, TypeError, AttributeError) as e:
            if raise_errors:
                raise e
    return typed_dict_class(result_dict)


class PlayerStatus(TypedDict):
    name: str
    position: str
    health: float
    distance: float
    hand_item: str
    ground_block: str
    is_looking_at_you_prob: float
    in_combat: bool
    recently_attacked: bool
    recently_damaged: bool
    weapon_threat: str
    avoiding: bool
    attacking: bool
    attackable: bool
    gamemode: str
    godmode: bool
    is_operator: bool


def parse_player_status(player_status: dict[str, str]) -> PlayerStatus:
    """Parsing player status got from java map"""
    return parse_with_hints(player_status, PlayerStatus)


def primitivize_nearby_players(
    nearby_players: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Py4j (Java) types to simple pythonic types"""
    result = []
    for player_status in nearby_players:
        primitive_player_status = {str(k): str(v) for k, v in player_status.items()}
        result.append(primitive_player_status)
    return result


def parse_nearby_players(nearby_players: list[dict[str, str]]) -> list[PlayerStatus]:
    """Parsing nearby players status got from java map"""
    result = []
    for player_status in nearby_players:
        result.append(parse_player_status(player_status))
    return result


def nearby_players_to_map(
    nearby_players: list[PlayerStatus],
) -> OrderedDict[str, PlayerStatus]:
    """Convert nearby players list to map"""
    result_dict = OrderedDict()
    for player in nearby_players:
        result_dict[player["name"]] = PlayerStatus(player)
    return result_dict


def parse_nearby_players_dict(
    nearby_players: dict[str, dict[str, str]],
) -> dict[str, PlayerStatus]:
    """Parsing nearby players status got from java map"""
    result_dict = {}
    for player_name, player_status in nearby_players.items():
        result_dict[player_name] = parse_player_status(player_status)
    return result_dict


def get_nearby_players(ctx_swarm) -> dict[str, PlayerStatus]:
    """Get nearby players status"""
    return nearby_players_to_map(ctx_swarm["game"]["nearby_players"])


def format_task_chain(ctx_swarm) -> str:
    ctx_game = ctx_swarm["game"]
    HELP_MSG = (
        "You can try to: speak (ask operator for help), run specific rejoin / "
        "lobby actions. You cannot run minecraft commands since not in game now."
    )
    NOT_CONNECTED_MSG = "Cant connect to minecraft executor agent =(" + "\n" + HELP_MSG
    task_chain = NOT_CONNECTED_MSG
    if ctx_game["ingame"]:
        task_chain = ctx_game.get("task_chain", NOT_CONNECTED_MSG)
    return task_chain
