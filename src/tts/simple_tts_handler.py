import asyncio
import os
import time
import traceback
from threading import Thread
from typing import Optional

from config_schema.general import get_name
from live2d.vtube_settings import Live2DConfig
from live2d.vtube_studio import VTubeStudioIntegration
from tts.audio_device import AudioProcessor
from tts.fish.fish_gr import fish_tts_emo

# [`neutral`, `happy`, `sad`, `angry`, `scared`, `whispering`, `disgusted`, `sarcastic`]
# from agent/tools.py
MAX_AUDIO_ALLOWED_TIME = 20  # TODO untested

SPELL_TO_EMOTION = {
    "sadistic": "sarcastic",
    "worried": "scared",
    "frightened": "scared",
    "fearful": "scared",
    "fear": "scared",
    "crazy": "angry",
    "vengeful": "angry",
    "flirt": "sarcastic",
    "teasing": "sarcastic",
    "flirtatious": "sarcastic",
    "joking": "sarcastic",
    "curious": "happy",
    "agressive": "angry",
    "thoughtful": "neutral",
    "encouraging": "happy",
}

SPELL_TO_EMOTIONS_RU = {
    "сарказм": "sarcastic",
    "подмигивает": "sarcastic",
    "злая": "angry",
    "страх": "scared",
    "боится": "scared",
    "агрессивная": "angry",
    "флирт": "sarcastic",
    "идевается": "sarcastic",
    "флиртует": "sarcastic",
    "любопытная": "happy",
    "бесится": "angry",
    "задумчивый": "neutral",
    "одобряет": "happy",
}

SPELL_TO_EMOTION.update(SPELL_TO_EMOTIONS_RU)

EMOTION_TO_COMMAND_OLD = {
    "neutral": "thinking-face",
    "happy": "smiling-face-with-hearts",
    "sad": "crying-cat",
    "angry": "smiling-face-with-horns",
    "scared": "face-screaming-in-fear",
    "whispering": "shushing-face",
    "disgusted": "face-vomiting",
    "sarcastic": "smirking-face",
}

EMOTION_TO_COMMAND_ESCAPED = {
    "neutral": "\u00a7eНейтральный",
    "happy": "\u00a76Весёлый",
    "sad": "\u00a7bГрустный",
    "angry": "\u00a74Строгий",
    "scared": "\u00a79Удивлён",
    "whispering": "\u00a7dШёпот",
    "disgusted": "\u00a7aНедоволен",
    "sarcastic": "\u00a7Ироничный",
}

EMOTION_TO_COMMAND = {
    "neutral": 'Нейтральный","color":"gold',
    "happy": 'Весёлый","color":"green',
    "sad": 'Грустный","color":"gold',
    "angry": 'Строгий","color":"red',
    "scared": 'Удивлён","color":"blue',
    "whispering": 'Шёпот","color":"gold',
    "disgusted": 'Недоволен","color":"green',
    "sarcastic": 'Ироничный","color":"gold',
}


SELF_NAME = get_name()
if os.getenv("ENABLE_MINECRAFT_HUD"):
    for k, v in EMOTION_TO_COMMAND.items():
        EMOTION_TO_COMMAND[k] = (
            'bossbar set 100 name [{"text":"'
            + SELF_NAME
            + ' сейчас: ","color":"white"},{"text":"'
            + v
            + '"}]'
        )

# TODO locks add


