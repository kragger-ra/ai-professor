"""
ctx_chat_handler
--the simpliest approach of ctx_handler_hard--

this class should handle only ctx_chat variable

Should have functions

- remove ctx chat element basing on processing id
- modify ctx chat element
- SMART add ctx chat element with checking for repetitions
- ability to SAVE and LOAD (restore) the ctx chat approach from json

- ability to wait_for on ctx chat trigger, like for event (write a determined trigger type class in chat structures, for example only messge or message with nick or event with nick)

wait_for event with timeout

"""

# TODO FINISH STARTED NEW EVENT VALIDATING CHECK

import asyncio
import json
import os
import threading
import time
from typing import Callable, Optional, Sequence, Union

from data_schema.chat_structures import (
    CtxEventBase,
    EventBase,
    default_event_check,
)
from data_schema.ctx_structures import CtxSwarmType
from data_schema.event_convert import convert_to_chat_message

DUPLICATE_LIMIT_CHECK = 8  # 30 was


class CtxHandler:
    def __init__(self, ctx_swarm: CtxSwarmType):
        self.ctx_swarm: CtxSwarmType = ctx_swarm
        self.ctx_chat: Sequence[EventBase] = self.ctx_swarm["ctx_chat"]
        self.ctx_chat_lock = self.ctx_swarm["ctx_chat_lock"]
        self._event_waiters: Sequence[EventWaiter] = []
        self._sync_event_waiters: Sequence["SyncEventWaiter"] = []
        self.duplicate_limit: int = DUPLICATE_LIMIT_CHECK
        self._running = True
        self._last_length = len(self.ctx_chat)
        self._checker_thread = threading.Thread(target=self._check_changes, daemon=True)
        self._checker_thread.start()
        self.processing_events = []

    def _convert_to_event(self, message: Union[EventBase, str]) -> CtxEventBase:
        """Convert any message to CtxEventBase"""
        return convert_to_chat_message(message)

    def _to_dict(self, event: CtxEventBase) -> EventBase:
        """Convert CtxEventBase to dict for storage"""
        return event.to_dict()

    def get_ctx_chat(
        self, validate=True, dict_format=False, limit=100, raw=False
    ) -> Union[Sequence[CtxEventBase], Sequence[EventBase]]:
        """Get all messages as CtxEventBase objects
        all functions not yet implemented
        """
        if raw:
            return self.ctx_chat
        validated_ctx_chat = []

        if len(self.ctx_chat) >= limit:
            check_ctx_chat = list(self.ctx_chat[-limit:])
        else:
            check_ctx_chat = list(self.ctx_chat)
        for msg in check_ctx_chat:
            event = self._convert_to_event(msg)
            if not validate or self._is_valid_event(event):
                if dict_format:
                    validated_ctx_chat.append(msg)
                else:
                    validated_ctx_chat.append(event)

        return validated_ctx_chat

    def _get_event_duplicate(self, chat_message: CtxEventBase) -> int:
        """Gets event is duplicate else returns -1"""
        for existing_event in self.get_ctx_chat(
            validate=False, limit=self.duplicate_limit, raw=False
        ):
            if chat_message.processing_timestamp == existing_event.processing_timestamp:
                return existing_event.processing_timestamp
            if chat_message.additional_fields.get(
                "type", ""
            ) and chat_message.additional_fields.get("type", "") in [
                "kill",
                "death",
                "damage",
            ]:
                return -1  # saving all damage events
            if (
                existing_event.type == chat_message.type
                and existing_event.additional_fields.get("isEvent")
                == chat_message.additional_fields.get("isEvent")
                and existing_event.additional_fields.get("description")
                == chat_message.additional_fields.get("description")
                and existing_event.user == chat_message.user
                and existing_event.msg == chat_message.msg
            ):
                return existing_event.processing_timestamp
            # if (
            #     existing_event.type == chat_message.type
            #     and existing_event.msg == chat_message.msg
            #     and existing_event.user == chat_message.user
            # ):
            #     return existing_event.processing_timestamp
        return -1

    def add_message(
        self, message: Union[CtxEventBase, EventBase, str], duplicate_check=True
    ) -> bool:
        """Add a new message to ctx_chat with duplicate checking"""
        if isinstance(message, CtxEventBase):
            chat_message = message
        else:
            chat_message = self._convert_to_event(message)
        if not chat_message.processing_timestamp:
            chat_message.processing_timestamp = time.time_ns()
        if duplicate_check:
            duplicate_id = self._get_event_duplicate(chat_message)
        else:
            duplicate_id = -1
        is_duplicate = True if duplicate_id != -1 else False
        if not is_duplicate:
            # with self.ctx_chat_lock:
            # maybe lock only on modify / removing?
            self.ctx_chat.append(self._to_dict(chat_message))
            return True
        else:
            existing_event_dict = self.get_event_by_id(duplicate_id, dict_format=True)
            if existing_event_dict is not None:
                new_event_dict = chat_message.to_dict()
                repetitions = existing_event_dict.get("repeat", 1)
                new_event_dict["repeat"] = repetitions + 1
                existing_event_dict.update(new_event_dict)
                self.modify_message(duplicate_id, existing_event_dict)
            return False

    def remove_message(self, processing_timestamp: int) -> bool:
        """Remove message by its processing timestamp"""
        for i, msg in enumerate(self.ctx_chat):
            event = self._convert_to_event(msg)
            if event.processing_timestamp == processing_timestamp:
                with self.ctx_chat_lock:
                    self.ctx_chat.pop(i)
                return True
        return False

    def get_event_by_id(
        self, processing_timestamp: int, dict_format=False
    ) -> Union[CtxEventBase, dict, None]:
        """Get event by its processing timestamp
        NOTE: LIMITS BY 100!!!
        """
        if processing_timestamp != -1:
            for msg in reversed(
                self.get_ctx_chat(validate=False, dict_format=dict_format)
            ):
                if dict_format:
                    if msg.get("processing_timestamp") == processing_timestamp:
                        return msg
                else:
                    event = self._convert_to_event(msg)
                    if event.processing_timestamp == processing_timestamp:
                        return event
        return None

    def modify_message(self, processing_timestamp: int, updates: EventBase) -> bool:
        """Modify existing message by its processing timestamp"""
        # iterating reversed to get FROM last message to FIRST, like chat[3], chat[2], ...
        # for i, d in enumerate(self.ctx_chat):
        # print(i, d["processing_timestamp"])
        for i, msg_dict in list(reversed(list(enumerate(self.ctx_chat)))):
            # we need to get NON REVERSE index
            # i = i
            # print(i, msg_dict["processing_timestamp"])
            if msg_dict.get("processing_timestamp") == processing_timestamp:
                msg_dict.update(updates)
                with self.ctx_chat_lock:
                    self.ctx_chat[i] = msg_dict
                return True
        return False

    def save_to_json(self, filepath: str):
        """Save ctx_chat to a JSON file"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            messages = [
                msg.to_dict() if isinstance(msg, CtxEventBase) else msg
                for msg in self.ctx_chat
            ]
            json.dump(messages, f, ensure_ascii=False, indent=2, default=str)

    @classmethod
    def load_from_json(cls, filepath: str) -> "CtxHandler":
        """Load ctx_chat from a JSON file"""
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            messages = [convert_to_chat_message(msg) for msg in data]
            return cls(messages)

    def _check_event_waiters(self, message: Union[EventBase, CtxEventBase]):
        """Check if message matches any waiting conditions"""
        event = (
            self._convert_to_event(message) if isinstance(message, dict) else message
        )
        # Check async waiters
        for waiter in self._event_waiters[:]:
            try:
                print(f"DEBUG: Checking message {message} against waiter condition")
                if waiter.check_condition(event):
                    print(f"DEBUG: Condition matched for message {message}")
                    self._event_waiters.remove(waiter)
                    waiter.set_result(event)
            except Exception as e:
                print(f"DEBUG: Error in check_condition: {e}")

        # Check sync waiters
        for waiter in self._sync_event_waiters[:]:
            try:
                if waiter.check_condition(event):
                    self._sync_event_waiters.remove(waiter)
                    waiter.set_result(event)
            except Exception as e:
                print(f"DEBUG: Error in sync check_condition: {e}")

    def _check_changes(self):
        """Background thread to monitor ctx_chat changes"""
        while self._running:
            current_length = len(self.ctx_chat)

            # Detect if ctx_chat has been cleared (current length < previous length)
            if current_length < self._last_length:
                print(
                    f"[CTX HANDLER] Detected ctx_chat clearing from {self._last_length} to {current_length}, resetting event tracking"
                )
                # Reset the processing_events for items that might no longer exist
                self.processing_events = []
                # Update last length to the new smaller value
                self._last_length = current_length

            if current_length > self._last_length:
                # New messages appeared
                for i in range(self._last_length, current_length):
                    try:
                        message = self.ctx_chat[i]
                        event = self._convert_to_event(message)
                        # event.processing_timestamp
                        if self._is_valid_event(event):
                            self._check_event_waiters(event)
                        else:
                            self.processing_events.append(
                                (i, event.processing_timestamp)
                            )
                    except IndexError:
                        # Sequence might have changed during iteration
                        pass
                self._last_length = current_length

            if len(self.processing_events) > 0:
                # TODO add removing for events that are processing too long
                for idx, timestamp in self.processing_events[
                    :
                ]:  # Use a copy for safe iteration
                    event = None
                    try:
                        event_dict = self.ctx_chat[idx]
                        if event_dict.get("processing_timestamp") != timestamp:
                            raise IndexError
                        else:
                            event = event_dict
                    except IndexError:
                        for event_dict in reversed(self.ctx_chat):
                            if event_dict.get("processing_timestamp") == timestamp:
                                event = event_dict
                                break
                    if event is not None:
                        event = self._convert_to_event(event)
                        if self._is_valid_event(event):
                            self._check_event_waiters(event)
                            self.processing_events.remove(
                                (
                                    idx,
                                    timestamp,
                                )
                            )
            threading.Event().wait(0.05)  # Small delay to prevent CPU overuse

    def _is_valid_event(self, event: CtxEventBase) -> bool:
        """Validate event before adding to ctx_chat"""
        if event is None:
            return False
        # TODO TEMPORTALLY DISABLE, IT SPAMS SO MUCH!!!
        if event.type:
            if event.type == "mc_executor_event":
                return False
            # if event.type == "mc_executor_log":
            #     return True
            # print("!!!! mc_executor_log TROUBLESHOOT DEBUG !!!!! JFKSDJG DSLJKGJKL SDG")

        if event.additional_fields.get("filter_results", None):
            # if event.type == "mc_executor_log":
            #     print("!!!! mc_executor_log TROUBLESHOOT DEBUG !!!!! JFKSDJG DSLJKGJKL SDG")
            return True
        return False

    def _get_base_event_check(
        self, check: Callable[[CtxEventBase], bool]
    ) -> Callable[[CtxEventBase], bool]:
        def new_check(event: CtxEventBase) -> bool:
            return self._is_valid_event(event) and check(event)

        return new_check

    async def wait_for(
        self,
        check: Callable[[CtxEventBase], bool],
        timeout: Optional[float] = None,
    ) -> CtxEventBase:
        """Wait for a message matching the check condition"""
        # Check existing messages first
        # THIS IS NO NEED IN WAIT FOR! IT'S JUST CHECK EXISTENCE
        # for msg in reversed(self.get_ctx_chat(validate=False)):
        #     try:
        #         if check(msg):
        #             return msg
        #     except Exception as e:
        #         print(f"DEBUG: Error checking existing message: {e}")
        waiter = EventWaiter(self._get_base_event_check(check))
        self._event_waiters.append(waiter)
        try:
            return await asyncio.wait_for(waiter.wait(), timeout)
        except asyncio.TimeoutError:
            self._event_waiters.remove(waiter)
            raise

    def wait_for_sync(
        self,
        check: Optional[Callable[[CtxEventBase], bool]] = None,
        timeout: Optional[float] = None,
        raise_timeout=True,
    ) -> Optional[CtxEventBase]:
        """Synchronous version of wait_for"""
        if check is None:
            check = default_event_check
        waiter = SyncEventWaiter(self._get_base_event_check(check))
        self._sync_event_waiters.append(waiter)
        try:
            result = waiter.wait(timeout)
            return result
        except TimeoutError:
            self._sync_event_waiters.remove(waiter)
            if raise_timeout:
                raise
        finally:
            if waiter in self._sync_event_waiters:
                self._sync_event_waiters.remove(waiter)

    def shutdown(self):
        """Clean shutdown of the checker thread"""
        self._running = False
        if self._checker_thread.is_alive():
            self._checker_thread.join(timeout=1.0)

    def __exit__(self):
        self.shutdown()

    def __del__(self):
        """Ensure thread is stopped on object destruction"""
        self.shutdown()


class EventWaiter:
    def __init__(self, check: Callable[[CtxEventBase], bool]):
        self.check = check
        self.future = asyncio.get_event_loop().create_future()

    def check_condition(self, message: CtxEventBase) -> bool:
        try:
            return self.check(message)
        except Exception as e:
            print(f"DEBUG: Error in waiter check_condition: {e}")
            return False

    def set_result(self, message: CtxEventBase):
        if not self.future.done():
            self.future.set_result(message)

    async def wait(self) -> CtxEventBase:
        return await self.future


class SyncEventWaiter:
    def __init__(self, check: Callable[[CtxEventBase], bool]):
        self.check = check
        self.event = threading.Event()
        self.result = None

    def check_condition(self, message: CtxEventBase) -> bool:
        try:
            return self.check(message)
        except Exception as e:
            print(f"DEBUG: Error in sync waiter check_condition: {e}")
            return False

    def set_result(self, message: CtxEventBase):
        self.result = message
        self.event.set()

    def wait(self, timeout: Optional[float] = None) -> CtxEventBase:
        if not self.event.wait(timeout):
            raise TimeoutError("Wait for event timed out")
        return self.result
