"""Streaming orchestrator — LLM token stream -> sentence buffer -> TTS.

Dispatches token streaming to one of two backends based on ``USE_LOCAL_LLM``:
- litellm (cloud, default) — dispatches to whatever CORE_LLM_MODEL_NAME resolves to
- LM Studio local server (requires running LM Studio)

No ctx_swarm / Manager / multiprocessing dependencies — single-process only.
"""

import os
import queue
import re
import threading
import time
from typing import Callable, Generator, List, Optional

import litellm

from tutor.util import log

FAST_MODEL = os.getenv("CORE_LLM_MODEL_NAME", "mistral/mistral-large-latest")

USE_LOCAL_LLM = os.getenv("USE_LOCAL_LLM", "false").lower() in ("true", "1", "yes")

STREAM_TOKEN_TIMEOUT_S = 7   # per-chunk idle in queue.get — THIS is the hang
                              # detector: no token for 7s means the student
                              # asked and no answer is coming. Fires only on a
                              # real stall, never while tokens (progress) flow.
MAX_STREAM_TIME_S = 120      # wall-clock backstop — only a pathological slow
                              # trickle reaches it; a real stall is caught far
                              # sooner by STREAM_TOKEN_TIMEOUT_S. Long mini-
                              # lectures legitimately stream 30-60s, so this must
                              # NOT double as a total-length cap.
FORCE_FLUSH_IDLE_S = 8

_COMPONENT = "llm"


# =========================================================================
# Sentence buffer: accumulates tokens into complete sentences
# =========================================================================

# Sentence endings: .!? followed by clear start of next sentence or end of string.
# A '.' splits only when followed by whitespace + capital letter / digit / quote /
# opening bracket — prevents splitting on dots inside paths like data/db.sqlite
# (after '.' comes lowercase 's' -> no split). '?' and '!' are unambiguous.
# (?<!\d) keeps "1." / "2." intact.
_SENTENCE_END_RE = re.compile(
    r'(?:(?<!\d)\.\s+(?=[A-ZА-ЯЁÀ-Ö0-9"\'(])'
    r'|[!?](?:\s+|$)|[.!?]$)'
)
# Word count threshold: flush even without punctuation
_MAX_WORDS_NO_PUNCT = 20


class SentenceBuffer:
    """Accumulates streaming tokens and yields complete sentences.

    Rules:
    - Flush on .!? followed by whitespace
    - Flush ? immediately (questions get separate TTS for better intonation)
    - Flush when buffer exceeds 20 words without punctuation
    - Don't emit fragments shorter than 4 words (carry to next)
    """

    def __init__(self):
        self.buffer = ""

    def add(self, token: str) -> List[str]:
        """Add a token, return list of complete sentences (may be empty)."""
        self.buffer += token
        sentences = []

        while True:
            m = _SENTENCE_END_RE.search(self.buffer)
            if m:
                end = m.end()
                sentence = self.buffer[:end].strip()
                self.buffer = self.buffer[end:].lstrip()

                if len(sentence.split()) < 4:
                    # Too short to stand alone — glue it to a neighbour:
                    # 1. a following sentence is already complete — merge forward
                    # 2. we already emitted one this batch — append the fragment
                    # 3. nothing to glue to yet — keep buffered, wait for tokens
                    # NB: case 1 must consume past the next boundary. Re-inserting
                    # the fragment and `continue` would re-match the same spot
                    # forever (infinite loop on answers like "Да. ...").
                    m2 = _SENTENCE_END_RE.search(self.buffer)
                    if m2:
                        nxt = self.buffer[:m2.end()].strip()
                        self.buffer = self.buffer[m2.end():].lstrip()
                        merged = (sentence + " " + nxt).strip()
                        if merged:
                            sentences.append(merged)
                        continue
                    if sentences:
                        sentences[-1] = sentences[-1].rstrip() + " " + sentence
                        continue
                    self.buffer = sentence + " " + self.buffer
                    break

                if sentence:
                    sentences.append(sentence)
                continue

            # No punctuation found — check word overflow
            words = self.buffer.split()
            if len(words) >= _MAX_WORDS_NO_PUNCT:
                cut = self.buffer.rfind(",", 0, len(self.buffer) - 10)
                if cut > 10:
                    sentence = self.buffer[:cut].strip()
                    self.buffer = self.buffer[cut + 1:].lstrip()
                else:
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
        from tutor.brain.lm_client import get_lm_studio_client
        client = get_lm_studio_client()
        client.stream_chat_to_queue(messages, q, max_tokens, temperature, stop=stop)
    except Exception as e:
        log(_COMPONENT, f"LM Studio stream error: {e}")
        q.put(None)


