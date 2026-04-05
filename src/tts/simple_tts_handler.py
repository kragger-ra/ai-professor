import asyncio
import logging
import os
import random
import time
import traceback
from threading import Thread
from typing import Optional

from config_schema.general import get_name
from live2d.vtube_settings import Live2DConfig
from live2d.vtube_studio import VTubeStudioIntegration
from tts.audio_device import AudioProcessor

_TTS_BACKEND = os.getenv("TTS_BACKEND", "fish")

if _TTS_BACKEND == "vosk":
    from tts.vosk.vosk_tts import vosk_tts_emo as fish_tts_emo
    from tts.vosk.vosk_tts import split_sentences, generate_silence, vosk_tts_sentence
elif _TTS_BACKEND == "piper":
    from tts.piper.piper_tts import piper_tts_emo as fish_tts_emo
else:
    from tts.fish.fish_gr import fish_tts_emo

log = logging.getLogger("tts-handler")

# [`neutral`, `happy`, `sad`, `angry`, `scared`, `whispering`, `disgusted`, `sarcastic`]
# from agent/tools.py
MAX_AUDIO_ALLOWED_TIME = 60  # seconds per TTS utterance

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


def _is_interrupt(tts_dict: dict) -> bool:
    return (
        tts_dict.get("text", "") == "interrupt"
        or tts_dict.get("emotion", "") == "interrupt"
    )


def _check_for_interrupt(tts_queue) -> bool:
    """Peek at queue head for interrupt signal."""
    if len(tts_queue) > 0:
        head = tts_queue[0]
        if head and _is_interrupt(head):
            tts_queue.pop(0)
            return True
    return False


def _wait_playback(audio_processor, ctx_swarm, audio, sr):
    """Monitor playback with interrupt checks (original behavior for fish/piper)."""
    chunk_size = 2048
    audio_samples_len = len(audio)
    full_audio_time = audio_samples_len / sr
    tts_queue = ctx_swarm["tts_queue"]

    if full_audio_time > MAX_AUDIO_ALLOWED_TIME:
        print(f"[TTS WARNING] Audio ({full_audio_time:.1f}s) exceeds limit, will cut at {MAX_AUDIO_ALLOWED_TIME}s")

    audio_played_time = 0
    print(f"[TTS] playing audio for {full_audio_time:.1f}s")
    for i in range(0, audio_samples_len, chunk_size):
        if _check_for_interrupt(tts_queue):
            print("VOICE INTERRUPTED!!!")
            audio_processor.interrupt_main_device()
            return
        this_chunk_time = chunk_size / sr
        audio_played_time += this_chunk_time
        if audio_played_time > MAX_AUDIO_ALLOWED_TIME:
            print("VOICE INTERRUPTED BY TIME!!!")
            audio_processor.interrupt_main_device()
            return
        time.sleep(this_chunk_time)


def check_tts_queue(
    audio_processor, ctx_swarm, check_interrupt=False
) -> Optional[bool]:
    """Process TTS queue. For vosk backend, delegates to streaming handler."""
    tts_queue = ctx_swarm["tts_queue"]
    if len(tts_queue) > 0:
        try:
            tts_dict = tts_queue[0]
            if tts_dict:
                if _is_interrupt(tts_dict):
                    if check_interrupt or len(tts_queue) == 1:
                        tts_queue.pop(0)
                        return True
                else:
                    if check_interrupt:
                        return False

                    # Vosk: sentence-level streaming
                    if _TTS_BACKEND == "vosk":
                        tts_dict = tts_queue.pop(0)
                        _handle_vosk_streaming(audio_processor, ctx_swarm, tts_dict)
                        if check_interrupt:
                            return False
                        return None

                    # Fish/Piper: original batch behavior
                    tts_dict = tts_queue.pop(0)
                    ctx_swarm["voice"]["speak_entry"] = tts_dict
                    ctx_swarm["voice"]["text_chunk"] = tts_dict["text"]
                    audio, sr = fish_tts_emo(tts_dict)
                    audio_processor.play_sound(audio, sr, blocking=False)
                    ctx_swarm["voice"]["is_speaking"] = True
                    old_state = ctx_swarm["vtube"]["state"]
                    ctx_swarm["vtube"]["state"] = "idle"
                    _wait_playback(audio_processor, ctx_swarm, audio, sr)
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


# =========================================================================
# Vosk streaming: sentence-by-sentence synthesis + playback
# =========================================================================

def _handle_vosk_streaming(audio_processor, ctx_swarm, tts_dict):
    """Synthesize and play text sentence-by-sentence for minimal latency.

    Flow per sentence:
      1. Check phrase cache -> instant if hit
      2. Send to Vosk server -> synthesize
      3. Post-process audio (compression + normalization)
      4. Play (blocking per sentence, with interrupt support)
      5. Micro-pause (150-250ms silence)
    """
    text = tts_dict.get("text", "")
    if not text.strip():
        return

    tts_queue = ctx_swarm["tts_queue"]

    # Queue overflow protection: if >10 items queued, student lost context
    if len(tts_queue) > 10:
        overflow_count = len(tts_queue) - 3
        overflow_texts = [tts_queue[i].get("text", "")[:60] for i in range(overflow_count)]
        for _ in range(overflow_count):
            tts_queue.pop(0)
        log.warning(f"[TTS] Queue overflow! Dropped {overflow_count} items: {overflow_texts}")

    # Split into sentences
    sentences = split_sentences(text)
    if not sentences:
        return

    log.info(f"[TTS] Streaming {len(sentences)} sentence(s): '{text[:80]}...'")

    ctx_swarm["voice"]["speak_entry"] = tts_dict
    ctx_swarm["voice"]["text_chunk"] = text
    ctx_swarm["voice"]["is_speaking"] = True
    old_state = ctx_swarm["vtube"]["state"]
    ctx_swarm["vtube"]["state"] = "idle"

    total_t0 = time.perf_counter()

    for i, sentence in enumerate(sentences):
        # Check interrupt between sentences
        if _check_for_interrupt(tts_queue):
            log.info("[TTS] Interrupted between sentences")
            audio_processor.interrupt_main_device()
            break

        sent_t0 = time.perf_counter()

        # Synthesize (checks cache internally)
        audio, sr = vosk_tts_sentence(sentence)

        if len(audio) == 0:
            continue

        synth_ms = (time.perf_counter() - sent_t0) * 1000
        audio_dur = len(audio) / sr

        # Safety: skip fragments longer than max allowed
        if audio_dur > MAX_AUDIO_ALLOWED_TIME:
            log.warning(f"[TTS] Sentence too long ({audio_dur:.1f}s), skipping")
            continue

        # Anomaly detection
        if synth_ms > 1000:
            log.warning(f"[TTS] Slow synth: {synth_ms:.0f}ms for '{sentence[:50]}'")

        # Play (blocking — wait for this sentence to finish)
        audio_processor.play_sound(audio, sr, blocking=True)

        log.info(
            f"[TTS] [{i+1}/{len(sentences)}] synth: {synth_ms:.0f}ms | "
            f"audio: {audio_dur:.1f}s | '{sentence[:40]}'"
        )

        # Micro-pause between sentences (not after the last one)
        if i < len(sentences) - 1:
            pause = random.uniform(0.15, 0.25)
            time.sleep(pause)

    total_ms = (time.perf_counter() - total_t0) * 1000
    log.info(f"[TTS] Streaming complete: {total_ms:.0f}ms total for {len(sentences)} sentences")

    ctx_swarm["voice"]["is_speaking"] = False
    ctx_swarm["voice"]["text_chunk"] = ""
    ctx_swarm["vtube"]["state"] = old_state


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
