import time
from contextlib import contextmanager
from typing import Dict, Union

from langchain_core.messages import BaseMessage


class bcolors:
    HEADER = "\033[95m"
    OKBLUE = "\033[94m"
    OKCYAN = "\033[96m"
    OKGREEN = "\033[92m"
    WARNING = "\033[93m"
    FAIL = "\033[91m"
    ENDC = "\033[0m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"


@contextmanager
def timing_context(name: str):
    start_time = time.time()
    yield
    end_time = time.time()
    print(f"[Timing] {name} took {end_time - start_time:.2f} seconds")


def debug_print_message(message: BaseMessage) -> None:
    separator = "-" * 50
    # Use repr() to show raw string with newlines, strip quotes
    content = message.content
    if not isinstance(content, list):
        print(f"{separator}" + f"({message.type})")
        for line in content.splitlines():
            print(f"| {line}")


def debug_print_message_dict(message: Dict) -> None:
    separator = "-" * 50
    # Use repr() to show raw string with newlines, strip quotes
    content = message["content"]
    if not isinstance(content, list):
        print(f"{separator}" + f"""({message["role"]})""")
        for line in content.splitlines():
            print(f"| {line}")


# Usage example:
def print_messages(messages: list[Union[BaseMessage, Dict]]) -> None:
    print("\n --- MANUAL DEBUG VERBOSE OUTPUT --- ")
    for msg in messages:
        if isinstance(msg, dict):
            debug_print_message_dict(msg)
        else:
            debug_print_message(msg)
    print(" --> END MANUAL DEBUG VERBOSE OUTPUT <-- \n")
