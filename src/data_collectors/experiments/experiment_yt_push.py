# Standard library imports
import asyncio
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from datetime import datetime
from typing import Optional

import uvicorn

# Third-party imports
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from twitchAPI.chat import Chat, ChatCommand, ChatEvent, ChatMessage, ChatSub, EventData
from twitchAPI.oauth import UserAuthenticator
from twitchAPI.twitch import Twitch
from twitchAPI.types import AuthScope

# Local imports
if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

from config_schema.general import get_secret
from data_schema.structure_templates import REPO_DATA_PATH
from utils.time_helper import eztime, tm

CREDENTIALS_DIR = os.path.join(REPO_DATA_PATH, "credentials")
YOUTUBE_CLIENT_SECRET_FILE = os.path.join(
    CREDENTIALS_DIR, "youtube", "client_secret.json"
)

# Configuration
YT_STREAM_API_KEY = get_secret("YOUTUBE_STREAM_API_KEY")
YT_CHANNEL_ID = get_secret("YOUTUBE_CHANNEL_ID")
YT_WEBHOOK_SECRET = get_secret("YOUTUBE_WEBHOOK_SECRET")  # Add this to your secrets
WEBHOOK_PORT = 8000  # Configure as needed

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class YouTubeNotificationHandler:
    def __init__(self, ctx, twitch_actions_queue, trovo_actions_queue, ctx_chat):
        self.ctx = ctx
        self.twitch_actions_queue = twitch_actions_queue
        self.trovo_actions_queue = trovo_actions_queue
        self.ctx_chat = ctx_chat
        self.youtube = None
        self.liveChatId = None

        # Initialize YouTube API
        self.initialize_youtube_api()

    def initialize_youtube_api(self):
        """Initialize YouTube API client"""
        flow = InstalledAppFlow.from_client_secrets_file(
            YOUTUBE_CLIENT_SECRET_FILE,
            scopes=[
                "openid",
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.force-ssl",
            ],
        )
        credentials = flow.run_local_server(
            host="localhost", port=5500, authorization_prompt_message=""
        )
        self.youtube = build("youtube", "v3", credentials=credentials)

    def verify_webhook_signature(self, request_body: bytes, signature: str) -> bool:
        """Verify the webhook signature from YouTube"""
        computed_signature = hmac.new(
            YT_WEBHOOK_SECRET.encode(), request_body, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(computed_signature, signature)

    async def handle_chat_message(self, message_data: dict):
        """Process incoming chat messages"""
        try:
            author_name = message_data.get("authorDetails", {}).get("displayName")
            author_channel_id = message_data.get("authorDetails", {}).get("channelId")
            message_text = message_data.get("snippet", {}).get("displayMessage")
            published_at = message_data.get("snippet", {}).get("publishedAt")

            if all([author_name, author_channel_id, message_text]):
                msg = {
                    "env": "youtube",
                    "msg": message_text,
                    "user": author_name,
                    "youtube_user_channel_id": author_channel_id,
                    "processing_timestamp": time.time_ns(),
                    "date": published_at,
                }

                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] [YOUTUBE CHAT] {author_name}: {message_text}"
                )
                self.ctx_chat.append(msg)
                self.ctx.IsYTChatConnected = True

        except Exception as err:
            print(f"Error processing chat message: {err}")
            self.ctx.IsYTChatConnected = False

    def send_chat_reply(self, message: str):
        """Send a reply to the YouTube chat"""
        if not self.liveChatId:
            print("No active live chat ID")
            return

        try:
            reply = self.youtube.liveChatMessages().insert(
                part="snippet",
                body={
                    "snippet": {
                        "liveChatId": self.liveChatId,
                        "type": "textMessageEvent",
                        "textMessageDetails": {"messageText": f"[AI] {message}"[:200]},
                    }
                },
            )
            response = reply.execute()
            print(f"[YT CHAT BOT] Send message response: {response}")

        except Exception as err:
            print(f"Error sending chat reply: {err}")

    async def process_youtube_actions(self):
        """Process pending YouTube actions"""
        while True:
            if len(self.ctx.YoutubeActionsQueue) > 0:
                action = self.ctx.YoutubeActionsQueue[0]
                try:
                    if action.get("action") == "reply":
                        self.send_chat_reply(action.get("msg", ""))
                    elif action.get("action") == "ban":
                        channel_id = action.get("youtube_user_channel_id")
                        if channel_id:
                            await self.handle_ban(channel_id, action.get("bantime", 20))

                    self.ctx.YoutubeActionsQueue.pop(0)
                except Exception as err:
                    print(f"Error processing YouTube action: {err}")
                    if len(self.ctx.YoutubeActionsQueue) > 0:
                        self.ctx.YoutubeActionsQueue.pop(0)

            await asyncio.sleep(0.1)


