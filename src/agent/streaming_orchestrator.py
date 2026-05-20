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

STREAM_TOKEN_TIMEOUT_S = 7   # per-chunk idle in queue.get
MAX_STREAM_TIME_S = 30       # wall-clock max — separate timer thread enforces
                              # this even if litellm's HTTP recv hangs and our
                              # in-loop checks never fire (incident 2026-05-17:
                              # process sat dead for 3+ minutes on a long Q&A).
FORCE_FLUSH_IDLE_S = 8


# =========================================================================
# Sentence buffer: accumulates tokens into complete sentences
# =========================================================================

# Sentence endings: .!? followed by clear start of next sentence or end of string.
# A '.' splits only when followed by whitespace + capital letter / digit / quote /
# opening bracket — this prevents splitting on dots inside paths and identifiers
# like `data/natyan_database.sqlite` (after `.` comes lowercase `s` -> no split).
# `?` and `!` are unambiguous — always split. `(?<!\d)` keeps "1." / "2." intact.
_SENTENCE_END_RE = re.compile(
    r'(?:(?<!\d)\.\s+(?=[А-ЯA-ZЁ0-9«"\'(])|[!?](?:\s+|$)|[.!?]$)'
)
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

                if len(sentence.split()) < 4:
                    # Too short — likely a leftover fragment (e.g. `sqlite`.` after
                    # a path got split at a `.\sCapital` boundary, or a stray
                    # tail like "Да."). Try to glue:
                    #   1. If buffer still has content — prepend to next sentence
                    #   2. Else, if we already emitted something in this batch —
                    #      glue back onto the previous sentence
                    #   3. Else — keep in buffer, wait for more tokens
                    if self.buffer:
                        self.buffer = sentence + " " + self.buffer
                        continue
                    if sentences:
                        sentences[-1] = sentences[-1].rstrip() + " " + sentence
                        continue
                    # standalone tiny utterance, just keep in buffer
                    self.buffer = sentence
                    break

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

def _stream_to_queue_lm_studio(messages, temperature, max_tokens, q, stop=None):
    """Stream tokens from LM Studio local server, push to queue."""
    try:
        from agent.lm_studio_client import get_lm_studio_client
        client = get_lm_studio_client()
        client.stream_chat_to_queue(messages, q, max_tokens, temperature, stop=stop)
    except Exception as e:
        print(f"[STREAM LM] Error: {e}", flush=True)
        q.put(None)


def _stream_to_queue_mistral(messages, temperature, max_tokens, q, stop=None):
    """Run litellm streaming in a thread, push tokens to queue.

    Despite the name, this dispatches to whatever CORE_LLM_MODEL_NAME resolves
    to (Mistral, OpenAI gpt-5.x, Claude, etc.) via litellm.
    """
    try:
        _api_base = os.getenv("CORE_LLM_API_BASE")
        _effective = _api_base if _api_base and _api_base != "NONE" else None
        _is_gpt5 = "gpt-5" in FAST_MODEL.lower()
        # Diagnostic: size of every message we ship, so a stuck request can be
        # correlated with prompt bloat (long history / RAG injects / etc.).
        _total_chars = sum(len(m.get("content", "")) for m in messages
                            if isinstance(m, dict))
        print(
            f"[STREAM] producer start: {len(messages)} msgs, "
            f"{_total_chars} chars, model={FAST_MODEL}",
            flush=True,
        )
        kwargs = dict(
            model=FAST_MODEL,
            messages=messages,
            temperature=temperature,
            stream=True,
            timeout=STREAM_TOKEN_TIMEOUT_S,
            api_base=_effective,
        )
        if _is_gpt5:
            kwargs["max_completion_tokens"] = max_tokens
            _reasoning = os.getenv("LM_STUDIO_REASONING_EFFORT", "").strip()
            if _reasoning:
                kwargs["reasoning_effort"] = _reasoning
        else:
            kwargs["max_tokens"] = max_tokens
        if stop:
            kwargs["stop"] = stop
        _t_call = time.time()
        response = litellm.completion(**kwargs)
        print(
            f"[STREAM] producer got response object in "
            f"{time.time() - _t_call:.2f}s, starting chunk iteration",
            flush=True,
        )
        token_count = 0
        _t_first = None
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                if _t_first is None:
                    _t_first = time.time()
                    print(
                        f"[STREAM] first token in "
                        f"{_t_first - _t_call:.2f}s after call: "
                        f"{delta.content[:40]!r}",
                        flush=True,
                    )
                q.put(delta.content)
                token_count += 1
        if token_count == 0:
            print(f"[STREAM] WARNING: 0 tokens received from {FAST_MODEL}", flush=True)
        else:
            print(
                f"[STREAM] producer done: {token_count} tokens, "
                f"total {time.time() - _t_call:.2f}s",
                flush=True,
            )
    except Exception as e:
        print(f"[STREAM] Error in thread: {type(e).__name__}: {e}", flush=True)
    finally:
        q.put(None)


