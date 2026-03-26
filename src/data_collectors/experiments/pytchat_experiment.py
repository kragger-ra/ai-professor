import asyncio
import json
import os
import sys
from datetime import datetime, timezone

import aiohttp
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
from config_schema.general import get_secret
from data_schema.structure_templates import REPO_DATA_PATH

CREDENTIALS_DIR = os.path.join(REPO_DATA_PATH, "credentials")
YOUTUBE_CLIENT_SECRET_FILE = os.path.join(
    CREDENTIALS_DIR, "youtube", "client_secret.json"
)


class YouTubeChatBot:
    def __init__(self):
        self.youtube = None
        self.live_chat_id = None
        self.video_id = None
        self.next_page_token = None
        self.session = None
        self.last_message_time = datetime.now(timezone.utc)
        self.known_message_ids = set()

    def authorize(self):
        """Regular (non-async) authorization method"""
        try:
            flow = InstalledAppFlow.from_client_secrets_file(
                YOUTUBE_CLIENT_SECRET_FILE,
                scopes=[
                    "openid",
                    "https://www.googleapis.com/auth/userinfo.email",
                    "https://www.googleapis.com/auth/userinfo.profile",
                    "https://www.googleapis.com/auth/youtube",
                    "https://www.googleapis.com/auth/youtube.force-ssl",
                    "https://www.googleapis.com/auth/youtube.readonly",
                ],
            )
            flow.run_local_server(
                host="localhost", port=5500, authorization_prompt_message=""
            )
            credentials = flow.credentials
            self.youtube = build("youtube", "v3", credentials=credentials)
            print("Authorization successful!")
        except Exception as e:
            print(f"Authorization failed: {e}")
            raise

    async def get_live_chat_id(self, video_id):
        try:
            video_response = (
                self.youtube.videos()
                .list(part="liveStreamingDetails", id=video_id)
                .execute()
            )

            if not video_response["items"]:
                raise Exception("Video not found or not a live stream")

            self.live_chat_id = video_response["items"][0]["liveStreamingDetails"][
                "activeLiveChatId"
            ]
            print(f"Found live chat ID: {self.live_chat_id}")
            return self.live_chat_id

        except Exception as e:
            print(f"Error getting live chat ID: {str(e)}")
            return None

    async def send_chat_message(self, message):
        try:
            response = (
                self.youtube.liveChatMessages()
                .insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "liveChatId": self.live_chat_id,
                            "type": "textMessageEvent",
                            "textMessageDetails": {"messageText": message},
                        }
                    },
                )
                .execute()
            )

            print(f"Message sent successfully: {message}")
            return response

        except Exception as e:
            print(f"Error sending message: {str(e)}")
            return None

    async def process_messages(self, messages):
        for message in messages:
            try:
                message_id = message["id"]

                # Skip if we've seen this message before
                if message_id in self.known_message_ids:
                    continue

                self.known_message_ids.add(message_id)

                # Keep the set size manageable
                if len(self.known_message_ids) > 1000:
                    self.known_message_ids.clear()

                author_name = message["authorDetails"]["displayName"]
                message_text = message["snippet"]["displayMessage"]
                published_at = message["snippet"]["publishedAt"]

                print(f"[{published_at}] {author_name}: {message_text}")

                # Handle commands
                lower_message = message_text.lower()
                if lower_message == "!hello":
                    await self.send_chat_message(
                        f"Hello {author_name}! Welcome to the stream!"
                    )
                # Add more commands here as needed

            except Exception as e:
                print(f"Error processing message: {e}")
                continue

    async def fetch_messages(self):
        try:
            response = (
                self.youtube.liveChatMessages()
                .list(
                    liveChatId=self.live_chat_id,
                    part="snippet,authorDetails",
                    pageToken=self.next_page_token,
                )
                .execute()
            )

            self.next_page_token = response.get("nextPageToken")
            polling_interval = response.get("pollingIntervalMillis", 5000) / 1000

            await self.process_messages(response["items"])

            return polling_interval

        except Exception as e:
            print(f"Error fetching messages: {e}")
            return 5  # Default to 5 seconds on error

    async def monitor_chat(self):
        print(f"Starting to monitor chat for video ID: {self.video_id}")

        while True:
            try:
                polling_interval = await self.fetch_messages()
                await asyncio.sleep(polling_interval)

            except Exception as e:
                print(f"Error in monitor_chat: {e}")
                await asyncio.sleep(5)  # Wait 5 seconds before retrying on error


async def main():
    VIDEO_ID = get_secret("VIDEO_ID")

    if not VIDEO_ID:
        print("Please set VIDEO_ID in environment variables")
        return

    print(f"Starting YouTube chat bot for video ID: {VIDEO_ID}")

    bot = YouTubeChatBot()
    bot.video_id = VIDEO_ID

    try:
        # Initialize the bot (non-async authorization)
        bot.authorize()

        # Get live chat ID
        await bot.get_live_chat_id(VIDEO_ID)

        if bot.live_chat_id:
            # Start monitoring chat
            await bot.monitor_chat()
        else:
            print("Failed to get live chat ID. Make sure the video is a live stream.")

    except Exception as e:
        print(f"An error occurred in main: {e}")


if __name__ == "__main__":
    asyncio.run(main())
