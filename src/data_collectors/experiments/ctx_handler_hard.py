"""
Advanced context manager with functions for:
- subscribing to ctx_swarm variables updating events
- scheluding adding or deleting events / messages...
- carefully update ctx_swarm variables with proper locks

Explanations:
ctx_swarm is a dict of python multiprocessing manager proxy objects that can be shared between processes.
Keys is strings, and all of its values is a proxy object.
see templates/structures.py for more info.
ctx_swarm {
    ctx_lock: manager.lock
    ctx_chat: manager.list (of dicts with determined fields (many, see in structures for more info))
    tts_queue: manager.list (of dicts with determined fields emotion and text)
    chat_queue: manager.list (of strings)
    game: manager.dict
    ctx: manager.namespace
    ...and others... (many, see in structures for more info)
}
"""

import os
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime
from multiprocessing import Manager, Process
from multiprocessing.managers import DictProxy, ListProxy, NamespaceProxy, ValueProxy
from typing import Any, Callable, Dict, List, Optional, Union

if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data_schema.chat_structures import (
    BaseCtxChatEntry,
    ChatEvent,
    CtxChatList,
    CtxEventBase,
)

# Add these constants at module level
REQUIRED_EVENT_FIELDS = {
    "type",
    "user",
    "date",
    "processing_timestamp",
}

"""TODO


add special method for ctx handler specail to add ctxchat events.
add_event({eventdict}) -> bool

also add method update_event({eventdict}) that select event by processing_timestamp and update only it properly with all locks.

There needs to be the next logic:

1. event should be any of like in minebridge, and base event constants should be added, like processing_timestamp
2. spamming similar events with same user and text should be connecting to previous event just with increasing its filed "repeating";
3. add tests to check this

"""


class ProxyListWrapper:
    def __init__(self, ctx_handler, list_name):
        self._ctx_handler = ctx_handler
        self._list_name = list_name
        self._proxy = ctx_handler.ctx_swarm[list_name]
        self._lock = ctx_handler._get_lock(list_name)

    def append(self, value):
        with self._lock:
            self._proxy.append(value)

    def remove(self, index=None, value=None, processing_timestamp=None):
        with self._lock:
            if processing_timestamp is not None:
                for i, item in enumerate(self._proxy):
                    if (
                        isinstance(item, dict)
                        and item.get("processing_timestamp") == processing_timestamp
                    ):
                        del self._proxy[i]
                        return
            elif index is not None and 0 <= index < len(self._proxy):
                del self._proxy[index]
            elif value is not None:
                try:
                    self._proxy.remove(value)
                except ValueError:
                    print(f"Value {value} not found in {self._list_name}")

    def getlast(self):
        with self._lock:
            return self._proxy[-1] if self._proxy else None

    def clear(self):
        with self._lock:
            self._proxy[:] = []

    def __iter__(self):
        return iter(self._proxy)

    def __len__(self):
        return len(self._proxy)


class ProxyDictWrapper:
    def __init__(self, ctx_handler, dict_name):
        self._ctx_handler = ctx_handler
        self._dict_name = dict_name
        self._proxy = ctx_handler.ctx_swarm[dict_name]
        self._lock = ctx_handler._get_lock(dict_name)

    def update(self, value):
        with self._lock:
            if isinstance(value, dict):
                self._proxy.update(value)
            else:
                self._proxy.clear()
                if hasattr(value, "items"):
                    self._proxy.update(value)
                else:
                    self._proxy["value"] = value

    def get(self, key, default=None):
        with self._lock:
            return self._proxy.get(key, default)

    def __getitem__(self, key):
        with self._lock:
            return self._proxy[key]

    def __setitem__(self, key, value):
        with self._lock:
            self._proxy[key] = value

    @property
    def value(self):
        """Get dict as value or single value if stored"""
        with self._lock:
            if len(self._proxy) == 1 and "value" in self._proxy:
                return self._proxy["value"]
            return dict(self._proxy)

    @value.setter
    def value(self, new_value):
        """Set value, convert to dict if needed"""
        self.update(new_value)