def _stream_to_queue_litellm(messages, temperature, max_tokens, q, stop=None):
    """Run litellm streaming in a thread, push tokens to queue.

    Dispatches to whatever CORE_LLM_MODEL_NAME resolves to (Mistral,
    OpenAI gpt-5.x, Claude, etc.) via litellm.
    """
    try:
        _api_base = os.getenv("CORE_LLM_API_BASE")
        _effective = _api_base if _api_base and _api_base != "NONE" else None
        _is_gpt5 = "gpt-5" in FAST_MODEL.lower()
        _total_chars = sum(
            len(m.get("content", "")) for m in messages if isinstance(m, dict)
        )
        log(_COMPONENT,
            f"producer start: {len(messages)} msgs, "
            f"{_total_chars} chars, model={FAST_MODEL}")
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
        log(_COMPONENT,
            f"producer got response object in {time.time() - _t_call:.2f}s, "
            f"starting chunk iteration")
        token_count = 0
        _t_first = None
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                if _t_first is None:
                    _t_first = time.time()
                    log(_COMPONENT,
                        f"first token in {_t_first - _t_call:.2f}s after call: "
                        f"{delta.content[:40]!r}")
                q.put(delta.content)
                token_count += 1
        if token_count == 0:
            log(_COMPONENT, f"WARNING: 0 tokens received from {FAST_MODEL}")
        else:
            log(_COMPONENT,
                f"producer done: {token_count} tokens, "
                f"total {time.time() - _t_call:.2f}s")
    except Exception as e:
        log(_COMPONENT, f"error in litellm thread: {type(e).__name__}: {e}")
    finally:
        q.put(None)


def _stream_to_queue(messages, temperature, max_tokens, q, stop=None):
    """Dispatch to configured backend; backend is responsible for q.put(None)."""
    if USE_LOCAL_LLM:
        _stream_to_queue_lm_studio(messages, temperature, max_tokens, q, stop=stop)
    else:
        _stream_to_queue_litellm(messages, temperature, max_tokens, q, stop=stop)


def stream_fast(messages: list, temperature: float = 0.6,
                max_tokens: int = 500,
                stop: Optional[List[str]] = None) -> Generator[str, None, None]:
    """Stream tokens from fast model with hard timeout per chunk.

    ``stop`` is a list of strings; generation halts when any matches. The matched
    sequence is NOT emitted in the output (standard llama.cpp behaviour).
    """
    _model_label = "LM Studio (local)" if USE_LOCAL_LLM else FAST_MODEL
    log(_COMPONENT,
        f"calling {_model_label}, max_tokens={max_tokens}"
        + (f", stop={stop}" if stop else ""))

    q = queue.Queue()
    t = threading.Thread(
        target=_stream_to_queue,
        args=(messages, temperature, max_tokens, q, stop),
        daemon=True,
    )
    t.start()

    # Wall-clock kill switch: if the producer thread hangs inside litellm's
    # HTTP recv (litellm's own timeout= is unreliable for the streaming endpoint
    # — observed 2026-05-17), this timer guarantees the consumer unblocks after
    # MAX_STREAM_TIME_S by pushing the end-of-stream sentinel. The hung producer
    # thread stays as a leaked daemon — acceptable, main is unblocked.
    # `_done` is set the instant the consumer loop exits, so a stream that
    # finishes in time cancels the timer — otherwise it leaked and fired a
    # confusing (though harmless) "wall-clock abort" line on every normal turn.
    _done = threading.Event()

    def _wall_clock_abort():
        if _done.wait(MAX_STREAM_TIME_S):
            return                       # stream already finished — nothing to abort
        try:
            q.put(None)
            log(_COMPONENT,
                f"wall-clock abort fired at {MAX_STREAM_TIME_S}s -- "
                f"producer thread leaked but consumer unblocked")
        except Exception:
            pass

    abort_timer = threading.Thread(target=_wall_clock_abort, daemon=True)
    abort_timer.start()

    stream_start = time.time()
    got_first_token = False

    try:
        while True:
            try:
                token = q.get(timeout=STREAM_TOKEN_TIMEOUT_S)
            except queue.Empty:
                elapsed = time.time() - stream_start
                if not got_first_token:
                    log(_COMPONENT,
                        f"connection hang: no first token in {elapsed:.0f}s, aborting")
                else:
                    log(_COMPONENT,
                        f"timeout: no tokens for {STREAM_TOKEN_TIMEOUT_S}s, aborting")
                break
            if token is None:
                log(_COMPONENT, "stream finished normally")
                break
            got_first_token = True
            yield token
    finally:
        _done.set()                      # cancel the wall-clock abort timer


