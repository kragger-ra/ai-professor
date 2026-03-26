"""Data host module.
This module contains tools for managing data flow

Should contain:
command-line interface to use tools

Auto-clearing ctx chat when too big

Hosting command-line system query (should be added as a field implemented in ctx_handler)
any agent tool usage like "!tool"
"""

import json
import time
from threading import Thread
from typing import List, OrderedDict

from agent.tools.tool_executor import execute_tools
from data_flow.ctx_handler import CtxHandler
from data_schema.chat_structures import CtxEventBase
from data_schema.tool_structures import ToolBankType
from utils.debug import bcolors


class CtxHost:
    def __init__(self, ctx_handler: CtxHandler, tool_bank: ToolBankType):
        """HOST for all context infrastructure.

        Features:
            command-line interface support
            auto-clearing context chat to manage size

        Args:
            ctx_handler: ctx handler from command handling
            tool_bank: tool_bank from tools_config

        Critical:
            This class should be a singleton for one ctx_swarm instance.
        """
        self.max_ctx_chat_size = 700
        self.ctx_handler = ctx_handler
        self.ctx_swarm = ctx_handler.ctx_swarm
        self.tool_bank = tool_bank
        self.started = False
        self.threads: List[Thread] = []
        self.start()

    def start(self):
        # singleton check
        self.this_lock = self.ctx_swarm.get("ctx_host_lock")
        if self.this_lock is None:
            self.started = False
        else:
            if self.this_lock.acquire(False):
                self.started = True
                # host checkers start
                self.ctx_chat_size_handler_thread = Thread(
                    target=self._ctx_chat_size_handler
                )
                self.ctx_chat_size_handler_thread.start()
                self.threads.append(self.ctx_chat_size_handler_thread)
                self.command_handler_thread = Thread(
                    target=self._internal_command_handler
                )
                self.command_handler_thread.start()
                self.threads.append(self.command_handler_thread)

                self.tool_event_waiter_thread = Thread(target=self._tool_event_waiter)
                self.tool_event_waiter_thread.start()
                self.threads.append(self.ctx_chat_size_handler_thread)
            else:
                self.this_lock.acquire()
                self.started = False

    def _tool_event_waiter(self):
        """TODO NEW UNTESTED
        DANGEROUS!!!
        """
        # WORKS TOO BAD / NOT WORKS / WORKS ?????
        # TODO FIND OUT WHY PROBLEMATIC!!!

        # we need to preserve order
        tool_event_waiter_threads: OrderedDict[int, Thread] = {}
        while self.ctx_swarm["env"]["actived"] and self.started:
            # if  > 0:
            # Step 1. Check events that are tools
            events = self.ctx_handler.get_ctx_chat(
                validate=True, dict_format=True, limit=20
            )
            for event in events:
                # print("[][] " + str(event))
                try:
                    event_id = event["processing_timestamp"]
                except Exception as e:
                    print(
                        "[CTX HOST] "
                        + e
                        + " FOUND EVENT WITH PROCESSING TIMESTAMP!!! >>>"
                        + json.dumps(event, indent=2)
                        + "<<<"
                    )
                    continue
                if (
                    event.get("type") == "tool_call"
                    and event_id not in tool_event_waiter_threads
                ):
                    # Step 2. Check if this tool event has field "tool_event_waiter"
                    waiter = event.get("tool_event_waiter", False)
                    if waiter:
                        match_events = waiter.get("match_events", [])
                        if match_events:
                            tool_call_id = event_id
                            tool_event_waiter_timeout = waiter.get("timeout", 3)
                            return_format = waiter.get("return_format", [])

                            # Step 3. Create a check function to check if any event is matching to our event
                            def check_tool_event(checking_event: CtxEventBase):
                                checking_event_dict = checking_event.to_dict()
                                for match_event in match_events:
                                    for key in match_event:
                                        if checking_event_dict.get(
                                            key
                                        ) != match_event.get(key):
                                            return False
                                return True

                            # Step 4. Start a new thread next logic:
                            # - checking event with our function using ctx_handler
                            # Giving timeout time - 3 seconds (or field tool_event_waiter_timeout)
                            # - if event is matching - change "result" field of tool event to the new event output
                            # - provided check function within a timeout

                            def tool_event_waiter_handler():
                                # print("[][][WAITER_STARTED] ", tool_call_id)
                                found_event_base = self.ctx_handler.wait_for_sync(
                                    check=check_tool_event,
                                    timeout=tool_event_waiter_timeout,
                                    raise_timeout=False,
                                )
                                # print("!!!![][] ", found_event_base)
                                tool_checking_result = {}
                                # time spent, something may change, re-check this is actual
                                if (
                                    found_event_base
                                    and tool_call_id in tool_event_waiter_threads
                                ):
                                    found_event = found_event_base.to_dict()
                                    # changing tool output based on return_format and returned event
                                    full_str_result = ""
                                    if return_format:
                                        for format_item in return_format:
                                            field = format_item.get("field", "")
                                            before = format_item.get("before", "")
                                            after = format_item.get("after", "")
                                            add_empty = format_item.get(
                                                "add_empty", False
                                            )
                                            field_value = found_event.get(field, "")
                                            if field_value or add_empty:
                                                full_str_result += (
                                                    before + field_value + after
                                                )
                                    else:
                                        # just pick the "msg" field of message and add to current tool result
                                        found_event_msg = found_event.get("msg", "")
                                        full_str_result = found_event_msg

                                    if full_str_result:
                                        tool_checking_result = {
                                            "result": full_str_result,
                                            "tool_bind_event_id": found_event[
                                                "processing_timestamp"
                                            ],
                                        }
                                    else:
                                        tool_checking_result = {
                                            "result": "Result capturing timeout"
                                        }
                                tool_checking_result["tool_event_waiter"] = None
                                self.ctx_handler.modify_message(
                                    tool_call_id, tool_checking_result
                                )

                                # if tool_call_id in tool_event_waiter_threads:
                                #    del tool_event_waiter_threads[tool_call_id]
                                deleted = tool_event_waiter_threads.pop(
                                    tool_call_id, None
                                )
                                if deleted:
                                    print(
                                        f"[TOOL_EVENT_WAITER] Thread for {tool_call_id} cleaned up."
                                    )

                            event_checking_thread = Thread(
                                target=tool_event_waiter_handler, daemon=True
                            )
                            tool_event_waiter_threads[tool_call_id] = (
                                event_checking_thread
                            )
                            event_checking_thread.start()
            # end for
            time.sleep(0.1)

    def _ctx_chat_size_handler(self):
        while self.ctx_swarm["env"]["actived"] and self.started:
            self._ctx_chat_size_check()
            time.sleep(2.4)

    def _ctx_chat_size_check(self):
        """Auto-clearing ctx chat when too big"""
        # TODO PERFORM AUTO-SAVE ALL REMOVING CTX CHAT DATA TO FILE
        if len(self.ctx_swarm["ctx_chat"]) > self.max_ctx_chat_size:
            # clear first occurrences
            # TODO replace this s..t to add all values to new list and then clear, than replace old list with new
            # get last elements
            new_ctx_chat = self.ctx_swarm["ctx_chat"][
                -(self.max_ctx_chat_size - self.max_ctx_chat_size // 2) :
            ]
            # clear
            print("[TEST] ACQUIRING CTX CHAT LOCK")
            with self.ctx_swarm["ctx_chat_lock"]:
                self.ctx_swarm["ctx_chat"][:] = []
            print("[TES] EXIT CTX CHAT LOCK, CLEARED CTX CHAT")
            # add new elements
            for ctx_chat_entry in new_ctx_chat:
                self.ctx_swarm["ctx_chat"].append(ctx_chat_entry)
            print(
                "[CTX HOST UNTESTED] !!!!!! Ctx chat cleared to maintain max size."
                + "!!!\n" * 6
            )

    def _internal_command_handler(self):
        while self.ctx_swarm["env"]["actived"] and self.started:
            cmd_q = self.ctx_swarm.get("internal_command_queue", False)
            if cmd_q:
                command_record = cmd_q.get()
                print("[CMD HANDLER] GOT COMMAND! ", command_record)
                command = command_record.get("command", False)
                if command:
                    self.query_tools(command)
            time.sleep(0.1)

    def query_tools(self, command: str):
        """Process command for tool usage."""
        execute_tools(
            command,
            generator_callable=lambda x: print(
                bcolors.OKCYAN + str(x) + bcolors.ENDC, flush=True, end=""
            ),
            # generator_callable=lambda x: print("|" + str(x.content), flush=True, end=""),
            # tool_exec_callable=default_exec_callaback,
            tool_bank=self.tool_bank,
            max_tool_run_cnt=5,
            allow_disabled_tools=True,
        )

    def _join_threads(self):
        """Shutdown all threads gracefully."""
        for thread in self.threads:
            if thread.is_alive():
                thread.join()

    def shutdown(self):
        if self.started:
            self.started = False
            self._join_threads()
            try:
                self.this_lock.release()
            except Exception as e:
                print(f"[CTX HOST] Error releasing lock: {e}")

    def __del__(self):
        self.shutdown()

    def __exit__(self):
        self.shutdown()
