import time
import traceback
from typing import Dict, List, Optional, Tuple

from agent.tools import tools_config
from agent.tools.control_tools import (
    _add_tool_error_log,
    _add_tool_result_log,
    _add_tool_run_log,
)
from agent.tools.dialogue_tools import _save_user_summary


def save_user_info(user: str, summary: str, *args, **kwargs) -> bool:
    """Saves information about user to your memory database

    Args:
        user: String, username that got your attention
        summary: String, summary of interest, VERY SHORT 5-10 words summary information why user is interesting.

    Use with caution, replaces previous summary if you seen it before
    """
    tool_name = "save_user_info"
    # TODO UNTESTED NEW FULL TEST NEED!!!
    # TODO add new agent
    if isinstance(summary, list) and len(summary) > 0:
        messageDict = summary[0]
        user = messageDict["user"]
        summary = messageDict["summary"]

    if args or kwargs:
        if not summary:
            summary = ""
        summary += " ".join(args)
        for key, value in kwargs.items():
            summary += f"{key}: {value}, "

    if len(summary) > 100:
        summary = summary[:80] + "..."
    call_id = _add_tool_run_log(tool_name, {"summary": summary, "user": user})
    print(
        f"***{tool_name}***",
        "->",
        user,
        "\nsummary:(",
        summary,
        ")",
    )
    try:

        if summary is None or not summary.strip():
            raise Exception("Summary is none")
        if user is None or not user.strip():
            raise Exception("User is none")

        result = _save_user_summary(user, summary)
        # Звук о внесении в бд
        # tools_config.ctx_swarm["fx_queue"].put("database_add")
        _add_tool_result_log(tool_name, {"returned": result, "call_id": call_id})
        return result
    except Exception as e:
        _add_tool_error_log(tool_name, {"returned": str(e), "call_id": call_id})
        return False


def _parse_text_tags(text: str, tag: str = "*") -> Tuple[str, List[str]]:
    """Parse tags from string text.

    Doing like:
    I "hi, how are you? *happy* *good* how are you? *sad* lol *bad*"
    O ["happy", "good", "sad", "bad"], "hi, how are you? how are you? lol"
    """

    tags = []
    cleaned_text = text
    try:
        if tag in text:
            cleaned_text = ""
            text_fragments = text.split(tag)
            inside_tag = False
            for text_fragment in text_fragments:
                if inside_tag:
                    tags.append(text_fragment)
                else:
                    cleaned_text += text_fragment
                inside_tag = not inside_tag
    except Exception as e:
        print(f"[CHAT PARSER] Error in _parse_text_tags: {e}")
        traceback.print_exc()
        tags = []
        cleaned_text = ""
    return cleaned_text, tags


def _parse_emotion(comment: str) -> tuple[str, str]:
    """Parse emotion from comment.

    Supports two formats:
    - New: (neutral) (happy) (thoughtful) (encouraging) at end of text
    - Legacy: *emotion* anywhere in text
    """
    import re
    # New format: (emotion) at end of text
    m = re.search(r'\((?:neutral|happy|thoughtful|encouraging|sad|angry|scared|whispering|disgusted|sarcastic)\)\s*$', comment)
    if m:
        emotion = m.group(0).strip('() \t')
        return emotion, comment[:m.start()].rstrip()
    # Legacy format: *emotion*
    clean_comment, tags = _parse_text_tags(comment, tag="*")
    if tags:
        emotion = tags[-1]
        comment = clean_comment
    else:
        emotion = ""
    return emotion, comment


# TODO ADD AVAILABLE EMOTION AS LIST!
def speak(comment: str, emotion: Optional[str] = None) -> bool:
    """Speak, comment overall situation with your voice.

    Args:
        comment:
            Str, commentary to speak with your mouth (VERY SHORT, NOT MORE than ~10 words)
        emotion:
            Str, emotion type for speech. Can be STRICT any of [`neutral`, `happy`, `sad`, `angry`, `scared`, `whispering`, `disgusted`, `sarcastic`, `thoughtful`, `encouraging`].

    You can use emotion in one comment argument like comment "hi, how are you? *happy*"
    """
    # tool_name = sys._getframe().f_code.co_name
    if not emotion:
        emotion, new_comment = _parse_emotion(comment)
        if not emotion:
            emotion = "neutral"
        else:
            comment = new_comment
    comment = comment.strip()
    if comment.startswith(">"):
        comment = comment[1:].strip()
    emotion = emotion.strip()
    call_id = _add_tool_run_log("speak", {"comment": comment, "emotion": emotion})
    try:
        print(f"***SPEAK TTS QUEUE***\n> {comment} *{emotion}*")
        if not comment and not emotion:
            raise Exception("[SPEAK TOOL] No comment and no emotion provided!")
        tools_config.ctx_swarm["tts_queue"].append(
            {"text": comment, "emotion": emotion}
        )
        _add_tool_result_log("speak", {"returned": True, "call_id": call_id})
        return True
    except Exception as e:
        _add_tool_error_log("speak", {"returned": str(e), "call_id": call_id})
        return False


def clear_queue(queue_name: str) -> str:
    "Internal Clear queue by name"
    # call_id = _add_tool_run_log("clear_queue", {"queue_name": queue_name})
    try:
        queue = tools_config.ctx_swarm[queue_name]
        if len(queue) > 0:
            queue[:] = []
            result = f"{queue_name} cleared"
            # _add_tool_result_log(
            #     "clear_queue", {"returned": result, "call_id": call_id}
            # )
            return result
        result = "Queue is already empty!"
        # _add_tool_result_log("clear_queue", {"returned": result, "call_id": call_id})
        return result
    except Exception as e:
        # _add_tool_error_log("clear_queue", {"returned": str(e), "call_id": call_id})
        return str(e)


def interrupt_chat() -> str:
    """Clears TTS queue. No args."""
    call_id = _add_tool_run_log("interrupt_chat", {})
    try:
        result = clear_queue("tts_queue")
        _add_tool_result_log("interrupt_chat", {"returned": result, "call_id": call_id})
        return result
    except Exception as e:
        _add_tool_error_log("interrupt_chat", {"returned": str(e), "call_id": call_id})
        return str(e)


def interrupt_voice() -> str:
    """Stops current speech pronunciation (voice). No args.
    USE ONLY WHEN YOUR CURRENT SPEECH IS MORE INTERESTING
    """
    call_id = _add_tool_run_log("interrupt_voice", {})
    try:
        print("***VOICE STOPPED REQUESTED***")
        tools_config.ctx_swarm["tts_queue"].append(
            {"text": "interrupt", "emotion": "interrupt"}
        )
        result = clear_queue("tts_queue")
        _add_tool_result_log(
            "interrupt_voice", {"returned": result, "call_id": call_id}
        )
        return result
    except Exception as e:
        _add_tool_error_log("interrupt_voice", {"returned": str(e), "call_id": call_id})
        return str(e)


def wait(seconds: int) -> bool:
    """Wait for a number of seconds.
    Args:
        seconds: (int) Number of seconds to wait before doing any actions. Cannot be more than 10.
    """
    call_id = _add_tool_run_log("wait", {"seconds": seconds})
    try:
        if seconds <= 10:
            time.sleep(seconds)
            _add_tool_result_log("wait", {"returned": True, "call_id": call_id})
            return True
        else:
            time.sleep(10)
            _add_tool_result_log("wait", {"returned": False, "call_id": call_id})
            return False
    except Exception as e:
        _add_tool_error_log("wait", {"returned": str(e), "call_id": call_id})
        return False
