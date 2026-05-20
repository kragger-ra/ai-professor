"""Vosk TTS queue handler with sentence-level prefetch and interrupts.

Single backend: Vosk. The ``TTS_BACKEND`` env var is still read so ops can
confirm what is running, but any non-``vosk`` value is ignored and logged.
"""

import concurrent.futures
import logging
import os
import threading
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
from utils.session_recorder import get_recorder as _session_recorder, is_enabled as _session_record_on

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
# Overflow protection guards against a streaming response runaway. Monolithic
# lectures push 20-40 sentences in one go — they're a coherent batch and must
# NOT be truncated. Raised from 10 to 60 to accommodate that.
QUEUE_OVERFLOW_LIMIT = 60
QUEUE_OVERFLOW_KEEP = 50


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

    A small watcher thread monitors `voice["student_speaking"]` and the
    `tts_queue` head for an interrupt sentinel during playback. STT runs in a
    separate process, so without the watcher the only interrupt check happens
    between sentences (after blocking `play_sound` returns) and the agent
    keeps talking for several seconds. The watcher calls
    `interrupt_main_device()` while a sentence is still playing, which the
    chunked `_play_safe` loop reacts to within ~100 ms.
    """
    tts_queue = ctx_swarm["tts_queue"]
    voice = ctx_swarm["voice"]
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    prefetch_future = None
    total_t0 = time.perf_counter()
    played = 0

    voice["is_speaking"] = True
    interrupt_event = threading.Event()
    watcher_stop = threading.Event()

    def _interrupt_watcher():
        while not watcher_stop.is_set():
            try:
                triggered = False
                if voice.get("student_speaking"):
                    triggered = True
                else:
                    if len(tts_queue) > 0:
                        head = tts_queue[0]
                        if head and _is_interrupt(head):
                            triggered = True
                if triggered:
                    audio_processor.interrupt_main_device()
                    interrupt_event.set()
                    log.info("[TTS] Interrupt watcher fired — stopping playback")
                    return
            except Exception:
                pass
            time.sleep(0.03)

    watcher = Thread(target=_interrupt_watcher, daemon=True)
    watcher.start()

    try:
        # Queue overflow protection — only triggers for an actual runaway.
        if len(tts_queue) > QUEUE_OVERFLOW_LIMIT:
            overflow_count = len(tts_queue) - QUEUE_OVERFLOW_KEEP
            for _ in range(overflow_count):
                tts_queue.pop(0)
            log.warning(f"[TTS] Queue overflow! Dropped {overflow_count} items")

        while len(tts_queue) > 0:
            if interrupt_event.is_set():
                break
            tts_dict = tts_queue.pop(0)
            if _is_interrupt(tts_dict):
                audio_processor.interrupt_main_device()
                interrupt_event.set()
                break

            text = tts_dict.get("text", "").strip()
            if not text:
                continue
            emotion = tts_dict.get("emotion", "neutral") or "neutral"
            _, pause_mul = emotion_prosody(emotion)

            sentences = split_sentences(text)

            for si, sentence in enumerate(sentences):
                if interrupt_event.is_set() or _check_for_interrupt(tts_queue):
                    audio_processor.interrupt_main_device()
                    interrupt_event.set()
                    break

                # Get audio: from prefetch or synthesize now
                if prefetch_future is not None:
                    audio, sr = prefetch_future.result()
                    prefetch_future = None
                else:
                    audio, sr = vosk_tts_sentence(sentence, emotion)

                if interrupt_event.is_set():
                    break

                if len(audio) == 0:
                    print(f"[TTS-DROP-EMPTY] Vosk returned empty WAV for: '{sentence[:200]}'", flush=True)
                    continue

                audio_dur = len(audio) / sr
                if audio_dur > MAX_AUDIO_ALLOWED_TIME:
                    print(f"[TTS-DROP-LONG] {audio_dur:.1f}s > {MAX_AUDIO_ALLOWED_TIME}s for: '{sentence[:200]}'", flush=True)
                    continue
                # Anomaly: too-short WAV for the text length. Normal Russian TTS
                # pace is ~0.25-0.35s per word. Below 0.10s/word means Vosk
                # silently aborted mid-sentence — flag it but still play what
                # we have (better partial than nothing).
                _wc = max(1, len(sentence.split()))
                if audio_dur / _wc < 0.10:
                    print(f"[TTS-ANOMALY-SHORT] {audio_dur:.1f}s for {_wc} words "
                          f"(={audio_dur/_wc:.2f}s/word) — likely cut off: '{sentence[:200]}'", flush=True)
                print(f"[TTS-PLAYED] {audio_dur:.1f}s: '{sentence[:200]}'", flush=True)

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

                if next_to_prefetch and prefetch_future is None and not interrupt_event.is_set():
                    prefetch_future = executor.submit(
                        vosk_tts_sentence, next_to_prefetch, next_emotion
                    )

                # Mirror to disk for the volunteer session (no-op unless SESSION_RECORD=true).
                if _session_record_on():
                    try:
                        _session_recorder("tts").write(audio, sr)
                    except Exception as _e:
                        log.warning(f"[TTS] session-record write failed: {_e}")
                # Play (blocking). Watcher will trigger interrupt_main_device()
                # mid-playback if the student starts speaking, and _play_safe
                # breaks out within one chunk (~100 ms).
                audio_processor.play_sound(audio, sr, blocking=True)
                played += 1

                # Publish what was JUST played + when. The agent's blocked-
                # lecture timer logic keys off this so "12 seconds to answer"
                # starts from the actual end of the audio, not from when we
                # popped the queue. Skip on interrupt — last_played_text
                # should reflect FULL playback only.
                if not interrupt_event.is_set():
                    try:
                        voice["last_played_text"] = sentence
                        voice["last_played_at"] = time.time()
                    except Exception:
                        pass

                if interrupt_event.is_set():
                    break

                # Variable pause: depends on this sentence's punctuation, scaled by emotion.
                if si + 1 < len(sentences):
                    base_pause = pause_for_sentence(sentence)
                    pause_audio, pause_sr = generate_silence(base_pause * pause_mul)
                    audio_processor.play_sound(pause_audio, pause_sr, blocking=True)
                elif len(tts_queue) > 0 and not _is_interrupt(tts_queue[0]):
                    pause_audio, pause_sr = generate_silence(INTER_ITEM_PAUSE_S * pause_mul)
                    audio_processor.play_sound(pause_audio, pause_sr, blocking=True)

                log.info(f"[TTS] #{played} audio: {audio_dur:.1f}s | '{sentence[:50]}'")

            if interrupt_event.is_set():
                break
    finally:
        watcher_stop.set()
        if prefetch_future is not None:
            prefetch_future.cancel()
            prefetch_future = None
        # If interrupted, drop any residue from this turn so the next
        # `_handle_vosk_queue_stream` call starts clean.
        if interrupt_event.is_set():
            try:
                while len(tts_queue) > 0:
                    head = tts_queue[0]
                    if head and _is_interrupt(head):
                        tts_queue.pop(0)
                    else:
                        break
            except Exception:
                pass
        voice["is_speaking"] = False
        voice["text_chunk"] = ""
        executor.shutdown(wait=False)
        total_ms = (time.perf_counter() - total_t0) * 1000
        log.info(
            f"[TTS] Queue drained: {played} sentences, {total_ms:.0f}ms total"
            + (" [INTERRUPTED]" if interrupt_event.is_set() else "")
        )


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
