"""Streaming orchestrator — LLM token stream → sentence buffer → TTS.

Dispatches token streaming to one of two backends based on ``USE_LOCAL_LLM``:
- Mistral API via litellm (cloud, default)
- LM Studio local server (requires running LM Studio)
"""

import os
import re
import threading
import time
from typing import Generator, List, Optional

import litellm

FAST_MODEL = os.getenv("CORE_LLM_MODEL_NAME", "mistral/mistral-large-latest")

USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() in ("true", "1", "yes")

STREAM_TOKEN_TIMEOUT_S = 10
MAX_STREAM_TIME_S = 30
FORCE_FLUSH_IDLE_S = 8


# =========================================================================
# Sentence buffer: accumulates tokens into complete sentences
# =========================================================================

# Sentence endings: .!? followed by space or end of string
# Sentence end: .!? followed by space, but NOT after a digit (e.g. "1." "2.")
_SENTENCE_END_RE = re.compile(r'(?<!\d)([.!?])(?:\s+|$)')
# Word count threshold: flush even without punctuation
_MAX_WORDS_NO_PUNCT = 20


class SentenceBuffer:
    """Accumulates streaming tokens and yields complete sentences.

    Rules:
    - Flush on .!? followed by whitespace
    - Flush ? immediately (questions get separate TTS for better intonation)
    - Flush when buffer exceeds 20 words without punctuation
    - Don't emit fragments shorter than 3 words (carry to next)
    """

    def __init__(self):
        self.buffer = ""

    def add(self, token: str) -> List[str]:
        """Add a token, return list of complete sentences (may be empty)."""
        self.buffer += token
        sentences = []

        while True:
            # Find sentence boundary
            m = _SENTENCE_END_RE.search(self.buffer)
            if m:
                end = m.end()
                sentence = self.buffer[:end].strip()
                self.buffer = self.buffer[end:].lstrip()

                if len(sentence.split()) < 3 and self.buffer:
                    # Too short — prepend to next sentence
                    self.buffer = sentence + " " + self.buffer
                    continue

                if sentence:
                    sentences.append(sentence)
                continue

            # No punctuation found — check word overflow
            words = self.buffer.split()
            if len(words) >= _MAX_WORDS_NO_PUNCT:
                # Force flush at last comma or space
                cut = self.buffer.rfind(",", 0, len(self.buffer) - 10)
                if cut > 10:
                    sentence = self.buffer[:cut].strip()
                    self.buffer = self.buffer[cut + 1:].lstrip()
                else:
                    # No good break point — flush all
                    sentence = self.buffer.strip()
                    self.buffer = ""
                if sentence:
                    sentences.append(sentence)
                continue

            break

        return sentences

    def flush(self) -> Optional[str]:
        """Return remaining text. Call when stream ends."""
        remaining = self.buffer.strip()
        self.buffer = ""
        return remaining if remaining else None


# =========================================================================
# Streaming LLM call
# =========================================================================

def _stream_to_queue_lm_studio(messages, temperature, max_tokens, q):
    """Stream tokens from LM Studio local server, push to queue."""
    try:
        from agent.lm_studio_client import get_lm_studio_client
        client = get_lm_studio_client()
        client.stream_chat_to_queue(messages, q, max_tokens, temperature)
    except Exception as e:
        print(f"[STREAM LM] Error: {e}", flush=True)
        q.put(None)


def _stream_to_queue_mistral(messages, temperature, max_tokens, q):
    """Run litellm streaming in a thread, push tokens to queue."""
    try:
        _api_base = os.getenv("CORE_LLM_API_BASE")
        _effective = _api_base if _api_base and _api_base != "NONE" else None
        response = litellm.completion(
            model=FAST_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            timeout=STREAM_TOKEN_TIMEOUT_S,
            api_base=_effective,
        )
        token_count = 0
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                q.put(delta.content)
                token_count += 1
        if token_count == 0:
            print(f"[STREAM] WARNING: 0 tokens received from {FAST_MODEL}", flush=True)
    except Exception as e:
        print(f"[STREAM] Error in thread: {e}", flush=True)
    finally:
        q.put(None)


