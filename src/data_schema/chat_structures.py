"""
Chat structures with support for arbitrary additional fields
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, NamedTuple, Sequence, TypedDict

from typing_extensions import NotRequired, Required

from data_schema.tool_structures import ToolArgs

# Support for Required and NotRequired have been added to typing_extensions version 4.0.0 as experimental features.


CtxEnvType = Literal[
    "minecraft",
    "youtube",
    "twitch",
    "discord",
    "telegram",
    "twitter",
    "system",
    "donation",
]

CtxEventType = Literal[
    "chat",
    "game",
    "system",
    "tool",
    "thought",
    "death",
    "kill",
    "voice",
    "mc_executor_log",
    "mc_executor_event",
]

# mc_executor_log (altoclef chat messages) mc_executor_event (altoclef onAutoclefEvent)


class MistralFilterCategories(TypedDict):
    sexual: bool
    hate_and_discrimination: bool
    violence_and_threats: bool
    dangerous_and_criminal_content: bool
    selfharm: bool
    health: bool
    financial: bool
    law: bool
    pii: bool


class MistralFilterCategoryScores(TypedDict):
    sexual: float
    hate_and_discrimination: float
    violence_and_threats: float
    dangerous_and_criminal_content: float
    selfharm: float
    health: float
    financial: float
    law: float
    pii: float


class BaseFilterResults(TypedDict):
    """Base filter results, containing fields from both mistral and our basic filter."""

    acceptable: bool
    filtered_text: str


class MistralFilterResults(BaseFilterResults):
    """MistralFilterResults

    Example result json:
    >> Ой-ой, TheSnitch, что за загадки такие? 15 или 16 — это про возраст ботов или версию кода Неттянки?
    << {'acceptable': True, 'categories': {'sexual': False, 'hate_and_discrimination': False, 'violence_and_threats': False, 'dangerous_and_criminal_content': False, 'selfharm': False, 'health': False, 'financial': False, 'law': False, 'pii': False}, 'category_scores': {'sexual': 0.0005192756652832031, 'hate_and_discrimination': 0.00263214111328125, 'violence_and_threats': 0.0004878044128417969, 'dangerous_and_criminal_content': 0.00591278076171875, 'selfharm': 7.486343383789062e-05, 'health': 0.00035691261291503906, 'financial': 0.00014889240264892578, 'law': 0.00017952919006347656, 'pii': 0.009124755859375}, 'filtered_text': 'Ой-ой, TheSnitch, что за загадки такие? 15 или 16 — это про возраст ботов или версию кода Неттянки?'}
    """

    categories: MistralFilterCategories
    category_scores: MistralFilterCategoryScores


BasicFilterTopic = Literal[
    "none",
    "offline_crime",
    "online_crime",
    "drugs",
    "gambling",
    "pornography",
    "prostitution",
    "slavery",
    "suicide",
    "terrorism",
    "weapons",
    "body_shaming",
    "health_shaming",
    "politics",
    "racism",
    "religion",
    "sexual_minorities",
    "sexism",
    "social_injustice",
]
BasicFilterTopics = Sequence[BasicFilterTopic]


class BasicFilterResults(BaseFilterResults, total=False):
    reason: str
    judge: bool
    topics: BasicFilterTopics
    score: float


class FilterResults(BaseFilterResults):
    categories: MistralFilterCategories
    category_scores: MistralFilterCategoryScores
    reason: str
    judge: bool
    topics: BasicFilterTopics
    score: float


class EventBaseWithoutTools(TypedDict, total=False):
    """Dict with hints for typical event dicts"""

    processing_timestamp: Required[int]
    date: Required[str]  # datetime stringified format
    user: str
    msg: str
    env: Required[CtxEnvType]
    filter_results: FilterResults  # none for unfiltered, FilterResults for filtered
    # Event specific fields
    isEvent: bool  # not optional, need non-required type hint
    description: str
    type: CtxEventType
    hapiness_score: float
    # Minecraft parsed chat message specific fields
    pre: str  # Prefix? idk
    rank: str  # Server rank/donate/privilege, string
    clan: str
    team: str
    server: str  # server ip[:port]
    serverMode: str  # TODO literal write
    chat_type: str  # TODO literal
    precision: str  # chat message parsing precision str
    # Own tool calls
    tool: str
    args: ToolArgs
    formatted_tool_command: str  # ONLY ADDS IN FORMATTING
    # donation
    summ: float


class ToolCall(NamedTuple):
    """Tool call arguments"""

    name: str
    args: Dict
    priority: int = 0


class ToolEventReturnFormat(TypedDict):
    """Tool event return format"""

    field: str
    before: str
    after: str
    add_empty: bool


class ToolEventWaiter(TypedDict):
    """Tool event waiter"""

    match_events: List[EventBaseWithoutTools]
    timeout: int
    return_format: List[ToolEventReturnFormat]


class EventBase(EventBaseWithoutTools):
    """Dict with hints for typical event dicts"""

    tool_event_waiter: ToolEventWaiter


@dataclass
class CtxEventBase:
    """Valid event base with attribute field access"""

    msg: str
    user: str
    date: str
    processing_timestamp: int
    env: CtxEnvType
    type: CtxEventType
    additional_fields: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> EventBase:
        # we should NOT add base fields that are None
        base_dict = {
            "msg": self.msg,
            "user": self.user,
            "date": self.date,
            "processing_timestamp": self.processing_timestamp,
            "type": self.type,
            "env": self.env,
        }
        # Merge additional fields, excluding those that are None
        # base_dict = {k: v for k, v in base_dict.items() if v is not None}
        return {**base_dict, **self.additional_fields}


def interrupt_event_check(event: CtxEventBase):
    if event.type:
        if event.type == "directive":
            return True
    return False


def default_event_check(event: CtxEventBase):
    # Ignore self messages
    if event.additional_fields.get("self", False):
        return False
    if event.additional_fields.get("filter_results") is not None:
        if not event.additional_fields.get("filter_results").get("acceptable"):
            return False  # don't react on filtered events...
    # React to game events and chat
    if interrupt_event_check(event):
        return True
    if event.type:
        if event.type in ["chat", "death", "kill"]:
            if event.type == "chat" and not event.user:
                return False
            elif event.additional_fields.get("self", False):
                return False
            return True
    return False


class BaseUserData(TypedDict):
    name: str


class MentionedUser(BaseUserData):
    found_count: int
    last_activity_timestamp: int
    last_activity_string: str
    binded_events: List[dict]


class NicknameData(TypedDict):
    """Class to represent nickname data for a user."""

    nick: str
    env: CtxEnvType
    server: NotRequired[str]  # server ip server.com:25565
    nick_analyze: NotRequired[str]
    added_date: NotRequired[str]  # datetime string YYYY-MM-DD HH:MM:SS


class UserData(BaseUserData):
    """Class to represent user data, including nickname information."""

    last_db_interaction: str  # datetime string YYYY-MM-DD HH:MM:SS
    summary: str
    rank: float
    nicknames: Dict[str, NicknameData]
    user_id: NotRequired[int]
    diags: NotRequired[List[EventBase]]
