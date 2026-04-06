"""Format helper
EXTRA-CRUCIAL MODULE for eventlist-for-LLM formatting
All issues probably goes from here... =(

TODO СРОЧНО!!!
ADD EVENT MERGING!!
like if player says "hello" and "hello, how are you?" - merge it into one message
user: hello
how are you?

EXTRA HARD AND VERY NEED: OWN TOOL CALL MERGING!!!
TODO NEED NOW!!

like
Response:
```
!tool_call
!new tool call
!next tool call
```

"""

import copy
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Tuple, Union

from dateutil.parser import parse

if __name__ == "__main__":  # for one-file testing
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from agent.tools.tool_executor import format_tool_command
from config_schema.general import get_name
from data_schema.chat_structures import EventBase, MentionedUser
from data_schema.ctx_structures import CtxChatType
from data_schema.tool_structures import TOOL_COMMAND_FORMATS, ToolCommandFormats
from utils.time_helper import eztime, format_relative_time

# TODO deal with this usage...
# WE NEED SUPER-CENTRALIZE AND NON-MODULE USING THING WHERE WE WILL HAVE OUR NICKNAMES!!!
SELF_NAME = get_name()
"""
self name getting thoughts

what can you suggest for me to this problem for self nickname-to-modules providing.

it's a VERY complex repository.
there are couple of usernames and nicknames for multiple platforms, envs, servers, etc.

I need nickname getting function to be:
- NO-ANY-MODULE-DEPENDENT to use in every module without even THINKING for circular imports error
- ability to be changed at anytime and then automatically swapped in all modules using this nickname
- fast working
- VERY easy to use
- contain nicknames:
    - main default nickname (general)
    - platform nicknames: for minecraft, twitch, etc
    - complex scenarious:
        minecraft server different nicknames
Methods:
    get_own_nickname that returns simple main default nickname
    get_own_nickname(platform: str) that returns platform nickname
Additional
    get_own_nickname(event: EventBase) that returns nickname for EventBase on provided information
"""


def merge_user_events(events: Sequence[EventBase]) -> List[EventBase]:
    """Merges user events

    Args:
        events: should be a FULL DEEPCOPY of initial events

    Does this:
    ```
    10s ago [lexa] hello
    5s ago [lexa] how are you?
    ```

    ->

    ```
    5s ago [lexa] hello
    how are you?
    ```
    """
    merged_events = []
    for event in events:
        if not merged_events:
            merged_events.append(event)
            continue
        merging_event = merged_events[-1]
        event_user = event.get("user", False)

        if (
            # event_user
            event_user == merging_event.get("user")
            and event.get("msg")
            and merging_event.get("msg")
            and event.get("type") == merging_event.get("type")
        ):
            merged_event = event
            merged_event["msg"] = merging_event["msg"] + "\n" + event.get("msg", "")
            merged_events[-1] = merged_event
            # update last event with the merged information
        else:
            merged_events.append(event)
    return merged_events


