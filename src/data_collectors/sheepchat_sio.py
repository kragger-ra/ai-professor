import asyncio
import html
import re
import threading
import time
from typing import Optional

import socketio


def example_callback(msg):
    print(f"[{msg.get('type', '')}] {msg['nick']}: {msg['text']}")


class SheepChatClient:
    def __init__(self, callback=example_callback, debug=False):
        self.sio = socketio.AsyncClient(logger=False, engineio_logger=False)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.callback = callback
        self._setup_handlers()
        self.debug = debug

    def _setup_handlers(self):
        @self.sio.event
        async def connect():
            print("[SheepChat] Connected to server!")
            join_data = {"event": "join", "data": {}}
            await self.sio.emit("message", join_data)
            print("[SheepChat] Sent join request")

        @self.sio.event
        async def disconnect():
            print("[SheepChat] Disconnected from server!")

        @self.sio.on("message")
        async def on_message(data):
            try:
                if (
                    isinstance(data, dict)
                    and data.get("event") == "broadcast"
                    and "ns" in data
                ):
                    broadcast = data.get("data", {})
                    if broadcast.get("broadcast_event") == "message":
                        if self.debug:
                            print("DEBUG", broadcast)
                        nick = broadcast.get("nick", "")
                        text = broadcast.get("text", "")
                        # Decode HTML entities
                        text = html.unescape(text)
                        text = convert_emoji_url(text)
                        text = re.sub(r"<[^>]+>", "", text)

                        if text.strip():
                            cb_dict = broadcast.copy()
                            cb_dict["nick"] = nick
                            cb_dict["text"] = text
                            self.callback(cb_dict)

            except Exception as e:
                print(f"[SC SIO] Error parsing message: {e}")
                print(f"[SC SIO] Raw message: {data}")

    async def _listen(self):
        base_url = "http://127.0.0.1:49135"
        query = {
            "session_id": "0",
            "device_type": "listener",
            "os": "Windows+10+64-bit",
            "room": "fguest-niyxhrhy",
            "pc_name": "Widget+on+Chrome",
            "EIO": "3",
        }
        url = f"{base_url}?" + "&".join(f"{k}={v}" for k, v in query.items())

        while self.running:
            try:
                print("[SheepChat] Connecting sio")
                if self.sio.connected:
                    await self.sio.disconnect()
                await self.sio.connect(url)
                await self.sio.wait()
            except Exception as e:
                print(f"[SheepChat] Connection error: {e}")
                if self.sio.connected:
                    await self.sio.disconnect()
                await asyncio.sleep(5)

    def _run_event_loop(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._listen())
        self.loop.close()

    def start(self):
        """Start the client in a background thread"""
        if self.thread is not None:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run_event_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        """Stop the client"""
        self.running = False
        if self.loop and self.sio.connected:

            async def disconnect():
                await self.sio.disconnect()

            future = asyncio.run_coroutine_threadsafe(disconnect(), self.loop)
            future.result(timeout=5)
        if self.thread:
            self.thread.join(timeout=5)
            self.thread = None


EMOJI_MAP = {
    # Common emojis
    "1f60c": "😌",  # relieved face
    "1f634": "😴",  # sleeping face
    "1f914": "🤔",  # thinking face
    "1f974": "🥴",  # woozy face
    "1fae5": "🫥",  # dotted line face
    # Add more as needed
}


def convert_emoji_url(text):
    """Convert emoji URLs to unicode emojis"""

    # Handle Google Font emoji URLs
    text = re.sub(
        r"https://fonts\.gstatic\.com/s/e/notoemoji/\d+\.\d+/([a-zA-Z0-9]+)/72\.png\?smile",
        lambda m: EMOJI_MAP.get(m.group(1), f"[emoji_{m.group(1)}]"),
        text,
    )

    # Handle YouTube emoji URLs
    text = re.sub(
        r"https://yt3\.ggpht\.com/[a-zA-Z0-9_\-/+=]+\?smile", "[YT_emoji]", text
    )

    return text.strip()


if __name__ == "__main__":
    client = SheepChatClient(debug=True)
    try:
        client.start()
        # Keep main thread alive
        while True:
            # print("LOL")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nShutting down...")
        client.stop()