def check_tts_queue(
    audio_processor, ctx_swarm, check_interrupt=False
) -> Optional[bool]:
    tts_queue = ctx_swarm["tts_queue"]
    if len(tts_queue) > 0:
        try:
            tts_dict = tts_queue[0]
            if tts_dict:
                # print("🟡 Generating, GOT QUEUE ITEM " + str(tts_dict))
                if (
                    tts_dict.get("text", "") == "interrupt"
                    or tts_dict.get("emotion", "") == "interrupt"
                ):
                    if check_interrupt or len(tts_queue) == 1:
                        tts_queue.pop(0)
                        return True
                else:
                    if check_interrupt:
                        return False
                    else:
                        tts_dict = tts_queue.pop(0)

                    ctx_swarm["voice"]["speak_entry"] = tts_dict
                    ctx_swarm["voice"]["text_chunk"] = tts_dict["text"]
                    emotion = tts_dict.get("emotion", "")
                    # EMOTION TO COMMANDS DISABLED
                    # WAITING FOR NEW COMMANDS!!
                    DO_EMOTION_COMMAND = False
                    # DO_EMOTION_COMMAND = server_ip == "localhost"
                    try:
                        if DO_EMOTION_COMMAND and emotion:
                            if emotion in list(EMOTION_TO_COMMAND.copy().keys()):
                                print(
                                    "[NEW TTS DEBUG] ADDING TO CHAT ",
                                    "/" + EMOTION_TO_COMMAND[emotion],
                                )
                                ctx_swarm["chat_queue"].append(
                                    "/" + EMOTION_TO_COMMAND[emotion]
                                )
                    except Exception as e:
                        print("ERROR TTS EMOTION PRINT =(", e)
                        traceback.print_exc()
                    audio, sr = fish_tts_emo(tts_dict)
                    audio_processor.play_sound(audio, sr, blocking=False)
                    ctx_swarm["voice"]["is_speaking"] = True
                    old_state = ctx_swarm["vtube"]["state"]
                    ctx_swarm["vtube"]["state"] = "idle"
                    chunk_size = 2048
                    audio_samples_len = len(audio)
                    full_audio_time = audio_samples_len / sr
                    if full_audio_time > MAX_AUDIO_ALLOWED_TIME:
                        print(
                            f"[TTS WARNING] THIS AUDIO ({str(full_audio_time)})s IS TOO BIG!!! WILL COMPRESSED TO "
                            + str(MAX_AUDIO_ALLOWED_TIME)
                            + "s"
                        )
                    audio_played_time = 0
                    print(
                        "[TTS] playing TTS audio for "
                        + str(full_audio_time)
                        + " seconds"
                    )
                    for i in range(0, audio_samples_len, chunk_size):
                        if check_tts_queue(
                            audio_processor, ctx_swarm, check_interrupt=True
                        ):
                            print("VOICE INTERRUPTED!!!")
                            audio_processor.interrupt_main_device()  # audio_processor.sd.stop()
                            break
                        this_chunk_time = chunk_size / sr
                        audio_played_time += this_chunk_time
                        if audio_played_time > MAX_AUDIO_ALLOWED_TIME:
                            print("VOICE INTERRUPTED BY TIME!!!")
                            audio_processor.interrupt_main_device()  # audio_processor.sd.stop()
                            break
                        else:
                            time.sleep(this_chunk_time)
                    ctx_swarm["voice"]["is_speaking"] = False
                    ctx_swarm["voice"]["text_chunk"] = ""
                    ctx_swarm["vtube"]["state"] = old_state
        except Exception as e:
            print("ERROR AUDIO GENERATE =(", e)
            traceback.print_exc()
            time.sleep(10)
            if check_interrupt:
                return False
        if check_interrupt:
            return False
    if check_interrupt:
        return False


def simple_tts_handler(ctx_swarm):
    ctx_env = ctx_swarm["env"]
    audio_processor = AudioProcessor()
    # Starting eye rotater thread
    live2d = VTubeStudioIntegration(Live2DConfig(), ctx_swarm)

    fx_thread = Thread(
        target=fx_sound_handler,
        args=(
            audio_processor,
            ctx_swarm,
        ),
        daemon=True,
    )
    fx_thread.start()
    tts_queue_handler(audio_processor, ctx_env, ctx_swarm)
    asyncio.run(live2d.cleanup())


def tts_queue_handler(audio_processor, ctx_env, ctx_swarm):
    while ctx_env["actived"]:
        check_tts_queue(audio_processor, ctx_swarm)
        time.sleep(0.1)


def fx_sound_handler(audio_processor: AudioProcessor, ctx_swarm):
    fx_queue = ctx_swarm.get("fx_queue", None)
    if fx_queue:
        ctx_env = ctx_swarm["env"]
        while ctx_env["actived"]:
            # yield
            # return None, None, "🟡 Generating, GOT QUEUE ITEM " + str(fx_queue.pop(0))
            try:
                sound_name = fx_queue.get()
                audio_processor.play_fx(sound_name)
            except Exception as e:
                print("ERROR FX PLAY =(", e)
                time.sleep(10)
            time.sleep(0.1)