def merge_tool_calls(
    events: Sequence[EventBase], tool_call_format: ToolCommandFormats
) -> List[EventBase]:
    """Merges tool calls

    Args:
        events: should be a FULL DEEPCOPY of initial events
    """
    merged_events: List[EventBase] = []
    merging_tool_call: Tuple[int, bool, EventBase] = None
    for i, event in enumerate(events):
        if event.get("type") == "tool_call":

            if not event.get("formatted_tool_command"):
                result = format_tool_command(
                    event["tool"], event["args"], tool_call_format
                )
                event["formatted_tool_command"] = result
                if event.get("result"):
                    event["formatted_tool_result"] = (
                        "Tool "
                        + event.get("tool", "")
                        + " returned {"
                        + str(event.get("result", "None"))
                        + "}"
                    )
                else:
                    event["formatted_tool_result"] = ""
                events[i] = event
            # another behaviour for speak tool
            if event.get("tool", "") == "speak":
                if tool_call_format == "text":
                    # should just add as regular assistant message, not a tool call
                    merged_events.append(
                        EventBase(
                            processing_timestamp=event["processing_timestamp"],
                            type="OVERRIDE_ASSISTANT_ROLE",
                            msg=event.get("formatted_tool_command", ""),
                            user=event["user"],
                            date=event["date"],
                        )
                    )
                    continue
                # dangerous fix like that... need another approach
                # we need to remove only result without affecting tool, but we can't
                # skip speak tool returnable...
                # if "True" in event.get("formatted_tool_result", ""):
                #     continue  # TODO UNTESTED
            # init events only after adding first formatted tool command
            is_first = False
            if not merged_events:
                merged_events.append(event)
                merging_tool_call = i, True, event
                continue
            if not merging_tool_call:
                merging_tool_call = i, True, event
            if merging_tool_call[1]:
                merging_event = merged_events[-1]
            else:
                is_first = True
                merging_event = event

            if (
                event.get("user") == merging_event.get("user")
                and event["type"] == merging_event.get("type")
                and not is_first
            ):
                event["multiple_tool_call"] = True
                # add special field for formatted multiple tool calls to easy use
                #

                merged_event = event
                try:
                    merged_event["formatted_tool_command"] = (
                        merging_event["formatted_tool_command"]
                        + TOOL_COMMAND_FORMATS[tool_call_format][
                            "multiple_tool_separator"
                        ]
                        + event["formatted_tool_command"]
                    )
                    if event["formatted_tool_result"]:
                        merged_event["formatted_tool_result"] = (
                            merging_event["formatted_tool_result"]
                            + "; "
                            + event["formatted_tool_result"]
                        )
                    # print(
                    #     "[DEBUG] Merged Tool formatted_tool_result:",
                    #     merged_event["formatted_tool_result"],
                    # )
                except KeyError as e:
                    print("[FORMAT HELPER] formatted_tool_command KeyError: ", e)
                    traceback.print_exc()
                    merged_event["formatted_tool_command"] = format_tool_command(
                        merged_event["tool"], merged_event["args"], tool_call_format
                    )
                    print("EVENT ===", event, "===merged_event ", merged_event)
                    print(
                        "EVENTS ====== ",
                        events,
                        " ============merged_events ",
                        merged_events,
                    )
                    print("=== TRACEBACK END ===")
                if merging_tool_call[1]:
                    merged_events[-1] = (
                        merged_event  # update last event with the merged information
                    )
                else:
                    merged_events.append(merged_event)

            else:
                merged_events.append(event)
            merging_tool_call = i, True, event
        else:
            merged_events.append(event)
            merging_tool_call = i, False, event
    final_events: List[EventBase] = []
    # add separately tool call result as a separate message
    for event in merged_events:
        if event.get("type") == "tool_call" and event.get("formatted_tool_result"):
            final_events.append(event)  # add existing tool call
            # add tool call result as a separate message from system chat
            tool_response_event = event.copy()
            tool_response_event["type"] = "system"
            tool_response_event["msg"] = (
                "Executing commands...\nResults:\n"
                + event.get("formatted_tool_result", "")
            )
            tool_response_event["isEvent"] = False
            for field in [
                "tool",
                "args",
                "formatted_tool_command",
                "formatted_tool_result",
                "description",
            ]:
                tool_response_event.pop(field, None)
            final_events.append(tool_response_event)
        else:
            final_events.append(event)
    return final_events


def timestamp_to_datetime(event: EventBase) -> datetime:
    timestamp = event.get("processing_timestamp", event["date"])
    if isinstance(timestamp, str):
        timestamp = parse(timestamp)
    elif isinstance(timestamp, datetime):
        pass
    elif isinstance(timestamp, (int, float)):
        timestamp = datetime.fromtimestamp(timestamp / 1000000000)  # os error if in ns
    return timestamp


def format_relative_time_event(event: EventBase) -> str:
    if event.get("text_timestamp", False):
        return event["text_timestamp"]
    event_dt = timestamp_to_datetime(event)
    return format_relative_time(event_dt)


def categorize_events_by_time(timestamp):
    current_time = datetime.now()

    # Convert timestamp to datetime if needed
    if isinstance(timestamp, (int, float)):
        event_time = datetime.fromtimestamp(timestamp)
    else:
        event_time = timestamp

    # Calculate time differences
    time_diff = current_time - event_time

    # Define thresholds
    RECENT_THRESHOLD = timedelta(seconds=10)
    RELEVANT_THRESHOLD = timedelta(minutes=1)

    # Categorize event
    if time_diff <= RECENT_THRESHOLD:
        return "recent"
    elif time_diff <= RELEVANT_THRESHOLD:
        return "relevant"
    else:
        return "old"


def group_events_by_time(events):
    categorized_events = {"recent": [], "relevant": [], "old": []}

    for event in events:
        category = categorize_events_by_time(event["timestamp"])
        categorized_events[category].append(event)

    return categorized_events


EVENTS_LIMIT = 30
RAG_EVENTS_LIMIT = 3
MAX_SYSTEM_MSG_PERCENT = 30


