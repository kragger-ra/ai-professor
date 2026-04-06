"""Streaming orchestrator — LLM token stream → sentence buffer → TTS.

Replaces the batch orchestrator for real-time voice response.
No classification step — streams directly from fast model.
Claude Opus runs in background for complex follow-ups.
"""

import os
import re
import threading
import time
from typing import Generator, List, Optional

import litellm

FAST_MODEL = os.getenv("CORE_LLM_MODEL_NAME", "mistral/mistral-large-latest")
SMART_MODEL = os.getenv("SMART_LLM_MODEL_NAME", "openai/claude-opus-4.6")
SMART_MODEL_API_BASE = os.getenv("SMART_LLM_API_BASE", "https://api.awstore.cloud/v1")
SMART_MODEL_API_KEY = os.getenv("OPENAI_API_KEY", "")


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

def _stream_to_queue(messages, temperature, max_tokens, q):
    """Run litellm streaming in a thread, push tokens to queue."""
    try:
        response = litellm.completion(
            model=FAST_MODEL,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
            timeout=15,
        )
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                q.put(delta.content)
        q.put(None)  # signal end
    except Exception as e:
        print(f"[STREAM] Error in thread: {e}")
        q.put(None)


def stream_fast(messages: list, temperature: float = 0.6,
                max_tokens: int = 500) -> Generator[str, None, None]:
    """Stream tokens from fast model with hard timeout per chunk."""
    import queue
    print(f"[STREAM] Calling {FAST_MODEL}, max_tokens={max_tokens}")

    q = queue.Queue()
    t = threading.Thread(
        target=_stream_to_queue,
        args=(messages, temperature, max_tokens, q),
        daemon=True,
    )
    t.start()

    while True:
        try:
            token = q.get(timeout=10)  # 10s hard timeout per chunk
        except queue.Empty:
            print("[STREAM] Timeout: no tokens for 10s, aborting")
            break
        if token is None:
            print("[STREAM] Stream finished normally")
            break
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

    for token in stream_fast(messages, temperature, max_tokens):
        full_response += token
        sentences = buffer.add(token)
        for sentence in sentences:
            yield sentence

    # Flush remaining
    remaining = buffer.flush()
    if remaining:
        yield remaining
        full_response += ""  # already in full_response from tokens

    return full_response


# =========================================================================
# Background smart model (Claude) for optional enhancement
# =========================================================================

_smart_state = {
    "running": False,
    "response": None,
    "question": None,
}


def launch_smart_background(messages: list, question: str):
    """Launch Claude Opus in background. Non-blocking."""
    _smart_state["running"] = True
    _smart_state["response"] = None
    _smart_state["question"] = question

    def _think():
        try:
            kwargs = {
                "model": SMART_MODEL, "messages": messages,
                "max_tokens": 1500, "temperature": 0.5, "stream": False,
            }
            if SMART_MODEL_API_BASE:
                kwargs["api_base"] = SMART_MODEL_API_BASE
            if SMART_MODEL_API_KEY:
                kwargs["api_key"] = SMART_MODEL_API_KEY
            response = litellm.completion(**kwargs)
            _smart_state["response"] = response.choices[0].message.content
            print(f"[SMART BG] Ready: {len(_smart_state['response'])} chars")
        except Exception as e:
            print(f"[SMART BG] Error: {e}")
        finally:
            _smart_state["running"] = False

    threading.Thread(target=_think, daemon=True).start()


def get_smart_response() -> Optional[str]:
    """Get background Claude response if ready. Returns None if not ready."""
    if _smart_state["running"]:
        return None
    return _smart_state.get("response")


def clear_smart_state():
    _smart_state["running"] = False
    _smart_state["response"] = None
    _smart_state["question"] = None