# Emotion tags like (neutral) / (thoughtful) / *happy* are leftovers from older
# personas and not used by the current TTS engine. Strip them before sentences
# go to the TTS queue so the synthesiser does not speak the tag literally.
_EMOTION_TAG_RE = re.compile(
    r"\s*[\*\(]\s*("
    r"neutral|happy|sad|angry|scared|whispering|disgusted|sarcastic|"
    r"thoughtful|encouraging"
    r")\s*[\*\)]\s*",
    re.IGNORECASE,
)


# Models keep appending an emotion tag ("...цель. neutral" / "neutral." /
# "Neutral"). Two filters: one trims a trailing tag together with any
# punctuation around it, the other removes any leftover standalone emotion
# word anywhere — these English words never occur as real content in a
# Russian course answer.
_EMOTIONS = (
    r"neutral|happy|sad|angry|scared|whispering|disgusted|sarcastic|"
    r"thoughtful|encouraging"
)
_BARE_EMOTION_TAIL_RE = re.compile(
    r"\s*\b(" + _EMOTIONS + r")\b[\s.,;:!?)\]*—-]*$", re.IGNORECASE,
)
_EMOTION_WORD_RE = re.compile(r"\b(" + _EMOTIONS + r")\b", re.IGNORECASE)


# Board-marker safety net. The primary mechanism is stop=["---BOARD---"] in
# the streaming call (the backend never emits the marker or anything after
# it), but if the model puts a bracket tag inline before reaching the marker
# we still must NOT voice "[BOARD-FORMULA]..." literally through TTS.
_BOARD_TAG_RE = re.compile(r"\[/?BOARD-[A-Z]+\]", re.IGNORECASE)
_BOARD_SEPARATOR_RE = re.compile(r"-{3,}\s*BOARD\s*-{3,}", re.IGNORECASE)


# Emojis / pictographs — Vosk would try to vocalize them. Strip outright.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # emoticons, pictographs, symbols (extended)
    "\U00002600-\U000027BF"   # misc symbols + dingbats
    "\U00002190-\U000021FF"   # arrows
    "\U00002B00-\U00002BFF"   # misc symbols and arrows
    "\U0000FE00-\U0000FE0F"   # variation selectors
    "\U0001F1E6-\U0001F1FF"   # regional indicators
    "]+",
    flags=re.UNICODE,
)


def _scrub(sentence: str) -> str:
    """Remove inline orchestration markers (emotion tags, emojis, board tags)."""
    cleaned = _EMOTION_TAG_RE.sub(" ", sentence)
    cleaned = _BARE_EMOTION_TAIL_RE.sub("", cleaned)
    cleaned = _EMOTION_WORD_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = _BOARD_SEPARATOR_RE.sub("", cleaned)
    cleaned = _BOARD_TAG_RE.sub("", cleaned)
    return cleaned.strip()


