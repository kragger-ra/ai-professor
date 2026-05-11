"""LM Studio client with Prompt Caching and heartbeat.

LM Studio provides an OpenAI-compatible API on localhost:1234.
Prompt Caching works automatically: if the beginning of the prompt matches
a previous request, LM Studio skips reprocessing those tokens.

Heartbeat prevents "cold start" — without requests for >3-5s (with tools)
or >30s (without), LM Studio evicts the KV cache and TTFT jumps from ~1s to 3+s.

This client provides both async (aiohttp) and sync (requests) interfaces,
since the Professor codebase uses synchronous threading.

Based on NetTyan's proven approach:
- Keepalive ping every N seconds with max_tokens=1
- Stream MUST be fully drained for cache to be saved
- Prefix matching is token-level: same prefix = cache hit
"""

import json
import os
import queue
import re
import threading
import time
from typing import Callable, Dict, Generator, List, Optional

import requests

# Trigger word that marks the start of the actual response.
# Everything before this marker is leaked thinking and gets stripped.
RESPONSE_TRIGGER = "TRIGGER_START"


class ThinkingFilter:
    """Streaming filter that drops leaked thinking before TRIGGER_START.

    Models like Gemma 4 E4B with reasoning_effort=none dump internal planning
    into the content stream before the actual response. The system prompt
    instructs the model to begin every response with TRIGGER_START. This
    filter buffers tokens until it sees the trigger, then streams everything
    after it in real time so downstream consumers (sentence buffer → TTS)
    can start playing immediately.

    Typical model output:
        "Нейронная сеть — это модель. (thoughtful)\nTRIGGER_START Ответ..."
                        ^^^ leaked thinking ^^^       ^^^ actual response ^^^
    """

    def __init__(self, enabled: bool = True, trigger: str = RESPONSE_TRIGGER):
        self.enabled = enabled
        self.trigger = trigger
        self._pre_buffer = ""   # raw stream until trigger seen
        self._triggered = False  # True once trigger encountered

    def process(self, token: str) -> Optional[str]:
        """Return text to stream now, or None to keep buffering.

        Once TRIGGER_START has been seen, every subsequent token is forwarded
        as-is. Before that, tokens accumulate in pre_buffer and the trigger
        boundary is searched; on hit, content after the trigger is emitted.
        """
        if not self.enabled:
            return token
        if self._triggered:
            return token
        self._pre_buffer += token
        if self.trigger not in self._pre_buffer:
            return None
        # Trigger boundary found — split, drop everything before, emit after.
        after = self._pre_buffer.split(self.trigger, 1)[1].lstrip("\n")
        self._pre_buffer = ""
        self._triggered = True
        return after if after else None

    def flush(self) -> Optional[str]:
        """Drain residual buffer at stream end.

        After triggered: nothing left, returns None.
        Filter disabled: pass through whatever was buffered.
        Filter enabled but TRIGGER_START never emitted: return None (do NOT
        leak the model's internal planning to TTS). Caller's retry path will
        ask again. Earlier behavior was to pass thinking through as a "best
        effort" fallback, which routed reasoning content straight to the
        student. The hardened personality prompt mandates TRIGGER_START on
        every turn, so absence of the marker is a stream we should drop.
        """
        if self._triggered:
            return None
        if not self.enabled:
            return self._pre_buffer or None
        if self._pre_buffer:
            preview = self._pre_buffer[:120].replace("\n", " ")
            print(f"[ThinkingFilter] No TRIGGER_START in stream — dropping {len(self._pre_buffer)} chars (preview: '{preview}')")
        return None


