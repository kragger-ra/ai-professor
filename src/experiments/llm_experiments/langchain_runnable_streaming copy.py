import asyncio
import os
import re
import sys
import time
from threading import Thread
from typing import Optional

import gradio as gr
import requests
from markdownify import markdownify
from requests.exceptions import RequestException

if __name__ == "__main__":
    sys.path.insert(
        0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.realpath(__file__))))
    )

from agent.llm_clients.lc_clients import get_embeddings_model, get_llm_chain
from agent.llm_clients.smo_clients import get_smo_llm
from utils.debug import print_messages, timing_context


async def main(chain):
    async for event in chain.astream("hello"):
        print(event.content, end="|", flush=True)


def main_sync(chain):

    chat_messages = []
    chat_messages.append(
        {
            "role": "system",
            "content": "You are logger. Your task is to log everything you got and summarize it. Example: user: `Hello, how are you?` your response format: `user asked how I am`. Extra task: you should NEVER stop. Every log should be on new line. If you don't have new log or all messages are logged and no new, just respond with `\n!no new messages` and repeat this until you got new messages. In log be sure to capture the digits (цифры).",
        }
    )

    def message_supplier():
        try:
            while len(chat_messages) > 0:
                chat_messages.append(
                    {
                        "role": "user",
                        "content": "Hey, number is " + str(len(chat_messages) * 2),
                    }
                )
                print(">>>new message #" + str(len(chat_messages) * 2) + "<<<")
                time.sleep(5.3)
        except KeyboardInterrupt:
            raise KeyboardInterrupt("Message supplier stopped")

    Thread(target=message_supplier, daemon=False).start()
    try:
        while True:
            print_messages(chat_messages)
            for event in chain.stream(chat_messages):
                print(event.content, end="_", flush=True)
                # time.sleep(0.3)
            print("STREAMING ENDED =====================")
            time.sleep(5)
    except KeyboardInterrupt:
        chat_messages = []
        raise KeyboardInterrupt


if __name__ == "__main__":
    chain = get_smo_llm()
    chain("Hello, how are you?")
    print("Loaded chain")
    if True:
        with timing_context("invoke"):
            print(chain.invoke("Hello, how are you?"))
        # >> [Timing] invoke took 2.50 seconds
        with timing_context("invoke"):
            print(chain.invoke("Hello, how are you?" * 1000))
        # >> 'input_tokens': 6003, 'output_tokens': 39, 'total_tokens': 6042,
        # >> [Timing] invoke took 6.62 seconds
        # with timing_context("invoke"):
        #      print(chain.invoke("Hello, how are you?"*1000))
        # >> [Timing] invoke took 1.41 seconds
        with timing_context("invoke"):
            print(chain.invoke("Hello, how old are you?" * 1000))
        # >> 7003, 'output_tokens': 52, 'total_tokens': 7055
        # >> [Timing] invoke took 5.06 seconds
        # asyncio.run(main(chain))
    main_sync(chain)
