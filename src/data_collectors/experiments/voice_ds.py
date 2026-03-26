"""
Simple Discord bot initialization test script.
This is a minimal implementation to verify Discord connectivity.

TODO NEXT AFTER SIMPLE PIPELINE VERIFY *TESTING*
using oldest and bad example approach of old/stt_discord_pycord.py (and realtimestt for STT), realise here a simple channel joining (with old channel number you find) and simpliest voice chat support.
in src\data_collectors\experiments\stt_test.py can be find current STT solution implemention that takes raw PCM data.
TODO add publish actions queue like in old/discord_service_old.py
TODO add simple discord audio device play transmitting like in old/discord_service_old.py
TODO add simple run func like in old/stt_discord_pycord.py

realize the voice listen approach from stt_discord_pycord but save realtimestt and pcmsink and other this code approaches

DONT BREAK ANYTHING OR DO ANYTHING YOU ARE NOT ASKED TO

USE THE FUCKING SIMPLIEST APPROACH WITHOUT ANY YOUR SHITTY "IMPROVEMENTS"

DONT TOUCH MY PROXIES YOU SON OF A ...

JUST COPY THE ENTIRE REALIZATION FROM STT DISCORD PYCORD WITHOUT SHITTY ADDITIONS, REMOVE FUCKING QUEUES OR SOME SHIT YOU HAVE THIS BECAUSE ITS NOT WORK FUCK THIS!!!

(dont remove notes upper, add *testing* to TODOs you implemented)

"""

import io
import os
import sys

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )


from config_schema.general import get_secret

proxy = get_secret("proxy")
if proxy:
    print(f"Setting proxy: {proxy}")
    os.environ["http_proxy"] = proxy
    os.environ["HTTP_PROXY"] = proxy
    os.environ["https_proxy"] = proxy
    os.environ["HTTPS_PROXY"] = proxy
    os.environ["SOCKS_PROXY"] = proxy.replace("http://", "socks5://")
    os.environ["ALL_PROXY"] = proxy.replace("http://", "socks5://")

import asyncio
import logging
import os
import queue
import time
import traceback
from threading import Thread

import aiohttp
import aiohttp_socks  # pip install aiohttp_socks
import async_timeout
import discord
import numpy as np
from discord.ext import commands, tasks
from RealtimeSTT import AudioToTextRecorder

# Disable debug logging for discord.gateway to prevent emoji encoding issues
logging.getLogger("discord.gateway").setLevel(logging.INFO)


def setup_bot() -> commands.Bot:
    """Initialize the Discord bot with basic configuration"""
    # Ensure opus is loaded for voice support
    # if not discord.opus.is_loaded():
    #     try:
    #         discord.opus.load_opus('opus')
    #         print("[DISCORD] Opus loaded successfully")
    #     except Exception as e:
    #         print(f"[DISCORD] Failed to load opus: {e}")
    #         print("[DISCORD] Voice functionality may not work!")

    # Setup intents
    intents = discord.Intents.all()
    intents.message_content = True
    intents.members = True

    # Bot command prefixes (nicks)
    bot_command_prefixes = [
        "ева ",
        "eva ",
        "неттян ",
        "нетян ",
        "тян ",
        "натян ",
        "нетТян ",
        "nettyan ",
        "NetTyan ",
    ]

    # Create bot instance
    activity = discord.Game(name="симулятор человека")
    return commands.Bot(
        command_prefix=bot_command_prefixes,
        intents=intents,
        activity=activity,
        # PROXY SHOULD BE IN LOWER LEVEL!
        # proxy=get_secret("proxy")
    )