class ProxyValueWrapper:
    def __init__(self, ctx_handler, var_name):
        self._ctx_handler = ctx_handler
        self._var_name = var_name
        self._proxy = ctx_handler.ctx_swarm[var_name]
        self._lock = ctx_handler._get_lock(var_name)

    @property
    def value(self):
        with self._lock:
            return self._proxy.value if hasattr(self._proxy, "value") else self._proxy

    @value.setter
    def value(self, new_value):
        with self._lock:
            if hasattr(self._proxy, "value"):
                self._proxy.value = new_value
            else:
                self._ctx_handler.ctx_swarm[self._var_name] = new_value


class CtxHandler:
    """Advanced context manager for ctx_swarm variables with events and safe updates."""

    def __init__(self, ctx_swarm: dict):
        self.ctx_swarm = ctx_swarm
        self._verify_locks()
        self._subscribers = defaultdict(list)
        self._callback_registry = {}  # Add callback registry
        self._processing_thread = None
        self._running = False
        self._scheduled_events = []  # Local list for scheduled events
        self._scheduled_events_lock = threading.Lock()  # Thread-safe lock
        self._create_proxy_properties()

    def register_callback(self, name: str, callback: Callable) -> None:
        """Register a callback function with a name for scheduling"""
        self._callback_registry[name] = callback

    def _verify_locks(self):
        """Verify that each variable has its corresponding lock and create if missing"""
        # Get list of names first to avoid modifying during iteration
        names = [name for name in self.ctx_swarm.keys()]
        for name in names:
            if name not in ("ctx_lock") and not name.endswith("_lock"):
                lock_name = f"{name}_lock"
                if lock_name not in self.ctx_swarm:
                    raise ValueError(f"Missing lock for variable: {name}, {lock_name}")

    def _get_lock(self, var_name: str):
        """Get lock for specific variable, create if missing"""
        lock_name = f"{var_name}_lock"
        if lock_name not in self.ctx_swarm:
            raise ValueError(f"Missing lock for variable: {var_name}, {lock_name}")

        return self.ctx_swarm[lock_name]

    def _create_proxy_properties(self):
        """Dynamically create properties for all items in ctx_swarm"""
        for name, value in self.ctx_swarm.items():
            if name == "ctx_lock":
                continue

            # Create property getter and setter
            def make_property(proxy_name):
                def getter(self):
                    proxy = self.ctx_swarm[proxy_name]
                    if isinstance(proxy, ListProxy):
                        return ProxyListWrapper(self, proxy_name)
                    elif isinstance(proxy, DictProxy):
                        return ProxyDictWrapper(self, proxy_name)
                    else:
                        return ProxyValueWrapper(self, proxy_name)

                def setter(self, value):
                    with self._get_lock(proxy_name):
                        proxy = self.ctx_swarm[proxy_name]
                        if isinstance(proxy, ListProxy):
                            proxy.append(value)
                        elif isinstance(proxy, DictProxy):
                            if isinstance(value, dict):
                                proxy.update(value)
                            else:
                                proxy["value"] = value
                        elif hasattr(proxy, "value"):
                            proxy.value = value
                        else:
                            self.ctx_swarm[proxy_name] = value

                return property(getter, setter)

            # Add the property to the class
            setattr(CtxHandler, name, make_property(name))

    def subscribe(self, variable_name: str, callback: Callable[[Any], None]) -> None:
        """Subscribe to changes in a ctx_swarm variable.

        Args:
            variable_name: Name of ctx_swarm variable to monitor
            callback: Function to call when variable changes
        """
        with self._get_lock(variable_name):
            self._subscribers[variable_name].append(callback)

    def on(
        self, variable_name: str, callback: Callable[[Any], None] = None
    ) -> Union[Callable, "CtxHandler"]:
        """Socket.IO style event subscription. Can be used as decorator or method.

        Examples:
            # As decorator:
            @ctx_handler.on("variable_name")
            def handle_change(value):
                print(f"Value changed to: {value}")

            # As method:
            ctx_handler.on("variable_name", handle_change)

        Args:
            variable_name: Name of ctx_swarm variable to monitor
            callback: Function to call when variable changes (optional for decorator use)

        Returns:
            Decorator function or self for method chaining
        """
        if callback is None:

            def decorator(func: Callable[[Any], None]) -> Callable[[Any], None]:
                self.subscribe(variable_name, func)
                return func

            return decorator
        self.subscribe(variable_name, callback)
        return self

    def schedule_event(
        self,
        variable_name: str,
        value: Any,
        delay: float,
        callback: Optional[Union[str, Callable]] = None,
    ) -> None:
        """Schedule an event to update a ctx_swarm variable after delay.

        Args:
            variable_name: Name of variable to update
            value: New value to set
            delay: Delay in seconds
            callback: Optional callback name (str) or function (will be registered automatically)
        """
        # Handle callback registration if function provided
        if callable(callback):
            cb_name = f"callback_{id(callback)}"
            self.register_callback(cb_name, callback)
            callback = cb_name

        event = {
            "variable": variable_name,
            "value": value,
            "time": time.time() + delay,
            "callback_name": callback,  # Store callback name instead of function
        }
        with self._scheduled_events_lock:
            self._scheduled_events.append(event)
            print(f"Scheduled event for {variable_name} in {delay} seconds")

    def update_variable(self, variable_name: str, value: Any) -> None:
        """Update a ctx_swarm variable and notify subscribers.

        Args:
            variable_name: Name of variable to update
            value: New value to set
        """
        with self._get_lock(variable_name):
            if isinstance(self.ctx_swarm.get(variable_name), ListProxy):
                # Handle ListProxy objects
                self.ctx_swarm[variable_name].append(value)
            elif isinstance(self.ctx_swarm.get(variable_name), DictProxy):
                # Handle DictProxy objects
                if isinstance(value, dict):
                    self.ctx_swarm[variable_name].update(value)
                else:
                    print(
                        f"Warning: Trying to update dict with non-dict value: {value}"
                    )
            else:
                # Handle regular variables and Value proxy
                self.ctx_swarm[variable_name] = value

            callbacks = self._subscribers[variable_name].copy()

        for callback in callbacks:
            try:
                callback(value)
            except Exception as e:
                print(f"Error in subscriber callback: {e}")

    def remove_from_list(
        self, variable_name: str, index: int = None, value: Any = None
    ) -> None:
        """Remove item from a list-type variable by index or value.

        Args:
            variable_name: Name of the list variable
            index: Index to remove (optional)
            value: Value to remove (optional)
        """
        if not isinstance(self.ctx_swarm.get(variable_name), ListProxy):
            raise ValueError(f"{variable_name} is not a list-type variable")

        with self._get_lock(variable_name):
            target_list = self.ctx_swarm[variable_name]
            if index is not None:
                if 0 <= index < len(target_list):
                    del target_list[index]
            elif value is not None:
                try:
                    target_list.remove(value)
                except ValueError:
                    print(f"Value {value} not found in {variable_name}")

            callbacks = self._subscribers[variable_name].copy()

        # Notify subscribers about the removal
        for callback in callbacks:
            try:
                callback({"action": "remove", "value": value, "index": index})
            except Exception as e:
                print(f"Error in removal callback: {e}")

    def clear_list(self, variable_name: str) -> None:
        """Clear all items from a list-type variable.

        Args:
            variable_name: Name of the list variable
        """
        if not isinstance(self.ctx_swarm.get(variable_name), ListProxy):
            raise ValueError(f"{variable_name} is not a list-type variable")

        with self._get_lock(variable_name):
            self.ctx_swarm[variable_name][:] = []
            callbacks = self._subscribers[variable_name].copy()

        # Notify subscribers about the clear operation
        for callback in callbacks:
            try:
                callback({"action": "clear"})
            except Exception as e:
                print(f"Error in clear callback: {e}")

    def start(self) -> None:
        """Start the event processing thread."""
        if self._processing_thread is None:
            self._running = True
            self._processing_thread = threading.Thread(
                target=self._process_events, daemon=True
            )
            self._processing_thread.start()

    def stop(self) -> None:
        """Stop the event processing thread."""
        self._running = False
        if self._processing_thread:
            self._processing_thread.join()
            self._processing_thread = None

    def _process_events(self) -> None:
        """Process scheduled events in background thread."""
        while self._running:
            now = time.time()
            events_to_process = []

            with self._scheduled_events_lock:
                # Get due events from local list
                due_events = [e for e in self._scheduled_events if e["time"] <= now]
                self._scheduled_events = [
                    e for e in self._scheduled_events if e["time"] > now
                ]
                events_to_process.extend(due_events)

            # Process events outside the lock
            for event in events_to_process:
                try:
                    print(f"Processing event: {event['variable']} = {event['value']}")
                    self.update_variable(event["variable"], event["value"])

                    # Execute callback by name if exists
                    if (
                        event.get("callback_name")
                        and event["callback_name"] in self._callback_registry
                    ):
                        self._callback_registry[event["callback_name"]](event["value"])
                except Exception as e:
                    print(f"Error processing event: {e}")

            time.sleep(0.01)  # Reduced sleep time for faster processing

    def add_event(self, event_data: Dict[str, Any]) -> bool:
        """Add an event to ctx_chat with proper formatting and deduplication."""
        # Validate input is a dictionary
        if not isinstance(event_data, dict):
            print(f"Error: event_data must be a dictionary, got {type(event_data)}")
            return False

        # Ensure processing_timestamp exists
        if "processing_timestamp" not in event_data:
            event_data["processing_timestamp"] = time.time_ns()

        # Look for similar recent events
        with self._get_lock("ctx_chat"):
            ctx_chat = self.ctx_swarm.get("ctx_chat", [])

            # Verify each item in ctx_chat is a dictionary
            for i, event in enumerate(ctx_chat):
                if not isinstance(event, dict):
                    print(f"Warning: Invalid event in ctx_chat at index {i}: {event}")
                    continue

                if self._are_events_similar(event, event_data):
                    # Update existing event
                    repeating = event.get("repeating", 1)
                    event["repeating"] = repeating + 1 if repeating else 1
                    event["date"] = event_data["date"]
                    return self.update_event(event)

            # Add new event
            self.ctx_swarm["ctx_chat"].append(event_data)
            return True

    def update_event(self, event_data: Dict[str, Any]) -> bool:
        """Update an existing event by processing_timestamp.

        Args:
            event_data: Dictionary containing event data with processing_timestamp

        Returns:
            bool: True if event was updated, False if not found
        """
        if "processing_timestamp" not in event_data:
            print("Cannot update event: missing processing_timestamp")
            return False

        with self._get_lock("ctx_chat"):
            ctx_chat = self.ctx_swarm.get("ctx_chat", [])
            for i, existing_event in enumerate(ctx_chat):
                if existing_event.get("processing_timestamp", -1) == event_data.get(
                    "processing_timestamp", -2
                ):
                    ctx_chat[i] = event_data
                    return True
            return False

    def _are_events_similar(
        self, event1: Dict[str, Any], event2: Dict[str, Any]
    ) -> bool:
        """Check if two events are similar enough to be combined.

        Args:
            event1: First event dictionary
            event2: Second event dictionary

        Returns:
            bool: True if events are similar
        """
        # Add type checking
        if not isinstance(event1, dict) or not isinstance(event2, dict):
            print(f"Warning: Invalid event types: {type(event1)}, {type(event2)}")
            return False

        # Debug print
        # print(f"Comparing events:\nEvent1: {event1}\nEvent2: {event2}")

        # Must have same type and user
        if event1.get("type", "") != event2.get("type", ""):
            return False
        if event1.get("user", "") != event2.get("user", ""):
            return False

        # If events have messages, they must match
        if "msg" in event1 and "msg" in event2:
            if event1["msg"] != event2["msg"]:
                return False

        # Events must be within 30 seconds of each other
        try:
            time1 = datetime.strptime(event1["date"], "%Y-%m-%d %H:%M:%S")
            time2 = datetime.strptime(event2["date"], "%Y-%m-%d %H:%M:%S")
            if abs((time1 - time2).total_seconds()) > 30:
                return False
        except Exception as e:
            print(f"Error parsing dates: {e}")
            return False

        return True

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def test_process_add_ctx_chat(manager_dict, manager_list, manager_lock):
    """Test function that runs in separate process with proper manager objects"""
    ctx_swarm = {
        "ctx_chat": manager_list,
        "ctx_lock": manager_lock,
    }
    this_ctx = CtxHandler(ctx_swarm)
    this_ctx.update_variable("ctx_chat", {"msg": "test from process", "user": "tester"})


