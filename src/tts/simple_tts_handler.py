"""Vosk TTS queue handler with sentence-level prefetch and interrupts.

Single backend: Vosk. The ``TTS_BACKEND`` env var is still read so ops can
confirm what is running, but any non-``vosk`` value is ignored and logged.
"""

import concurrent.futures
import logging
import os
import time
import traceback
from threading import Thread
from typing import Optional

from tts.audio_device import AudioProcessor
from tts.vosk.vosk_tts import (
    emotion_prosody,
    generate_silence,
    pause_for_sentence,
    split_sentences,
    vosk_tts_sentence,
)

_TTS_BACKEND = os.getenv("TTS_BACKEND", "vosk")
if _TTS_BACKEND != "vosk":
    logging.getLogger("tts-handler").warning(
        f"[TTS] TTS_BACKEND={_TTS_BACKEND!r} is not supported; using vosk"
    )

log = logging.getLogger("tts-handler")

MAX_AUDIO_ALLOWED_TIME = 60  # seconds per TTS utterance
# Inter-LLM-message base pause; intra-message pauses are computed per sentence
# from punctuation (see pause_for_sentence) and scaled by emotion's pause_mul.
INTER_ITEM_PAUSE_S = 0.35
QUEUE_OVERFLOW_LIMIT = 10
QUEUE_OVERFLOW_KEEP = 3


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


def check_tts_queue(
    audio_processor, ctx_swarm, check_interrupt=False
) -> Optional[bool]:
    """Process one batch of pending TTS items via the vosk streaming handler."""
    tts_queue = ctx_swarm["tts_queue"]
    if len(tts_queue) == 0:
        if check_interrupt:
            return False
        return None

    try:
        head = tts_queue[0]
        if not head:
            if check_interrupt:
                return False
            return None

        if _is_interrupt(head):
            tts_queue.pop(0)
            return True if check_interrupt else None

        if check_interrupt:
            return False

        _handle_vosk_queue_stream(audio_processor, ctx_swarm)
    except Exception as e:
        print("ERROR AUDIO GENERATE =(", e)
        traceback.print_exc()
        time.sleep(10)
    if check_interrupt:
        return False
    return None


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
    if len(tts_queue) > QUEUE_OVERFLOW_LIMIT:
        overflow_count = len(tts_queue) - QUEUE_OVERFLOW_KEEP
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
        emotion = tts_dict.get("emotion", "neutral") or "neutral"
        _, pause_mul = emotion_prosody(emotion)

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
                audio, sr = vosk_tts_sentence(sentence, emotion)

            if len(audio) == 0:
                continue

            audio_dur = len(audio) / sr
            if audio_dur > MAX_AUDIO_ALLOWED_TIME:
                continue

            # Prefetch: look ahead — next sentence in this text, or next queue item
            next_to_prefetch = None
            next_emotion = emotion
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
                            next_emotion = peek.get("emotion", "neutral") or "neutral"

            if next_to_prefetch and prefetch_future is None:
                prefetch_future = executor.submit(
                    vosk_tts_sentence, next_to_prefetch, next_emotion
                )

            # Play (blocking)
            audio_processor.play_sound(audio, sr, blocking=True)
            played += 1

            # Variable pause: depends on this sentence's punctuation, scaled by emotion.
            if si + 1 < len(sentences):
                base_pause = pause_for_sentence(sentence)
                pause_audio, pause_sr = generate_silence(base_pause * pause_mul)
                audio_processor.play_sound(pause_audio, pause_sr, blocking=True)
            elif len(tts_queue) > 0 and not _is_interrupt(tts_queue[0]):
                pause_audio, pause_sr = generate_silence(INTER_ITEM_PAUSE_S * pause_mul)
                audio_processor.play_sound(pause_audio, pause_sr, blocking=True)

            log.info(f"[TTS] #{played} audio: {audio_dur:.1f}s | '{sentence[:50]}'")

    ctx_swarm["voice"]["is_speaking"] = False
    ctx_swarm["voice"]["text_chunk"] = ""
    executor.shutdown(wait=False)
    total_ms = (time.perf_counter() - total_t0) * 1000
    log.info(f"[TTS] Queue drained: {played} sentences, {total_ms:.0f}ms total")


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
    if not fx_queue:
        return
    ctx_env = ctx_swarm["env"]
    while ctx_env["actived"]:
        try:
            sound_name = fx_queue.get()
            audio_processor.play_fx(sound_name)
        except Exception as e:
            print("ERROR FX PLAY =(", e)
            time.sleep(10)
        time.sleep(0.1)