class DiscordVoiceBot:
    def __init__(self, play_sound_device_index=None):
        self.bot = setup_bot()
        self.main_guild_id = 1122595942986694658
        self.approved_guild_ids = [self.main_guild_id]
        self.token = get_secret("DiscordToken")

        # Voice handling vars from stt_discord_pycord
        self.sink = None
        self.vc = None  # Note: using vc instead of voice_client to match original
        self.voice_client = None
        self.listening_loop_started = False
        self.guild = None
        self.debug_text_channel = None

        # Voice detection vars
        self.voice_streak_found = 0
        self.silence_streak_found = 0
        self.voice_confirmed_iters = 0
        self.voice_recog_stared = False
        self.prev_voice_recog_stared = False
        self.collected_voice_data = {}
        self.listening_loop_delay = 1.0

        # Start only voice recognition loop
        self.voice_recognition_loop.start()

        # Register events
        @self.bot.event
        async def on_ready():
            """Called when bot successfully connects"""
            print(
                f"[DISCORD] Logged in as {self.bot.user.name} (ID: {self.bot.user.id})"
            )
            print("[DISCORD] Bot is ready!")
            # Auto-join voice channel
            await self.auto_join_voice()

        @self.bot.event
        async def on_message(message):
            """Handle messages only in authorized guild"""
            if message.guild and message.guild.id not in self.approved_guild_ids:
                return
            await self.bot.process_commands(message)

        @self.bot.command()
        async def ping(ctx):
            """Simple ping command to test bot responsiveness"""
            if ctx.guild and ctx.guild.id not in self.approved_guild_ids:
                return
            await ctx.send(f"Pong! Latency: {round(self.bot.latency * 1000)}ms")

        @self.bot.command()
        async def join(ctx):
            """Join the user's voice channel"""
            if not ctx.author.voice:
                await ctx.send("You're not in a voice channel!")
                return

            channel = ctx.author.voice.channel
            if ctx.voice_client is not None:
                await ctx.voice_client.move_to(channel)
            else:
                self.voice_client = await channel.connect()
                # Start receiving audio
                self.voice_client.start_recording(
                    discord.sinks.PCMSink(), self.finished_callback, ctx.channel
                )
            await ctx.send(f"Joined {channel.name} and started listening!")

        @self.bot.command()
        async def leave(ctx):
            """Leave voice channel"""
            if ctx.voice_client:
                if self.voice_client.recording:
                    self.voice_client.stop_recording()
                await ctx.voice_client.disconnect()
                self.voice_client = None
                await ctx.send("Left voice channel!")

    async def check_vc_initialize(self):
        """Direct copy of stt_discord_pycord initialize logic"""
        if self.vc is not None:
            if self.sink is None:
                self.sink = discord.sinks.WaveSink()
            if not self.vc.recording:
                self.vc.start_recording(
                    self.sink, self.finished_callback, self.debug_text_channel
                )
            return True
        else:
            if self.guild is not None:
                self.vc = discord.utils.get(self.bot.voice_clients, guild=self.guild)
            else:
                self.guild = self.bot.get_guild(self.main_guild_id)
                self.vc = discord.utils.get(self.bot.voice_clients, guild=self.guild)
            return False

    @tasks.loop(seconds=1.0)
    async def voice_recognition_loop(self):
        """Direct copy of stt_discord_pycord voice detection logic"""
        if self.listening_loop_started:
            initialized = await self.check_vc_initialize()
            if not initialized:
                return

            audios = self.sink.get_all_audio()
            sound_found = False
            if audios is not None:
                for _ in audios:
                    sound_found = True
                    break

            if sound_found:
                self.silence_streak_found = 0
                self.voice_streak_found += 1

                for user_id, audio in self.sink.audio_data.items():
                    if user_id not in self.collected_voice_data:
                        file = io.BytesIO()
                        self.collected_voice_data.update(
                            {user_id: discord.sinks.AudioData(file)}
                        )
                    self.collected_voice_data[user_id].write(audio.file.getvalue())

                if self.voice_streak_found > 1:
                    self.voice_confirmed_iters += 1
                    self.voice_recog_stared = True

            else:
                self.silence_streak_found += 1
                self.voice_streak_found = 0

                if self.voice_confirmed_iters > 0:
                    if self.voice_recog_stared:
                        self.voice_recog_stared = False

                if self.silence_streak_found > 1:
                    # Just print debug info for now
                    for user_id in self.collected_voice_data:
                        print(
                            f"[DISCORD] Would process audio from {self.bot.get_user(user_id).name}"
                        )
                        print("[DISCORD] Recognition not implemented yet!")
                    self.collected_voice_data.clear()

            if self.prev_voice_recog_stared != self.voice_recog_stared:
                if not self.voice_recog_stared:
                    self.voice_confirmed_iters = 0
                    await asyncio.sleep(1)

                    if self.vc.recording:
                        self.vc.stop_recording()
                    self.sink = discord.sinks.WaveSink()
                    self.vc.start_recording(
                        self.sink, self.finished_callback, self.debug_text_channel
                    )
                    self.collected_voice_data.clear()
                self.prev_voice_recog_stared = self.voice_recog_stared

            self.sink.audio_data = {}

    async def finished_callback(self, sink, channel, *args):
        """Simplified callback that just prints received audio"""
        if not sink.audio_data:
            return

        for user_id in sink.audio_data:
            print(f"[DISCORD] Got audio from {self.bot.get_user(user_id).name}")

    async def auto_join_voice(self):
        """Auto-join voice channel based on priority:
        1. NetTyanDev channel with people
        2. Any channel with NetTyan in name
        3. Any other channel"""
        try:
            guild = self.bot.get_guild(self.main_guild_id)
            if not guild:
                print("[DISCORD] Failed to get guild")
                return

            voice_channels = [
                c for c in guild.channels if isinstance(c, discord.VoiceChannel)
            ]
            target_channel = None

            # Priority 1: NetTyanDev with people
            for vc in voice_channels:
                if vc.name == "NetTyanDev" and len(vc.members) > 0:
                    target_channel = vc
                    break

            # Priority 2: Channel with NetTyan in name
            if not target_channel:
                for vc in voice_channels:
                    if "NetTyan" in vc.name:
                        target_channel = vc
                        break

            # Priority 3: Any channel
            if not target_channel and voice_channels:
                target_channel = voice_channels[0]

            if target_channel:
                print(f"[DISCORD] Connecting to {target_channel.name}...")
                try:
                    # First disconnect if already connected
                    if self.voice_client and self.voice_client.is_connected():
                        print("[DISCORD] Disconnecting from previous channel...")
                        await self.voice_client.disconnect()
                        self.voice_client.connect()
                        self.voice_client = None
                        await asyncio.sleep(1)

                    print("[DISCORD] Attempting to connect...")
                    # Set a timeout for the connect operation
                    async with async_timeout.timeout(10):
                        try:
                            vc = await target_channel.connect(
                                timeout=5, reconnect=False
                            )
                            # PROBLEM IS HERE
                            # proxy is not working with voice channels
                            # just BLOCKS code here forever
                            # but with SYSTEM OVERALL PROXY all is ok (enabled from third party programs)
                            # seems like discord's voice UDP packets is not proxied
                            # so need to:
                            # - get VoiceClient / VoiceProtocol websocket and change main websocket to the SOCKS proxy
                            # - or change the entire python interpreter all traffic to SOCKS proxy...

                        except Exception as e:
                            print(f"[DISCORD] Connection error: {str(e)}")
                            traceback.print_exc()
                            raise
                    print("[DISCORD] Initial connection established")

                    # Wait and verify connection
                    for _ in range(5):  # Try for 5 seconds
                        if vc.is_connected():
                            print("[DISCORD] Connection verified")
                            self.voice_client = vc
                            break
                        print("[DISCORD] Waiting for connection to stabilize...")
                        await asyncio.sleep(1)

                    if not vc.is_connected():
                        print("[DISCORD] Failed to maintain connection")
                        return

                    print("[DISCORD] Setting up recording...")
                    self.sink = discord.sinks.PCMSink()
                    self.listening_loop_started = True

                    # Start recording with explicit error handling
                    try:
                        print("[DISCORD] Starting recording...")
                        self.voice_client.start_recording(
                            self.sink, self.finished_callback, None
                        )
                        print(
                            f"[DISCORD] Connected and recording in {target_channel.name}"
                        )
                    except Exception as rec_err:
                        print(f"[DISCORD] Recording setup error: {rec_err}")
                        raise

                except asyncio.TimeoutError:
                    print("[DISCORD] Connection timed out")
                    if self.voice_client:
                        await self.voice_client.disconnect()
                        self.voice_client = None
                except Exception as e:
                    print(f"[DISCORD] Connection error: {str(e)}")
                    if self.voice_client:
                        await self.voice_client.disconnect()
                        self.voice_client = None
        except Exception as e:
            print(f"[DISCORD] Auto-join failed with error: {str(e)}")
            print(f"[DISCORD] Error type: {type(e).__name__}")
            print(f"[DISCORD] Traceback: {traceback.format_exc()}")

    async def setup_proxy_client(self):
        """Setup proxy for aiohttp client session"""
        # wee need to add proxies to the system
        proxy = get_secret("proxy")
        if proxy:
            print(f"[DISCORD] Setting up proxy: {proxy}")
            # connector = aiohttp.TCPConnector(ssl=False)  # Disable SSL verification for proxy
            self.bot.http.proxy = proxy
            # self.bot.http._HTTPClient__session = aiohttp.ClientSession(connector=connector)
            return True
        return False

    def run(self):
        """Start the Discord bot"""
        print("[DISCORD] Starting bot...")

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            try:
                # Setup proxy before running
                # asyncio.get_event_loop().run_until_complete(self.setup_proxy_client())
                # now we adding it to the bot constructor

                # Run the bot
                self.bot.run(self.token)
                break

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                retry_count += 1
                print(
                    f"[DISCORD] Connection error (attempt {retry_count}/{max_retries}): {str(e)}"
                )
                if retry_count < max_retries:
                    wait_time = retry_count * 5
                    print(f"[DISCORD] Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    print("[DISCORD] Failed to connect after maximum retries")

            except Exception as e:
                print(f"[DISCORD] Unexpected error: {str(e)}")
                break


if __name__ == "__main__":
    # Set proxy if needed
    # proxy logic moved into bot...

    # Create and run bot
    voice_bot = DiscordVoiceBot()
    voice_bot.run()