def _stream_to_queue(messages, temperature, max_tokens, q):
    """Dispatch to the configured backend; each backend is responsible for
    pushing tokens into ``q`` and terminating with ``q.put(None)``.
    """
    if USE_LOCAL_LLM:
        _stream_to_queue_lm_studio(messages, temperature, max_tokens, q)
    else:
        _stream_to_queue_mistral(messages, temperature, max_tokens, q)


def stream_fast(messages: list, temperature: float = 0.6,
                max_tokens: int = 500) -> Generator[str, None, None]:
    """Stream tokens from fast model with hard timeout per chunk."""
    import queue
    _model_label = "LM Studio (local)" if USE_LOCAL_LLM else FAST_MODEL
    print(f"[STREAM] Calling {_model_label}, max_tokens={max_tokens}", flush=True)

    q = queue.Queue()
    t = threading.Thread(
        target=_stream_to_queue,
        args=(messages, temperature, max_tokens, q),
        daemon=True,
    )
    t.start()

    stream_start = time.time()
    got_first_token = False

    while True:
        try:
            token = q.get(timeout=STREAM_TOKEN_TIMEOUT_S)
        except queue.Empty:
            elapsed = time.time() - stream_start
            if not got_first_token:
                print(f"[STREAM] Connection hang: no first token in {elapsed:.0f}s, aborting", flush=True)
            else:
                print(f"[STREAM] Timeout: no tokens for {STREAM_TOKEN_TIMEOUT_S}s, aborting", flush=True)
            break
        if token is None:
            print("[STREAM] Stream finished normally", flush=True)
            break
        if time.time() - stream_start > MAX_STREAM_TIME_S:
            print(f"[STREAM] Max stream time {MAX_STREAM_TIME_S}s reached, aborting", flush=True)
            break
        got_first_token = True
        yield token


def stream_response_sentences(messages: list, temperature: float = 0.6,
                              max_tokens: int = 500) -> Generator[str, None, str]:
    """Stream LLM response and yield complete sentences.

    Yields sentences as they become complete.
    Returns full response text when generator exhausts.

    Usage:
        gen = stream_response_sentences(messages)
        full = ""
        for sentence in gen:
            tts_queue.append({"text": sentence, "emotion": "neutral"})
            full += sentence + " "
    """
    buffer = SentenceBuffer()
    full_response = ""
    _resp_start = time.time()
    _last_yield_time = time.time()

    # When using local LLM with trigger word, sentences containing
    # "TRIGGER_START" are artifacts of the thinking filter and should be skipped.
    _trigger = "TRIGGER_START" if USE_LOCAL_LLM else None

    for token in stream_fast(messages, temperature, max_tokens):
        full_response += token
        sentences = buffer.add(token)
        for sentence in sentences:
            if _trigger and _trigger in sentence:
                # Strip trigger and keep only the part after it
                sentence = sentence.split(_trigger, 1)[-1].strip()
                if not sentence:
                    continue
            _last_yield_time = time.time()
            yield sentence

        # Force flush if buffer hasn't yielded a sentence in FORCE_FLUSH_IDLE_S
        # (Mistral sometimes generates long text without punctuation)
        if time.time() - _last_yield_time > FORCE_FLUSH_IDLE_S and buffer.buffer.strip():
            forced = buffer.flush()
            if forced:
                if _trigger and _trigger in forced:
                    forced = forced.split(_trigger, 1)[-1].strip()
                if forced:
                    print(f"[STREAM] Force-flushing buffer after 8s: '{forced[:50]}'", flush=True)
                    _last_yield_time = time.time()
                    yield forced

    # Flush remaining
    remaining = buffer.flush()
    if remaining:
        if _trigger and _trigger in remaining:
            remaining = remaining.split(_trigger, 1)[-1].strip()
        if remaining:
            yield remaining

    return full_response
