import logging
import os
import queue
import sys
import time
import traceback
from queue import Queue
from threading import Thread
from typing import Dict

import requests

from data_schema.chat_structures import BasicFilterResults, FilterResults
from data_schema.ctx_structures import CtxSwarmType

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))


from config_schema.general import get_secret  # noqa: E402
from data_flow.filter_mistral import MistralFilter  # noqa: E402


class FilterDummy:
    def __init__(self, *args, **kwargs):
        self.filter_results: BasicFilterResults = BasicFilterResults(
            acceptable=True,
            reason="",
            judge=True,
            topics=[],
            score=0.0,
            filtered_text="",
        )

    def check_message(self, text: str, *args, **kwargs) -> BasicFilterResults:
        return self.filter_results.copy()

    def is_acceptable(self, text: str) -> bool:
        result = self.check_message(text)
        return result["acceptable"]


class FilterClient:
    def __init__(self, base_url: str = "http://localhost:22230"):
        self.base_url = base_url
        self.session = requests.Session()

    def check_message(self, text: str) -> BasicFilterResults:
        try:
            response = self.session.post(f"{self.base_url}/filter", json={"text": text})
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print("ALARM!!! FILTER NOT CONNECTED!!! FALLBACK TO NON-ACCEPTABLE!!!")
            traceback.print_exc()
            logger.error(f"Filter request failed: {e}")

            return {
                "acceptable": False,
                "reason": "FILTER_ERROR",
                "judge": True,
                "topics": [],
                "score": 0.0,
                "filtered_text": text,
            }

    def is_acceptable(self, text: str) -> bool:
        result = self.check_message(text)
        return result["acceptable"]


