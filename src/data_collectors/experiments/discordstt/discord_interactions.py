# https://interactions-py.github.io/interactions.py/Guides/01%20Getting%20Started/#__tabbed_2_2
# pip install discord.py-interactions[voice]
import asyncio
import os
import sys

import interactions
from interactions import Intents, listen, slash_command

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )
    )


from interactions.api.voice.audio import AudioVolume

from config_schema.general import get_secret


@slash_command(
    "play",
)
async def play(ctx: interactions.SlashContext):
    if not ctx.voice_state:
        # if we haven't already joined a voice channel
        # join the authors vc
        await ctx.author.voice.channel.connect()

    song = r"C:\Users\Onix\Downloads\output (2).wav"
    audio = AudioVolume(song)
    await ctx.send(f"Now Playing: **{song}**")
    # Play the audio
    await ctx.voice_state.play(audio)


@slash_command("alllooo")
async def lolll(ctx: interactions.SlashContext):
    await ctx.send("KLGSJGJKFDHKJ")


@slash_command("record")
async def record(ctx: interactions.SlashContext):
    if not ctx.voice_state:
        voice_state = await ctx.author.voice.channel.connect()
    else:
        voice_state = ctx.voice_state
    # Start recording
    await voice_state.start_recording()
    print("STARTED")
    await asyncio.sleep(3)
    print("STOPPING")
    await voice_state.stop_recording()
    await ctx.send(
        files=[
            interactions.File(file, file_name="user_id.mp3")
            for user_id, file in voice_state.recorder.output.items()
        ]
    )


@listen()  # this decorator tells snek that it needs to listen for the corresponding event, and run this coroutine
async def on_ready():
    # This event is called when the bot is ready to respond to commands
    print("Ready")
    print(f"This bot is owned by {bot.owner}")


@listen()
async def on_message_create(event):
    # This event is called when a message is sent in a channel the bot can see
    print(f"message received: {event.message.jump_url}")


if __name__ == "__main__":
    bot = interactions.Client(
        intents=Intents.ALL,
        # proxy_url=get_secret("proxy").replace("http://", "socks://"),
    )
    bot.start(get_secret("DiscordToken"))