def limit_events(events: CtxChatType, max_events: int) -> CtxChatType:
    limited_events: CtxChatType = []
    for event in events:
        if len(limited_events) >= max_events:
            break
        limited_events.append(event)
    return limited_events


def filter_spam_events(events: CtxChatType, max_events: int) -> CtxChatType:
    # now = datetime.now()
    filtered_events: CtxChatType = []
    prev_timestamp = None
    spam_count = 0

    # Only limit system messages if we exceed the total events limit
    total_events = len(events)
    if total_events > max_events:
        max_system_msgs = int(max_events * MAX_SYSTEM_MSG_PERCENT / 100)
        non_parsed_msg_count = 0
    else:
        non_parsed_msg_count = None  # Flag to indicate no limiting needed
    event: EventBase
    tool_binded_events = set()
    for event in list(reversed(events)):
        if len(filtered_events) >= max_events:
            break
        event_add = True
        timestamp = timestamp_to_datetime(event)
        event_user = event.get("user", "")

        # Only apply system message limiting if we're over the limit
        if non_parsed_msg_count is not None:
            if not event_user:
                if non_parsed_msg_count >= max_system_msgs:
                    event_add = False
                non_parsed_msg_count += 1

        # Rest of spam checking logic
        if prev_timestamp is None:
            prev_timestamp = timestamp
        else:
            if prev_timestamp - timestamp <= timedelta(seconds=0.5):
                spam_count += 1
                if spam_count > 4:
                    event_add = False
                    prev_timestamp = timestamp
                # else:
                #     event_add = True
            else:
                spam_count = 0

            if spam_count <= 1:
                prev_timestamp = timestamp

        if event_user and event_user == SELF_NAME:
            event_type = event.get("type", "")
            if (
                event_type and "chat" in event_type
            ):  # not event.get("type", "tool_call")
                # print("[DEBUG NOT ADDING] FOUND SELF CHAT EVENT, SHOULD BE WRAPPED BY TOOL!")
                event_add = False

        if event_add:
            tool_bind_event_id = event.get("tool_bind_event_id", None)
            if tool_bind_event_id:
                tool_binded_events.add(tool_bind_event_id)
            filtered_events.append(event)
    filtered_events = [
        ev
        for ev in filtered_events
        if ev.get("processing_timestamp") not in tool_binded_events
    ]
    return list(reversed(filtered_events))  # unreverse the list


def preprocess_events(
    events: CtxChatType,
    tool_call_format: ToolCommandFormats = "command",
    max_events: int = EVENTS_LIMIT,
) -> CtxChatType:
    """Prepare and validate"""
    # print("[FORMAT HELPER LEN BEFORE FILTERING]", len(events))
    processed_events = limit_events(events, max_events * 2)
    # print("[FORMAT HELPER LEN AFTER LIMITING ONLY HARD EVENTS]", len(processed_events))
    processed_events = merge_tool_calls(processed_events, tool_call_format)
    # print("[FORMAT HELPER LEN AFTER MERGING TOOLS]", len(processed_events))
    processed_events = merge_user_events(processed_events)
    # print("[FORMAT HELPER LEN AFTER MERGING ALL]", len(processed_events))
    processed_events = filter_spam_events(processed_events, max_events)
    # print("[FORMAT HELPER LEN AFTER VALIDATING]", len(processed_events))
    return processed_events


def categorize_events(
    events: CtxChatType, trigger_id: int = -1
) -> Tuple[CtxChatType, CtxChatType, CtxChatType, EventBase]:
    now = datetime.now()
    recent = []
    relevant = []
    old = []

    # Find trigger event before main processing
    trigger_event = None
    if trigger_id != -1:
        try:
            for event in events:
                # Compare as integers to avoid type mismatches
                event_timestamp = int(event.get("processing_timestamp", 0))
                # print(trigger_id, event_timestamp, event_timestamp==trigger_id)
                if event_timestamp == int(trigger_id):
                    event["isTriggerEvent"] = True
                    trigger_event = [event]  # Wrap in list to match expected format
                    break
        except:
            pass

    # Categorize events by time
    for event in events:
        timestamp = timestamp_to_datetime(event)
        time_diff = now - timestamp

        if time_diff <= timedelta(seconds=10):
            recent.append(event)
        elif time_diff <= timedelta(minutes=1):
            relevant.append(event)
        else:
            old.append(event)

    return recent, relevant, old, trigger_event