def _stream_to_queue(messages, temperature, max_tokens, q, stop=None):
    """Dispatch to the configured backend; each backend is responsible for
    pushing tokens into ``q`` and terminating with ``q.put(None)``.
    """
    if USE_LOCAL_LLM:
        _stream_to_queue_lm_studio(messages, temperature, max_tokens, q, stop=stop)
    else:
        _stream_to_queue_mistral(messages, temperature, max_tokens, q, stop=stop)


def stream_fast(messages: list, temperature: float = 0.6,
                max_tokens: int = 500,
                stop: Optional[List[str]] = None) -> Generator[str, None, None]:
    """Stream tokens from fast model with hard timeout per chunk.

    `stop` is a list of strings; generation halts when any matches. The matched
    sequence is NOT emitted in the output (standard llama.cpp behavior).
    """
    import queue
    _model_label = "LM Studio (local)" if USE_LOCAL_LLM else FAST_MODEL
    print(f"[STREAM] Calling {_model_label}, max_tokens={max_tokens}"
          + (f", stop={stop}" if stop else ""), flush=True)

    q = queue.Queue()
    t = threading.Thread(
        target=_stream_to_queue,
        args=(messages, temperature, max_tokens, q, stop),
        daemon=True,
    )
    t.start()

    # Wall-clock kill switch: if the producer thread is hung inside
    # litellm's HTTP recv (litellm's own `timeout=` is unreliable for the
    # streaming endpoint — observed 2026-05-17), this timer guarantees the
    # consumer unblocks after MAX_STREAM_TIME_S by pushing the end-of-
    # stream sentinel into the queue. The hung producer thread stays as a
    # leaked daemon — acceptable because main is unblocked and the process
    # itself is fine.
    def _wall_clock_abort():
        time.sleep(MAX_STREAM_TIME_S)
        try:
            q.put(None)
            print(f"[STREAM] Wall-clock abort fired at {MAX_STREAM_TIME_S}s — "
                  f"producer thread leaked but consumer unblocked", flush=True)
        except Exception:
            pass

    abort_timer = threading.Thread(target=_wall_clock_abort, daemon=True)
    abort_timer.start()

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


_SKELETON_MARKER_RE = re.compile(r"\s*\[ПУНКТ\s*\d+\]\s*")

# Emotion tags like (neutral) / (thoughtful) / *happy* are leftovers from older
# personas and not used by the current TTS engine. Strip them before sentences
# go to the TTS queue so the synthesiser doesn't speak the tag literally.
_EMOTION_TAG_RE = re.compile(
    r"\s*[\*\(]\s*("
    r"neutral|happy|sad|angry|scared|whispering|disgusted|sarcastic|"
    r"thoughtful|encouraging"
    r")\s*[\*\)]\s*",
    re.IGNORECASE,
)


def _scrub(sentence: str) -> str:
    """Remove inline orchestration markers (skeleton points, emotion tags)."""
    cleaned = _SKELETON_MARKER_RE.sub(" ", sentence)
    cleaned = _EMOTION_TAG_RE.sub(" ", cleaned)
    return cleaned.strip()


def stream_response_sentences(messages: list, temperature: float = 0.6,
                              max_tokens: int = 500,
                              stop: Optional[List[str]] = None,
                              ) -> Generator[str, None, str]:
    """Stream LLM response and yield complete sentences.

    Yields sentences as they become complete.
    Returns full response text when generator exhausts.

    `stop` is forwarded to the LLM backend (e.g. ["[END]"]) to halt generation
    cleanly when the model writes a completion marker.

    Skeleton markers like "[ПУНКТ N]" are stripped from emitted sentences but
    retained in the full_response return value for upstream tracking.

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

    for token in stream_fast(messages, temperature, max_tokens, stop=stop):
        full_response += token
        sentences = buffer.add(token)
        for sentence in sentences:
            if _trigger and _trigger in sentence:
                # Strip trigger and keep only the part after it
                sentence = sentence.split(_trigger, 1)[-1].strip()
                if not sentence:
                    continue
            sentence = _scrub(sentence)
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
                forced = _scrub(forced)
                if forced:
                    print(f"[STREAM] Force-flushing buffer after 8s: '{forced[:50]}'", flush=True)
                    _last_yield_time = time.time()
                    yield forced

    # Flush remaining
    remaining = buffer.flush()
    if remaining:
        if _trigger and _trigger in remaining:
            remaining = remaining.split(_trigger, 1)[-1].strip()
        remaining = _scrub(remaining)
        if remaining:
            yield remaining

    return full_response