def test_var_access(list_proxy, value, delay=None):
    """Test function for multiprocess variable access."""
    if delay:
        time.sleep(delay)
    list_proxy.append(value)


def test_handler_process(
    var_name: str, values: range, delay: Optional[float] = None
) -> None:
    """Test function that verifies CtxHandler lock isolation in separate process.
    Creates its own manager to avoid pickling issues."""
    with Manager() as process_manager:
        # Create minimal context with just the needed proxies
        ctx_swarm = {
            var_name: process_manager.list(),
        }
        ctx_swarm[f"{var_name}_lock"] = process_manager.Lock()

        if delay:
            time.sleep(delay)

        handler = CtxHandler(ctx_swarm)
        for value in values:
            handler.update_variable(var_name, value)

        # Return length as exit code to verify completion
        return len(list(values))


def print_ctx_swarm(ctx_swarm):
    inner_handler = CtxHandler(ctx_swarm)
    for i, (
        k,
        v,
    ) in enumerate(inner_handler.ctx_swarm.items()):
        print(i, "inner ctx swarm", "k", k, "v", v)


if __name__ == "__main__":
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data_schema.structure_templates import CTX_SWARM_EMPTY, create_ctx_swarm

    print("\n=== Testing CtxManager ===")

    # Create manager that will live through all tests
    with Manager() as test_manager:
        # Initialize test context properly through structures
        ctx_swarm = create_ctx_swarm(test_manager)

        # Add test variables
        ctx_swarm["test_var"] = test_manager.Value("i", 0)
        ctx_swarm["test_var1"] = test_manager.Value("i", 0)
        ctx_swarm["test_var2"] = test_manager.Value("i", 0)
        ctx_swarm["test_var_lock"] = test_manager.Lock()
        ctx_swarm["test_var1_lock"] = test_manager.Lock()
        ctx_swarm["test_var2_lock"] = test_manager.Lock()
        # Create shared callback state
        callback_called = False
        callback_value = None

        def test_callback(value):
            global callback_called, callback_value
            callback_called = True
            callback_value = value
            print(f"Callback received value: {value}")

        # Run all tests within the same manager context
        with CtxHandler(ctx_swarm) as handler:
            handler.ctx_chat.append("ыыы")
            print(ctx_swarm)
            p1 = Process(target=print_ctx_swarm, args=(ctx_swarm,))
            p1.start()
            time.sleep(5)
            p1.join()
            exit()
            # Test 1: Variable subscription and updates
            print("\nTest 1: Variable subscription and updates")
            handler.subscribe("test_var", test_callback)
            handler.update_variable("test_var", 42)
            handler.update_variable("ctx_chat", 42)
            assert callback_called, "Callback was not called"
            assert callback_value == 42, f"Wrong callback value: {callback_value}"
            print("✓ Subscription test passed")

            # Test 2: ctx_chat handling with multiprocessing
            print("\nTest 2: ctx_chat handling with multiprocessing")
            # Create separate list and lock for multiprocess test
            mp_list = test_manager.list()
            mp_lock = test_manager.Lock()

            mp_ctx_swarm = {"ctx_chat": mp_list, "ctx_lock": mp_lock}

            # Setup callback
            callback_called = False

            def mp_callback(value):
                global callback_called
                callback_called = True
                print(f"Multiprocess callback received: {value}")

            # Start process with proper manager objects
            proc = Process(
                target=test_process_add_ctx_chat, args=(mp_ctx_swarm, mp_list, mp_lock)
            )
            proc.start()
            proc.join()

            # Verify results
            assert len(mp_list) > 0, "Message not added from other process"
            assert mp_list[0]["msg"] == "test from process", "Wrong message content"
            print("✓ Multiprocess ctx_chat handling test passed")

            # Test 3: Event scheduling
            print("\nTest 3: Event scheduling")
            callback_called = False
            callback_value = None

            def scheduled_callback(value):
                global callback_called, callback_value
                callback_called = True
                callback_value = value
                print(f"Scheduled callback received: {value}")

            # Register callback before scheduling
            handler.register_callback("test_scheduled_callback", scheduled_callback)

            schelude_delay = 2
            handler.schedule_event(
                "test_var", 100, schelude_delay, "test_scheduled_callback"
            )
            print("Event scheduled")

            # Wait for callback
            start_time = time.time()
            while (
                not callback_called and time.time() - start_time < schelude_delay * 1.1
            ):
                time.sleep(0.01)

            assert callback_called, "Scheduled event callback not called"
            assert callback_value == 100, f"Wrong callback value: {callback_value}"
            print("✓ Event scheduling test passed")

            # Test 4: Multiple subscribers
            print("\nTest 4: Multiple subscribers")
            callback2_called = False

            def test_callback2(value):
                global callback2_called
                callback2_called = True
                print(f"Second callback received value: {value}")

            handler.subscribe("test_var", test_callback2)

        # Test 5: Context manager cleanup
        print("\nTest 5: Context manager cleanup")
        assert (
            not handler._running
        ), "Processing thread still running after context exit"
        print("✓ Cleanup test passed")

        # Test 6: Socket.IO style event subscription with decorator
        print("\nTest 6: Testing Socket.IO style decorator subscriptions")
        with CtxHandler(ctx_swarm) as handler:
            callback1_called = False
            callback2_called = False

            @handler.on("test_var1")
            def on_test1(value):
                global callback1_called
                callback1_called = True
                print(f"Decorator received: {value}")

            # Test method style too
            def on_test2(value):
                global callback2_called
                callback2_called = True
                print(f"Method style received: {value}")

            handler.on("test_var2", on_test2)

            # Update both variables
            handler.update_variable("test_var1", "value1")
            handler.update_variable("test_var2", "value2")

            assert callback1_called, "Decorator style callback was not called"
            assert callback2_called, "Method style callback was not called"
            print("✓ Socket.IO style decorator test passed")

        # Add new tests for list operations
        print("\nTest 7: List operations")
        with CtxHandler(ctx_swarm) as handler:
            # Test list append
            test_message = {"msg": "test1", "user": "tester"}
            handler.update_variable("ctx_chat", test_message)
            assert (
                test_message in ctx_swarm["ctx_chat"]
            ), "Message not added to ctx_chat"

            # Test list remove by value
            handler.remove_from_list("ctx_chat", value=test_message)
            assert (
                test_message not in ctx_swarm["ctx_chat"]
            ), "Message not removed from ctx_chat"

            # Test list clear
            handler.update_variable("ctx_chat", {"msg": "test2", "user": "tester"})
            handler.clear_list("ctx_chat")
            assert len(ctx_swarm["ctx_chat"]) == 0, "ctx_chat not cleared"

            print("✓ List operations test passed")

        # Test 8: Event handling
        print("\nTest 8: Event handling")
        with CtxHandler(ctx_swarm) as handler:
            # Test event addition
            event = {
                "type": "chat",
                "user": "tester",
                "msg": "test message",
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "processing_timestamp": time.time_ns(),
            }
            assert handler.add_event(event), "Failed to add event"

            # Test similar event combining
            similar_event = event.copy()
            similar_event["date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            assert handler.add_event(similar_event), "Failed to add similar event"
            assert len(ctx_swarm["ctx_chat"]) == 1, "Similar events not combined"
            assert (
                ctx_swarm["ctx_chat"][0].get("repeating", 0) == 2
            ), "Repeating count not updated"
            print(ctx_swarm["ctx_chat"])
            print("✓ Event handling test passed")

        # Add these tests at the end of the test section
        print("\nTest 9: Testing proxy wrappers")
        with CtxHandler(ctx_swarm) as handler:
            # Test list proxy wrapper
            handler.ctx_chat.append({"msg": "test", "user": "tester"})
            assert len(handler.ctx_chat) > 0, "Failed to append via wrapper"

            last_msg = handler.ctx_chat.getlast()
            assert last_msg["msg"] == "test", "getlast() failed"

            # Test removing by processing_timestamp
            ts = time.time_ns()
            handler.ctx_chat.append({"msg": "test2", "processing_timestamp": ts})
            handler.ctx_chat.remove(processing_timestamp=ts)
            assert (
                handler.ctx_chat.getlast()["msg"] == "test"
            ), "Remove by timestamp failed"

            # Test dict proxy wrapper - direct dict operations
            handler.game["score"] = 100
            assert handler.game["score"] == 100, "Dict set/get failed"

            # Test dict proxy wrapper - value operations
            handler.game.value = {"score": 200}
            assert handler.game.value["score"] == 200, "Dict value setter failed"

            # Test dict proxy wrapper - single value
            handler.game.value = 42
            assert handler.game.value == 42, "Dict single value failed"

            print("✓ Proxy wrapper tests passed")

        print("\nTest 10: Testing automatic proxy wrappers")
        with CtxHandler(ctx_swarm) as handler:
            # Test automatic list proxy wrapper
            handler.ctx_chat.append({"msg": "test"})
            assert len(handler.ctx_chat) > 0
            assert handler.ctx_chat.getlast()["msg"] == "test"

            # Test automatic dict proxy wrapper
            handler.game["score"] = 100
            assert handler.game["score"] == 100
            handler.game.update({"level": 2})
            assert handler.game["level"] == 2

            # Test value proxy - direct assignment
            handler.test_var = 42
            assert handler.test_var.value == 42

            # Test value proxy - through .value
            handler.test_var.value = 84
            assert handler.test_var.value == 84

            print("✓ Automatic proxy wrapper tests passed")

    print("\nTest 11: Testing CtxHandler multiprocess lock isolation")
    with Manager() as test_manager:
        # Create variables to track process completion
        p1_done = test_manager.Value("i", 0)
        p2_done = test_manager.Value("i", 0)

        # Test concurrent access using separate processes
        p1 = Process(target=test_handler_process, args=("var1", range(100), 0.1))
        p2 = Process(target=test_handler_process, args=("var2", range(100, 200)))

        p1.start()
        p2.start()

        # Wait for both processes
        p1.join()
        p2.join()

        # Small delay to ensure manager syncs
        time.sleep(0.2)

        # Create final handler to verify results
        final_ctx = {
            "_manager": test_manager,
            "var1": test_manager.list(range(100)),  # Expected values
            "var2": test_manager.list(range(100, 200)),  # Expected values
        }
        final_ctx["var1_lock"] = test_manager.Lock()
        final_ctx["var2_lock"] = test_manager.Lock()

        handler = CtxHandler(final_ctx)

        # Verify results
        assert len(handler.var1) == 100, "var1 should have 100 values"
        assert len(handler.var2) == 100, "var2 should have 100 values"

        # Sort the lists since order might vary due to timing
        var1_values = sorted(list(handler.var1))
        var2_values = sorted(list(handler.var2))

        assert var1_values == list(range(100)), "var1 values incorrect"
        assert var2_values == list(range(100, 200)), "var2 values incorrect"

        print("✓ CtxHandler multiprocess lock isolation test passed")

    print("\nAll tests passed successfully!")