class LMStudioClient:
    """Synchronous LM Studio client with background heartbeat.

    Uses requests library for HTTP (matching the sync threading model of Professor).
    Heartbeat runs in a daemon thread to keep KV cache warm.
    """

    def __init__(
        self,
        base_url: str = None,
        model: str = "loaded-model",
        heartbeat_interval: float = 2.0,
        max_tokens: int = 512,
        temperature: float = 0.7,
        reasoning_effort: str = "none",
        filter_thinking: bool = True,
    ):
        if base_url is None:
            base_url = os.getenv("LM_STUDIO_API_BASE", "http://127.0.0.1:1234/v1")
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.heartbeat_interval = heartbeat_interval
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.reasoning_effort = reasoning_effort  # "none" disables thinking in Gemma 4
        self.filter_thinking = filter_thinking    # filter leaked thinking from content

        self._session: Optional[requests.Session] = None
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._heartbeat_running: bool = False
        self._last_request_time: float = 0
        self._last_messages: Optional[List[Dict]] = None  # for keepalive ping

    def start(self):
        """Start the client and heartbeat thread."""
        self._session = requests.Session()
        self._heartbeat_running = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True
        )
        self._heartbeat_thread.start()
        print(f"[LM Studio] Client started: {self.base_url}, "
              f"heartbeat every {self.heartbeat_interval}s")

    def stop(self):
        """Stop heartbeat and close session."""
        self._heartbeat_running = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=5)
            self._heartbeat_thread = None
        if self._session:
            self._session.close()
            self._session = None
        print("[LM Studio] Client stopped")

    def _heartbeat_loop(self):
        """Send minimal keepalive pings to prevent KV cache eviction.

        Uses the SAME prefix as the last real request (maximizes cache hit).
        Sends max_tokens=1 and fully reads the response (required for cache save).
        """
        while self._heartbeat_running:
            time.sleep(self.heartbeat_interval)
            if not self._heartbeat_running:
                break

            elapsed = time.time() - self._last_request_time
            if elapsed < self.heartbeat_interval:
                continue  # recent real request, no ping needed

            # Build ping: use last known messages prefix, or minimal fallback
            if self._last_messages and len(self._last_messages) > 1:
                # Use cached prefix (all messages except the last dynamic one)
                ping_messages = self._last_messages
            else:
                ping_messages = [{"role": "user", "content": "ping"}]

            try:
                resp = self._session.post(
                    f"{self.base_url}/chat/completions",
                    json={
                        "model": self.model,
                        "messages": ping_messages,
                        "max_tokens": 1,
                        "temperature": 0,
                        "stream": True,
                    },
                    timeout=5,
                    stream=True,
                )
                # MUST fully drain stream for cache to be saved
                for line in resp.iter_lines():
                    pass
                resp.close()
            except Exception:
                pass  # heartbeat failure is not critical

    def stream_chat(
        self,
        messages: List[Dict],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        on_token: Optional[Callable[[str], None]] = None,
        stop: Optional[List[str]] = None,
    ) -> Generator[str, None, None]:
        """Stream chat completion via SSE.

        Yields tokens as they arrive. Fully drains the stream on completion
        (required for LM Studio KV cache to be saved).

        Args:
            messages: OpenAI-format messages list
            max_tokens: Override default max_tokens
            temperature: Override default temperature
            on_token: Optional callback for each token
        """
        if self._session is None:
            raise RuntimeError("Client not started. Call start() first.")

        # Pause heartbeat during real request to avoid slot conflict
        self.pause_heartbeat()
        self._last_request_time = time.time()
        self._last_messages = messages  # save for keepalive

        payload = {
            "model": self.model,
            "messages": messages,
            "max_tokens": max_tokens or self.max_tokens,
            "temperature": temperature if temperature is not None else self.temperature,
            "stream": True,
        }
        # Disable thinking for models that support it (e.g. Gemma 4 E4B)
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if stop:
            payload["stop"] = stop

        try:
            resp = self._session.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                stream=True,
                timeout=30,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[LM Studio] Connection error: {e}")
            return

        thinking_filter = ThinkingFilter(enabled=self.filter_thinking)

        try:
            resp.encoding = "utf-8"
            for line in resp.iter_lines(decode_unicode=True):
                if not line:
                    continue
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                    delta = chunk["choices"][0]["delta"]
                    # Skip reasoning_content (thinking tokens)
                    if "content" in delta and delta["content"]:
                        token = delta["content"]
                        if self.filter_thinking:
                            # Streaming filter: returns None until TRIGGER_START
                            # is seen, then forwards subsequent tokens in real time.
                            out = thinking_filter.process(token)
                            if out:
                                if on_token:
                                    on_token(out)
                                yield out
                        else:
                            if on_token:
                                on_token(token)
                            yield token
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue

            # Flush: when filter is active, this extracts the clean response
            # after the last TRIGGER_START. Yielded as one block.
            remaining = thinking_filter.flush()
            if remaining:
                if on_token:
                    on_token(remaining)
                yield remaining
        finally:
            # CRITICAL: fully drain remaining stream for KV cache save
            try:
                for _ in resp.iter_lines():
                    pass
            except Exception:
                pass
            resp.close()
            # Resume heartbeat after stream completes
            self.resume_heartbeat()

    def stream_chat_to_queue(
        self,
        messages: List[Dict],
        q: queue.Queue,
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stop: Optional[List[str]] = None,
    ):
        """Stream chat to a queue (for threading compatibility with existing code).

        Puts tokens into queue, None signals end of stream.
        This method runs in the caller's thread.
        """
        try:
            token_count = 0
            for token in self.stream_chat(messages, max_tokens, temperature, stop=stop):
                q.put(token)
                token_count += 1
            if token_count == 0:
                print("[LM Studio] WARNING: 0 tokens received")
        except Exception as e:
            print(f"[LM Studio] Stream error: {e}")
        finally:
            q.put(None)  # signal end

    def check_health(self) -> Dict:
        """Check that LM Studio is running and a model is loaded."""
        if self._session is None:
            self._session = requests.Session()
        try:
            resp = self._session.get(
                f"{self.base_url}/models",
                timeout=3,
            )
            data = resp.json()
            models = data.get("data", [])
            return {
                "status": "ok" if models else "no_model",
                "models": [m["id"] for m in models],
            }
        except Exception as e:
            return {"status": "error", "error": str(e)}

    def pause_heartbeat(self):
        """Temporarily pause heartbeat (before real request to avoid slot conflict)."""
        self._heartbeat_running = False

    def resume_heartbeat(self):
        """Resume heartbeat after real request completes."""
        if self._heartbeat_thread and not self._heartbeat_thread.is_alive():
            self._heartbeat_running = True
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True
            )
            self._heartbeat_thread.start()
        elif not self._heartbeat_thread:
            self._heartbeat_running = True
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True
            )
            self._heartbeat_thread.start()
        else:
            self._heartbeat_running = True

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# Module-level singleton for easy access
_client: Optional[LMStudioClient] = None


def get_lm_studio_client() -> LMStudioClient:
    """Get or create the global LMStudioClient singleton."""
    global _client
    if _client is None:
        _client = LMStudioClient(
            base_url=os.getenv("LM_STUDIO_API_BASE", "http://127.0.0.1:1234/v1"),
            model=os.getenv("LM_STUDIO_MODEL_NAME", "loaded-model"),
            heartbeat_interval=float(os.getenv("LM_STUDIO_HEARTBEAT_INTERVAL", "2.0")),
            reasoning_effort=os.getenv("LM_STUDIO_REASONING_EFFORT", "none"),
            filter_thinking=os.getenv("LM_STUDIO_FILTER_THINKING", "true").lower() in ("true", "1", "yes"),
        )
        _client.start()
    return _client


def shutdown_lm_studio_client():
    """Shutdown the global client (call on app exit)."""
    global _client
    if _client is not None:
        _client.stop()
        _client = None