# Initialize handler
handler = None


@app.on_event("startup")
async def startup_event():
    global handler
    # Initialize the handler with your context and queues
    handler = YouTubeNotificationHandler(
        ctx, twitch_actions_queue, trovo_actions_queue, ctx_chat
    )


@app.post("/youtube/webhook")
async def youtube_webhook(request: Request):
    """Handle incoming YouTube notifications"""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature")

    if not signature or not handler.verify_webhook_signature(body, signature):
        return Response(status_code=403)

    data = await request.json()

    # Handle different types of notifications
    if data.get("type") == "live_chat":
        await handler.handle_chat_message(data.get("message", {}))

    return Response(status_code=200)


def run_webhook_server():
    """Run the FastAPI webhook server"""
    uvicorn.run(app, host="0.0.0.0", port=WEBHOOK_PORT)


if __name__ == "__main__":
    import multiprocessing

    manager = multiprocessing.Manager()
    ctx = manager.Namespace()
    ctx.IsYTChatConnected = False
    ctx_chat = manager.list()
    ctx_twitch_actions_queue = manager.Queue()
    ctx_trovo_actions_queue = manager.Queue()
    ctx.YoutubeActionsQueue = manager.list()
    ctx.YouTubeCommentCheckerEnabled = True
    ctx.botNicknames = ["Net Tyan", "NetTyan", "neurodeva", "NeuroDeva"]
    ctx.ThreadsActived = True
    ctx.YouTubeAppEnabled = True
    ctx.IsYTChatConnected = False

    # Create and start webhook server thread
    webhook_thread = threading.Thread(target=run_webhook_server, daemon=True)
    webhook_thread.start()

    # Initialize Twitch functionality
    async def run_twitch_bot():
        twitch = await Twitch(
            get_secret("TWITCH_APP_ID"), get_secret("TWITCH_APP_SECRET")
        )
        auth = UserAuthenticator(twitch, [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT])
        token, refresh_token = await auth.authenticate()
        await twitch.set_user_authentication(
            token, [AuthScope.CHAT_READ, AuthScope.CHAT_EDIT], refresh_token
        )

        twitch_chat = await Chat(twitch)

        async def on_ready(ready_event: EventData):
            print("[TWITCH BOT LOAD] Bot is ready for work, joining channels")
            await ready_event.chat.join_room(get_secret("TWITCH_TARGET_CHANNEL"))
            await twitch_chat.send_message(
                get_secret("TWITCH_TARGET_CHANNEL"),
                f"[AI] [CONNECTED->{datetime.now().strftime('%M:%S')}] Connected to Twitch! Hello everyone, system is operational =)",
            )

        async def on_message(msg: ChatMessage):
            twitch_username = msg.user.name
            message = {
                "env": "twitch",
                "msg": msg.text,
                "user": twitch_username,
                "processing_timestamp": time.time_ns(),
                "date": eztime(),
            }

            if twitch_username in ctx.botNicknames:
                print(
                    f"[YT] Own message detected from {message['user']}, adding to database: {message['msg']}"
                )
            else:
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] [TWITCH CHAT] {message['user']} > {message['msg']}"
                )
                ctx_chat.append(message)

        twitch_chat.register_event(ChatEvent.READY, on_ready)
        twitch_chat.register_event(ChatEvent.MESSAGE, on_message)
        twitch_chat.start()

        return twitch_chat

    # Process Twitch actions
    async def process_twitch_actions(twitch_chat):
        while True:
            try:
                if not ctx_twitch_actions_queue.empty():
                    action = ctx_twitch_actions_queue.get()
                    if action.get("action") == "reply":
                        await twitch_chat.send_message(
                            get_secret("TWITCH_TARGET_CHANNEL"),
                            f"[AI] {action.get('msg', '')}",
                        )
            except Exception as err:
                print(f"Error processing Twitch action: {err}")
            await asyncio.sleep(0.1)

    # Main async function to run everything
    async def main():
        # Start Twitch bot
        twitch_chat = await run_twitch_bot()

        # Start YouTube action processor
        youtube_action_processor = asyncio.create_task(
            handler.process_youtube_actions()
        )

        # Start Twitch action processor
        twitch_action_processor = asyncio.create_task(
            process_twitch_actions(twitch_chat)
        )

        # Wait for all tasks
        await asyncio.gather(youtube_action_processor, twitch_action_processor)

    # Run everything
    try:
        print("Starting chat integration system...")
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
    except Exception as err:
        print(f"Fatal error: {err}")
    finally:
        ctx.ThreadsActived = False