""" 
        "date": "2025-02-26 05:58:32",
        "env": "minecraft",
        "filter_results": {
            "acceptable": true
        },
        "msg": "кошки мышки",
        "precision": "universal",
        "processing_timestamp": 1740524312025294600,
        "self": true,
        "server": "universal",
        "serverMode": "survival",
        "type": "chat",
        "user": "NetTyan"
"""


def format_time(seconds: float) -> str:
    return f"{seconds:.2f}s"


# def format_tool_call_event(event: dict, self_name: str = "NetTyan", tool_call_format: str = "command") -> str:


def format_single_event(
    event: EventBase,
    self_name: str = SELF_NAME,
    tool_call_format: ToolCommandFormats = "command",
) -> str:
    """Format single event to string for LLM prompt.

    Output: "[timestamp] User: message" or "[timestamp] Professor (ты): message"
    """
    ev = event.copy()
    ev_type_raw = ev.get("type", "")

    if ev_type_raw == "OVERRIDE_ASSISTANT_ROLE":
        return ev.get("msg", "")

    timestamp = format_relative_time_event(ev)
    user_str = ev.get("user", "") or "система"
    msg = ev.get("msg", "")

    if ev.get("self", False) or user_str == self_name:
        user_str = f"{self_name} (ты)"

    return f"[{timestamp}] {user_str}: {msg}"
    #             result+= "\n" + summary
    #     # for direct messages
    #         id_user = db.get_or_create_user(event)
    #         summary = db.get_user_diags(id_user)
    #         if summary:
    #             result+= "\n" + summary


def format_events_for_llm(
    events: list[dict], self_name=SELF_NAME, trigger_event_id=None
) -> str:
    if not events:
        return ""

    formatted_messages = format_events_with_roles(events, self_name, trigger_event_id)
    if not formatted_messages:
        return ""

    return "\n\n".join(
        f"[{msg['role']}] ===\n{msg['content']}" for msg in formatted_messages
    )


def format_events_for_rag(events: list[dict]) -> str:
    if events is not None:
        length = len(events)
        if length > 0:
            if length > RAG_EVENTS_LIMIT:  # limit events
                this_events = events[-RAG_EVENTS_LIMIT:]
            else:
                this_events = events
            rag_events = []
            for event in this_events:
                if event.get("user", False):
                    rag_events.append(event)
            fields = [
                [f"{v}" for k, v in event.items() if k and k in ["msg", "text"]]
                for event in this_events
            ]
            # fields.extend(
            #     [
            #         [f"{v}" for k, v in event.items() if k and k in ["user"]]
            #         for event in this_events
            #     ]
            # )
            rag_query = "\n".join(["\n".join(field) for field in fields])
            return rag_query
    return ""


def get_user_mentions(
    events: List[dict], user: str, events_limit: int = 80
) -> MentionedUser:
    mentioned_user: MentionedUser = MentionedUser()
    for event in events:
        if events_limit <= 1:
            break
        events_limit -= 1
        if event.get("user", False):
            if event["user"] == user:
                if not mentioned_user:
                    mentioned_user = MentionedUser(
                        {"name": user, "found_count": 0, "binded_events": []}
                    )
                mentioned_user["binded_events"].append(event)
                mentioned_user["found_count"] = mentioned_user["found_count"] + 1
                mentioned_user["last_activity_timestamp"] = event.get(
                    "processing_timestamp", -1
                )
                mentioned_user["last_activity_string"] = format_relative_time_event(
                    event
                )
    return mentioned_user


