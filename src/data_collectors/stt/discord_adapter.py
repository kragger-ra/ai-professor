"""DISCORD BOT

TODO
move into the DOCKER part and configure smart socks5 proxying like
`sockify python discord_adapter.py`
"""

import asyncio
import os
import sys

import interactions
from interactions import Intents, listen, slash_command

if __name__ == "__main__":
    sys.path.append(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )

from config_schema.general import get_secret
from data_collectors.stt.stt_utils import RECORD_INTERVAL, audio_format_discord_wav

bot = interactions.Client(intents=Intents.ALL)
# ,proxy_url=get_secret("proxy").replace("http://", "socks://"),)
ctx_swarm = {"audio_feed_queue": asyncio.Queue()}


@slash_command("record")
async def record(ctx: interactions.SlashContext):
    if not ctx.author.voice or not ctx.author.voice.channel:
        await ctx.send("Вы должны находиться в голосовом канале!")
        return

    voice_channel = ctx.author.voice.channel
    if not ctx.voice_state:
        voice_state = await voice_channel.connect()
    else:
        voice_state = ctx.voice_state

    await ctx.send("Начали обрабатывать аудио")

    while True:
        await voice_state.start_recording(encoding="wav")
        await asyncio.sleep(RECORD_INTERVAL)
        await voice_state.stop_recording()

        if len(voice_state.recorder.output.items()) == 0:
            continue

        user_id, wav_chunk = next(iter(voice_state.recorder.output.items()))
        formatted_wav = audio_format_discord_wav(wav_chunk)
        await ctx.send(
            files=[
                interactions.File(formatted_wav, file_name=str(user_id) + "user_id.wav")
            ]
        )
        ctx_swarm["audio_feed_queue"].put(
            {"user": user_id, "audio": formatted_wav.raw_data, "env": "discord"}
        )
        # processor.stream_audio("discord", formatted_wav)


@listen()
async def on_ready():
    print("Ready")
    print(f"This bot is owned by {bot.owner}")


if __name__ == "__main__":
    bot.start(get_secret("DiscordToken"))
