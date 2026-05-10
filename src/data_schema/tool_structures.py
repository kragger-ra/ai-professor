from typing import Any, Callable, Dict, List, Literal, Optional, Set, TypedDict, Union

from langchain_core.tools import StructuredTool

ToolCommandFormats = Literal["command", "python", "text"]
ToolFormats = Literal["langchain", "smolagents", "autogpt", "agnet"]
SpeakEmotion = Literal[
    "neutral",
    "happy",
    "sad",
    "angry",
    "scared",
    "whispering",
    "disgusted",
    "sarcastic",
]
SpeakEmotions: Set[SpeakEmotion] = {
    "neutral",
    "happy",
    "sad",
    "angry",
    "scared",
    "whispering",
    "disgusted",
    "sarcastic",
}

ToolArgs = Dict[Union[str, int], Any]


class ToolRecord(TypedDict):
    name: str
    cooldown: float = -1
    cooldown_id: Optional[str]
    description: str
    last_call: Optional[float]  # timestamp
    call_count: int
    success_count: int
    error_count: int
    disabled: bool
    args: Dict[str, Any]
    function: Callable[..., Any]
    get_status: Optional[Callable[[], str]]
    tool: StructuredTool


class VoteData(TypedDict):
    topic: str
    option: str
    voter_name: str


class VoteWinner(TypedDict):
    winner: str
    votes: int


class VoteTopicData(TypedDict):
    options: List[str]
    votes: Dict[str, int]  # option, count
    voters: Dict[str, str]  # name, option
    winner: VoteWinner


ToolBankType = Dict[str, ToolRecord]
VotesBank = Dict[str, VoteTopicData]


class ToolResponseFormatsTypeHints(TypedDict):
    """Type hint dict for separators in tool response formatting"""

    multiple_start: str
    multiple_end: str
    single_start: str
    single_end: str
    multiple_tool_separator: str


CommandFormatsTypeHints = Dict[str, ToolResponseFormatsTypeHints]
TOOL_COMMAND_FORMATS: CommandFormatsTypeHints = {
    "command": {
        "multiple_start": "```commands\n",
        "multiple_end": "\n```",
        "single_start": "```commands\n",
        "single_end": "\n```",
        "multiple_tool_separator": "\n",
    },
    "text": {
        "multiple_start": "",
        "multiple_end": "",
        "single_start": "",
        "single_end": "",
        "multiple_tool_separator": "\n",
    },
    "python": {
        "multiple_start": "```py\n",
        "multiple_end": "```",
        "single_start": "`",
        "single_end": "`",
        "multiple_tool_separator": "\n",  # just new line of code
    },
}
