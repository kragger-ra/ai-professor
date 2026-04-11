import concurrent.futures
import logging
import os
import random
import time
import traceback
from threading import Thread
from typing import Optional, Tuple

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
                    tts_queue.pop(0)
                    if check_interrupt:
                        return True
                else:
                    if check_interrupt:
                        return False

                    # Vosk: queue-level prefetch streaming
                    if _TTS_BACKEND == "vosk":
                        _handle_vosk_queue_stream(audio_processor, ctx_swarm)
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
                    _wait_playback(audio_processor, ctx_swarm, audio, sr)
                    ctx_swarm["voice"]["is_speaking"] = False
                    ctx_swarm["voice"]["text_chunk"] = ""
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

def _handle_vosk_queue_stream(audio_processor, ctx_swarm):
    """Drain tts_queue with prefetch: synthesize next item while current plays.

    Instead of processing one queue item at a time (with synthesis gap between),
    this keeps draining the queue and pre-synthesizing the next sentence
    during playback of the current one — near-zero gap.
    """
    tts_queue = ctx_swarm["tts_queue"]
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    prefetch_future = None
    total_t0 = time.perf_counter()
    played = 0

    ctx_swarm["voice"]["is_speaking"] = True

    # Queue overflow protection
    if len(tts_queue) > 10:
        overflow_count = len(tts_queue) - 3
        for _ in range(overflow_count):
            tts_queue.pop(0)
        log.warning(f"[TTS] Queue overflow! Dropped {overflow_count} items")

    while len(tts_queue) > 0:
        tts_dict = tts_queue.pop(0)
        if _is_interrupt(tts_dict):
            audio_processor.interrupt_main_device()
            if prefetch_future:
                prefetch_future.cancel()
                prefetch_future = None
            break

        text = tts_dict.get("text", "").strip()
        if not text:
            continue

        sentences = split_sentences(text)

        for si, sentence in enumerate(sentences):
            if _check_for_interrupt(tts_queue):
                audio_processor.interrupt_main_device()
                if prefetch_future:
                    prefetch_future.cancel()
                    prefetch_future = None
                break

            # Get audio: from prefetch or synthesize now
            if prefetch_future is not None:
                audio, sr = prefetch_future.result()
                prefetch_future = None
            else:
                audio, sr = vosk_tts_sentence(sentence)

            if len(audio) == 0:
                continue

            audio_dur = len(audio) / sr
            if audio_dur > MAX_AUDIO_ALLOWED_TIME:
                continue

            # Prefetch: look ahead — next sentence in this text, or next queue item
            next_to_prefetch = None
            if si + 1 < len(sentences):
                next_to_prefetch = sentences[si + 1]
            elif len(tts_queue) > 0:
                peek = tts_queue[0]
                if not _is_interrupt(peek):
                    peek_text = peek.get("text", "").strip()
                    if peek_text:
                        peek_sents = split_sentences(peek_text)
                        if peek_sents:
                            next_to_prefetch = peek_sents[0]

            if next_to_prefetch and prefetch_future is None:
                prefetch_future = executor.submit(vosk_tts_sentence, next_to_prefetch)

            # Play (blocking)
            audio_processor.play_sound(audio, sr, blocking=True)
            played += 1

            # Micro-pause between sentences for natural pacing
            if si + 1 < len(sentences):
                # Within same TTS item — short pause
                pause_audio, pause_sr = generate_silence(0.18)
                audio_processor.play_sound(pause_audio, pause_sr, blocking=True)
            elif len(tts_queue) > 0 and not _is_interrupt(tts_queue[0]):
                # Between TTS items (different LLM ideas) — longer pause
                pause_audio, pause_sr = generate_silence(0.35)
                audio_processor.play_sound(pause_audio, pause_sr, blocking=True)

            log.info(f"[TTS] #{played} audio: {audio_dur:.1f}s | '{sentence[:50]}'")

    ctx_swarm["voice"]["is_speaking"] = False
    ctx_swarm["voice"]["text_chunk"] = ""
    executor.shutdown(wait=False)
    total_ms = (time.perf_counter() - total_t0) * 1000
    log.info(f"[TTS] Queue drained: {played} sentences, {total_ms:.0f}ms total")

    ctx_swarm["voice"]["is_speaking"] = False
    ctx_swarm["voice"]["text_chunk"] = ""


def simple_tts_handler(ctx_swarm):
    ctx_env = ctx_swarm["env"]
    audio_processor = AudioProcessor()

    fx_thread = Thread(
        target=fx_sound_handler,
        args=(audio_processor, ctx_swarm),
        daemon=True,
    )
    fx_thread.start()
    tts_queue_handler(audio_processor, ctx_env, ctx_swarm)


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
