import asyncio
import json
import re
import time
from urllib.parse import parse_qs, urlparse

import socketio

# Socket.IO packet types
PACKET_OPEN = "0"  # handshake
PACKET_PING = "2"  # ping
PACKET_PONG = "3"  # pong
PACKET_MESSAGE = "4"  # message/upgrade
PACKET_EVENT = "42"  # event with data

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


sio = socketio.AsyncClient()


@sio.event
async def connect():
    print("Socket.IO connection established")
    join_data = {"event": "join", "data": {}}
    await sio.emit("message", join_data)
    print("Sent join request")


@sio.on("message")
async def handle_socketio_message(msg):
    try:
        if msg.get("event") == "broadcast" and "ns" in msg:
            broadcast = msg.get("data", {})
            if broadcast.get("broadcast_event") == "message":
                nick = broadcast.get("nick", "")
                text = broadcast.get("text", "")
                text = convert_emoji_url(text)
                text = re.sub(r"<[^>]+>", "", text)
                if text.strip():
                    print(f"[{broadcast['type']}] {nick}: {text}")
    except Exception as e:
        print(f"Error parsing message: {e}")
        print(f"Raw message: {msg}")


async def main():
    url = "http://127.0.0.1:49135"
    while True:
        await sio.connect(
            url,
            transports=["websocket"],
            # socketio_path='socket.io/?session_id=1735743237395&device_type=listener&os=Windows%2B10%2B64-bit&room=fguest-niyxhrhy&pc_name=Widget%2Bon%2BChrome&EIO=3')
        )
        await sio.wait()

        await asyncio.sleep(5)


import asyncio

asyncio.run(main())