def format_events_with_roles(
    events: List[dict],
    self_name: str = SELF_NAME,
    trigger_event_id=-1,
    tool_call_format: ToolCommandFormats = "command",
    return_mentioned_users: bool = False,
) -> Union[List[dict], Tuple[List[dict], Dict[str, MentionedUser]]]:
    """
    Format events into a list of role-based messages.
    Returns list of dicts with 'role' and 'content' keys.
    """
    if return_mentioned_users:
        mentioned_users: dict[str, MentionedUser] = {}
    if not events:
        if return_mentioned_users:
            return [], mentioned_users
        return []

    # if len(events) > EVENTS_LIMIT:
    #     this_events = list(events[-EVENTS_LIMIT:]).copy()
    # else:
    #     this_events = events.copy()
    # DEEPCOPY
    this_events = copy.deepcopy(events)

    processed_events = preprocess_events(
        this_events, tool_call_format, max_events=EVENTS_LIMIT
    )

    recent, relevant, old, trigger_event = categorize_events(
        processed_events, trigger_event_id
    )
    formatted_messages = []

    # Helper function to add a system message (divider)
    def add_divider(text: str):
        divider_event = EventBase(
            user="system",
            msg=text,
            type="system",
            env="system",
            processing_timestamp=time.time_ns(),
            date=eztime(),
            text_timestamp="DIVIDER",
        )
        divider_formatted_text = format_single_event(
            event=divider_event, self_name=self_name, tool_call_format=tool_call_format
        )
        formatted_messages.append({"role": "user", "content": divider_formatted_text})

    # Helper function to add events from a category
    def add_events(category_events: list):
        for event in category_events:
            # role = "assistant" if event.get("user", "") == self_name else "user"
            ev_type = event.get("type", "")
            if (
                ev_type == "tool_call"
                and event.get("user", "") == self_name
                or ev_type == "OVERRIDE_ASSISTANT_ROLE"
                or event.get("self", False)
            ):
                role = "assistant"
            else:
                role = "user"
            formatted_event = format_single_event(
                event=event, self_name=self_name, tool_call_format=tool_call_format
            )
            if return_mentioned_users:
                user = event.get("user", False)
                if user:
                    if user in mentioned_users:
                        mentioned_user = mentioned_users[user]
                    else:
                        mentioned_user = MentionedUser(
                            {"name": user, "found_count": 0, "binded_events": []}
                        )
                    mentioned_user["binded_events"].append(event)
                    mentioned_user["found_count"] = mentioned_user["found_count"] + 1
                    mentioned_user["last_activity_timestamp"] = event.get(
                        "processing_timestamp", -1
                    )
                    mentioned_user["last_activity_string"] = format_relative_time_event(
                        event
                    )
                    mentioned_users[user] = mentioned_user
            formatted_messages.append({"role": role, "content": formatted_event})

    # Add old messages
    if old:
        add_divider("Ранее в диалоге:\n")
        add_events(old)

    # Add relevant messages
    if relevant:
        add_divider("Недавний контекст:\n")
        add_events(relevant)

    # Add recent messages
    if recent:
        add_divider("Текущий диалог:\n")
        add_events(category_events=recent)
    # add_divider("TRG search id=" + str(trigger_event_id) + ",result=" + str(trigger_event))
    # if trigger_event:
    #     add_divider(f"{SELF_NAME}, Event that triggered you:\n")
    #     add_events(trigger_event)
    # else:
    #     add_divider(
    #         f"{SELF_NAME}, You were triggered just by a time (maybe low game and chat activity)"
    #     )
    if return_mentioned_users:
        return formatted_messages, mentioned_users
    return formatted_messages


def openai_chat_to_str(chat_messages: list[dict]) -> str:
    """
    Convert format_events_with_roles output to string with proper spacing.
    System messages separated by triple newline, other messages by double newline.

    Args:
        chat_messages: List of dicts with 'role' and 'content' keys

    Returns:
        Formatted string representation
    """
    if not chat_messages:
        return ""

    result = []
    for msg in chat_messages:
        content = msg["content"]
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            if content and content[0].get("type", False) == "text":
                text = content["text"]
            else:
                continue
        else:
            continue
        if msg["role"] == "system":
            result.append(f"\n{msg['role']} =====\n{text}\n")
        else:
            role_rename = msg["role"]
            if role_rename == "assistant":
                role_rename = "you"
            result.append(f"{role_rename} ====\n{text}\n\n")

    return "".join(result).strip()


if __name__ == "__main__":

    from data_schema.structure_templates import CTX_CHAT_SAMPLE

    # print(format_events_with_roles(CTX_CHAT_SAMPLE))
    print(
        format_events_with_roles(CTX_CHAT_SAMPLE, trigger_event_id=1736021873965839300)
    )
    print("--- for rag ---")
    print(format_events_for_rag(CTX_CHAT_SAMPLE))
    event = CTX_CHAT_SAMPLE[0]
    timestamp = format_relative_time_event({"date": "22:19:15"})
    print(timestamp)
    print(time.time())
    timestamp = format_relative_time_event({"date": time.time_ns()})

    print("cur time", timestamp)

    print("========================")
    from utils.structure_helper import load_ctx_chat_sample

    ctx_chat = []
    load_ctx_chat_sample(realtime=True, new_ctx_chat=ctx_chat, add_time=0)
    while True:
        if len(ctx_chat) > 0:
            print("Latest event:", ctx_chat[-1])
            print(
                format_events_for_llm(
                    ctx_chat,
                    trigger_event_id=ctx_chat[-1].get("processing_timestamp", -1),
                )
            )
            print("--- for rag ---")
            # print(format_events_for_rag(ctx_chat))
            # print("================")
        time.sleep(3)