BOARD_MARKER = "---BOARD---"


def stream_response_sentences(messages: list, temperature: float = 0.6,
                              max_tokens: int = 500,
                              stop: Optional[List[str]] = None,
                              board_capture: Optional[Callable[[str], None]] = None,
                              ) -> Generator[str, None, str]:
    """Stream LLM response and yield complete sentences.

    Yields sentences as they become complete.
    Returns full response text when generator exhausts.

    ``stop`` is forwarded to the LLM backend (e.g. ["[END]"]) to halt generation
    cleanly when the model writes a completion marker. NB: OpenAI GPT-5.x does
    not accept this parameter — pass ``None`` for that backend.

    ``board_capture`` — when set, the stream is split at the BOARD_MARKER
    (``---BOARD---``). Pre-marker text feeds the sentence buffer as usual;
    post-marker text is collected and passed to the callback at stream end.
    This is how the board sidecar gets [BOARD-*] tags without a second LLM
    call and without TTS ever seeing the marker or tags.
    """
    buffer = SentenceBuffer()
    full_response = ""
    board_text = ""
    pre_board = True
    fed_chars = 0   # how many chars of full_response we have already fed to `buffer`
    _last_yield_time = time.time()

    # When using local LLM with trigger word, sentences containing
    # "TRIGGER_START" are artifacts of the thinking filter and should be skipped.
    _trigger = "TRIGGER_START" if USE_LOCAL_LLM else None

    def _emit(sentence: str) -> Optional[str]:
        if _trigger and _trigger in sentence:
            sentence = sentence.split(_trigger, 1)[-1].strip()
            if not sentence:
                return None
        sentence = _scrub(sentence)
        return sentence or None

    for token in stream_fast(messages, temperature, max_tokens, stop=stop):
        full_response += token

        if not pre_board:
            board_text += token
            continue

        idx = full_response.find(BOARD_MARKER)
        if idx < 0:
            # Whole token is pre-marker, but the marker may be split across
            # tokens — hold back the last (len(BOARD_MARKER) - 1) characters
            # from the buffer so we don't leak a partial marker into TTS.
            safe_upto = max(fed_chars, len(full_response) - (len(BOARD_MARKER) - 1))
            if safe_upto > fed_chars:
                chunk = full_response[fed_chars:safe_upto]
                fed_chars = safe_upto
                for sentence in buffer.add(chunk):
                    out = _emit(sentence)
                    if out:
                        _last_yield_time = time.time()
                        yield out
        else:
            # Marker fully present in full_response. Feed the unfed pre-marker
            # tail to the buffer, then switch to board-capture mode.
            if idx > fed_chars:
                chunk = full_response[fed_chars:idx]
                for sentence in buffer.add(chunk):
                    out = _emit(sentence)
                    if out:
                        _last_yield_time = time.time()
                        yield out
            fed_chars = idx
            pre_board = False
            board_text = full_response[idx + len(BOARD_MARKER):]

        # Force flush if buffer hasn't yielded a sentence in FORCE_FLUSH_IDLE_S
        # (some cloud models generate long text without punctuation)
        if time.time() - _last_yield_time > FORCE_FLUSH_IDLE_S and buffer.buffer.strip():
            forced = buffer.flush()
            if forced:
                out = _emit(forced)
                if out:
                    log(_COMPONENT,
                        f"force-flushing buffer after 8s: '{out[:50]}'")
                    _last_yield_time = time.time()
                    yield out

    # If the marker never arrived, flush the chars we were holding back.
    if pre_board and fed_chars < len(full_response):
        tail = full_response[fed_chars:]
        for sentence in buffer.add(tail):
            out = _emit(sentence)
            if out:
                yield out

    # Flush remaining buffered text
    remaining = buffer.flush()
    if remaining:
        out = _emit(remaining)
        if out:
            yield out

    if board_capture and board_text.strip():
        try:
            board_capture(board_text)
        except Exception as exc:
            log(_COMPONENT, f"board_capture failed: {type(exc).__name__}: {exc}")

    return full_response
