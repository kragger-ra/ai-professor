import asyncio
import json
import re
import time
from urllib.parse import parse_qs, urlparse

import websockets

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


async def handle_socketio_message(message):

    try:

        # Handle handshake
        if message.startswith(PACKET_OPEN):
            handshake = json.loads(message[1:])
            print(f"Connected! Session ID: {handshake['sid']}")
            return None

        # Handle connect packet
        elif message.startswith(PACKET_MESSAGE):
            if message == "40":
                print("Socket.IO connection established")
                return None
            # Handle event packets
            # print(f"Raw message: {str(message)}")
            data = json.loads(message[2:])  # Remove '42' prefix

            if data[0] == "message":

                msg = data[1]

                # Handle broadcast messages
                if msg.get("event") == "broadcast" and "ns" in msg:
                    broadcast = msg.get("data", {})
                    if broadcast.get("broadcast_event") == "message":
                        # Extract message details
                        nick = broadcast.get("nick", "")
                        text = broadcast.get("text", "")

                        # Convert emoji URLs and clean text
                        text = convert_emoji_url(text)
                        text = re.sub(r"<[^>]+>", "", text)

                        if text.strip():  # Only print if there's actual text
                            print(f"[{broadcast['type']}] {nick}: {text}")
                        return None
                    elif broadcast.get("broadcast_event") == "status":
                        # Ignore status broadcasts
                        return None
        else:
            print(f"Raw message: {str(message)}")
        # Debug other messages only during development
        # print(f"Debug message: {message}")

    except Exception as e:
        print(f"Error parsing message: {e}")
        print(f"Raw message: {message}")

    return None


async def send_join_message(websocket):
    join_data = {"event": "join", "data": {}}
    await websocket.send(f"{PACKET_EVENT}{json.dumps(['message', join_data])}")
    print("Sent join request")


async def listen():
    url = "ws://127.0.0.1:49135/socket.io/?session_id=1735743237395&device_type=listener&os=Windows%2B10%2B64-bit&room=fguest-niyxhrhy&pc_name=Widget%2Bon%2BChrome&EIO=3&transport=websocket"

    while True:  # Add reconnection loop
        try:
            async with websockets.connect(url) as websocket:
                # Send join message after connection established
                join_sent = False

                while True:
                    try:
                        message = await websocket.recv()

                        # Handle ping packets
                        if message.startswith(PACKET_PING):
                            await websocket.send(PACKET_PONG)
                            continue

                        # Send join after connection is established
                        if not join_sent and message == "40":
                            await send_join_message(websocket)
                            join_sent = True

                        await handle_socketio_message(message)

                    except websockets.ConnectionClosed:
                        print("Connection closed, reconnecting...")
                        break

        except Exception as e:
            print(f"Connection error: {e}")

        # Wait before reconnecting
        await asyncio.sleep(5)


# Start the asyncio event loop
asyncio.run(listen())

time.sleep(10)