def ctx_filter_handler(ctx_swarm: CtxSwarmType):
    ctx_chat = ctx_swarm["ctx_chat"]
    tts_queue = ctx_swarm["tts_queue"]
    ctx_env = ctx_swarm["env"]
    filter_q_i = ctx_swarm["filter_input_queue"]
    filter_q_o = ctx_swarm["filter_output_queue"]
    old_ctx_chat_len = len(ctx_chat)
    print("[FILTER] STARTED FILTERING")
    while ctx_swarm["env"]["actived"]:
        print("[FILTER] ENTERING FILTER LOOP")
        try:

            # if queue_name in ["tts_queue"]:
            # old_len_tts_queue = -1
            if not ctx_env["filter_enabled"]:
                filter_client = FilterDummy()
                mistral_filter = FilterDummy()
                print("[FILTERS ARE DISABLED] Using dummy filters!!!")
            else:
                filter_client = FilterClient()
                mistral_filter = FilterClient()  # fallback to standart filter...
                # TODO add .env var for mistral filter and check this ON only when cool event
                # mistral_filter = MistralFilter()

            def full_filter_check(text: str) -> bool:
                # first basic filter, its faster
                filter_result = filter_client.check_message(text)
                if (
                    filter_result["acceptable"] is False
                    and filter_result.get("reason") == "BAD_WORD"
                ):
                    return False
                mistral_filter_result = mistral_filter.check_message(text)
                if mistral_filter_result:
                    pass
                    # print("[🟡 MISTRAL FILTER API DEBUG] RESULT", mistral_filter_result)
                if not mistral_filter_result.get("acceptable", True):
                    return False
                return True

            def filter_queue_handler():
                while ctx_env["actived"]:
                    try:
                        q_input = filter_q_i.get(timeout=3)
                        if q_input:
                            text = q_input["text"]
                            if text:
                                filter_type = q_input.get("filter_type", "basic")
                                filter_result: FilterResults
                                if filter_type == "mistral":
                                    filter_result = mistral_filter.check_message(text)
                                elif filter_type == "all":
                                    filter_result = {}
                                    filter_result["acceptable"] = full_filter_check(
                                        text
                                    )
                                else:
                                    # if filter_type == "basic":
                                    filter_result = filter_client.check_message(text)
                                filter_q_o.put(filter_result)
                    except queue.Empty:
                        pass
                    except Exception as e:
                        print(
                            f"[FILTER QUEUE HANDLER] Error processing filter queue: {e}"
                        )
                        traceback.print_exc()
                    time.sleep(0.02)

            queue_thread = Thread(target=filter_queue_handler, daemon=True).start()

            def tts_filter_handler():
                old_text_chunk = ""
                while ctx_env["actived"]:
                    text_chunk = ctx_swarm["voice"]["text_chunk"]
                    if text_chunk:  # and tts_queue[-1].get("text", "") != "interrupt":
                        if old_text_chunk != text_chunk:
                            interrupted = False
                            for i, msg in enumerate(tts_queue):
                                if (
                                    msg.get("text", "") == "interrupt"
                                    or msg.get("emotion", "") == "interrupt"
                                ):
                                    interrupted = True
                            if not interrupted:
                                if full_filter_check(text_chunk) is False:
                                    print("🔴 TTS Filtering, REJECTED " + text_chunk)
                                    with ctx_swarm["tts_queue_lock"]:
                                        tts_queue[:] = []
                                        tts_queue.append(
                                            {
                                                "text": "interrupt",
                                                "emotion": "interrupt",
                                            }
                                        )
                                else:
                                    print("🟢 TTS Filtering, ACCEPTED " + text_chunk)
                            # old_len_tts_queue = len(tts_queue)
                            old_text_chunk = text_chunk
                    time.sleep(0.05)

            tts_thread = Thread(target=tts_filter_handler, daemon=True).start()

            while ctx_env["actived"]:
                current_ctx_chat_len = len(ctx_chat)

                # Detect if ctx_chat has been cleared (current length < old length)
                if current_ctx_chat_len < old_ctx_chat_len:
                    print(
                        "[FILTER] Detected ctx_chat clearing, resetting length tracker"
                    )
                    old_ctx_chat_len = current_ctx_chat_len

                if (
                    current_ctx_chat_len > old_ctx_chat_len
                    and current_ctx_chat_len > 0
                    # and ctx_swarm["env"].get("filter_enabled", False)
                    # # need to handle this in other way!
                ):
                    old_ctx_chat_len = current_ctx_chat_len
                    # last_ctx_chat = ctx_chat[-1]
                    for last_ctx_chat in ctx_chat:
                        # print("🟡 Filtering, GOT QUEUE ITEM " + str(last_ctx_chat))
                        if last_ctx_chat.get("filter_results", None) is not None:
                            # print("🟡 Filtering, ALREADY FILTERED " + str(last_ctx_chat))
                            continue
                        last_msg = last_ctx_chat.get("msg", "")
                        msg_type = last_ctx_chat.get("type", "")
                        if last_msg and "chat" in msg_type:
                            user_str = last_ctx_chat.get("user", "")
                            msg_env = last_ctx_chat.get("env", "")
                            user = user_str
                            if not user_str:
                                user_str = ""
                            else:
                                user_str += " "
                            filter_result = {"acceptable": True}
                            # print(get_secret("RAZRABS").split(","))
                            # print(get_secret("BOT_NICKNAMES").split(","))
                            bypass_filtering = False
                            if (
                                user in get_secret("RAZRABS").split(",")
                                or msg_type == "system"
                                or msg_env == "system"
                                or "mc_exec" in msg_type
                            ):
                                bypass_filtering = True
                            else:
                                filter_result = filter_client.check_message(
                                    (user_str + last_ctx_chat["msg"]).strip()
                                )

                            if filter_result["acceptable"]:
                                print(
                                    f"🟢 Filter, ACCEPTED (bypass={str(bypass_filtering)}) '"
                                    + str(last_ctx_chat["msg"])
                                    + "'"
                                )
                                text = last_ctx_chat["msg"]
                            else:
                                text = f"""[MESSAGE IS FILTERED! Probably cause: {filter_result.get("reason", "BAD SLANG, BAD TOPICS]")}]"""  # + str(filter_result)
                                print(
                                    "🔴 Filter, REJECTED "
                                    + str(last_ctx_chat)
                                    + str(filter_result)
                                )
                            id = last_ctx_chat.get("processing_timestamp")
                            # filter_results["filtered_text"]
                            last_ctx_chat.update(
                                {
                                    "msg": text,
                                    "filter_results": filter_result,
                                }
                            )
                            # STOP WORKING WITHOUT ERRORS AFTER BAD MESSAGES SPAM =(((
                            # TODO INVESTIGATE
                            # HYPOTHESIS: CTX LOCK
                            # with ctx_swarm["ctx_chat_lock"]:
                            if True:
                                for i, chat_entry in enumerate(ctx_swarm["ctx_chat"]):
                                    if chat_entry.get("processing_timestamp") == id:
                                        try:
                                            ctx_swarm["ctx_chat"][i] = last_ctx_chat
                                            # if not filter_results["acceptable"]:
                                            break
                                        except Exception as error:
                                            print(
                                                "[FILTER UPDATE ERROR] Failed to update ctx_chat: ",
                                                error,
                                            )
                                            traceback.print_exc()
                time.sleep(0.02)
            queue_thread.join()
            tts_thread.join()
            print("[FILTER] EXITING FILTER LOOP")
        except Exception as e:
            print("[FILTER MAIN ERROR] STOPPING FILTER! ", e)
            print(traceback.print_exc())
            time.sleep(5)


if __name__ == "__main__":
    filter_client = FilterClient()

    test_cases = [
        "Привет, как дела?",
        "Привет как дела, лох?",
        "This is a test message",
        "Это тестовое сообщение",
        "Это тестовое сообщение",
    ]

    print("Starting filter tests...\n")

    for text in test_cases:
        print(f"Testing text: '{text}'")
        try:
            result = filter_client.check_message(text)

            print("Filter Results:")
            print(f"  Acceptable: {result['acceptable']}")
            print(f"  Reason: {result['reason']}")
            print(f"  Judge: {result['judge']}")
            print(f"  Topics: {result['topics']}")
            print(f"  Score: {result['score']}")
            print(f"  Filtered text: {result['filtered_text']}")
            print("-" * 50)

        except Exception as e:
            print(f"Error testing text: {e}")
            print("-" * 50)

        time.sleep(0.5)
