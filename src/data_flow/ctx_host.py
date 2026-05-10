"""Context host module.

Singleton-per-ctx_swarm helper that runs a background thread trimming
the shared chat history when it grows past ``max_ctx_chat_size``.
"""

import time
from threading import Thread
from typing import List

from data_flow.ctx_handler import CtxHandler


class CtxHost:
    def __init__(self, ctx_handler: CtxHandler):
        self.max_ctx_chat_size = 700
        self.ctx_handler = ctx_handler
        self.ctx_swarm = ctx_handler.ctx_swarm
        self.started = False
        self.threads: List[Thread] = []
        self.start()

    def start(self):
        self.this_lock = self.ctx_swarm.get("ctx_host_lock")
        if self.this_lock is None:
            self.started = False
            return
        if self.this_lock.acquire(False):
            self.started = True
            self.ctx_chat_size_handler_thread = Thread(
                target=self._ctx_chat_size_handler, daemon=True
            )
            self.ctx_chat_size_handler_thread.start()
            self.threads.append(self.ctx_chat_size_handler_thread)
        else:
            self.this_lock.acquire()
            self.started = False

    def _ctx_chat_size_handler(self):
        while self.ctx_swarm["env"]["actived"] and self.started:
            self._ctx_chat_size_check()
            time.sleep(2.4)

    def _ctx_chat_size_check(self):
        """Trim the shared ctx_chat once it passes ``max_ctx_chat_size`` entries."""
        if len(self.ctx_swarm["ctx_chat"]) <= self.max_ctx_chat_size:
            return
        keep = self.max_ctx_chat_size - self.max_ctx_chat_size // 2
        new_ctx_chat = self.ctx_swarm["ctx_chat"][-keep:]
        with self.ctx_swarm["ctx_chat_lock"]:
            self.ctx_swarm["ctx_chat"][:] = []
        for entry in new_ctx_chat:
            self.ctx_swarm["ctx_chat"].append(entry)
        print(f"[CTX HOST] ctx_chat trimmed to {len(new_ctx_chat)} entries")

    def _join_threads(self):
        for thread in self.threads:
            if thread.is_alive():
                thread.join()

    def shutdown(self):
        if not self.started:
            return
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
