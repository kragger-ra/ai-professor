# Prompt Caching — How It Works

## Result

TTFT improved **6x**: from 6-7s down to ~1.1s per response.

| Stage | TTFT | What changed |
|---|---|---|
| Before any optimization | 6-7s | Full prompt rebuilt every call |
| Tool statuses removed from tail | 3-3.5s | Tail shrank by ~800 tokens |
| Append-only prefix + keepalive | 1.0-1.2s | KV cache hit on prefix |
| Theoretical max (isolated test) | 0.19s | Same prompt, no new events |

## How it works

### LM Studio KV Cache

LM Studio (llama.cpp) caches computed key-value pairs by **token prefix matching**.
If request B starts with the same tokens as request A, those tokens are not reprocessed.

**Critical requirement**: the stream must be **fully read** (all chunks consumed).
If you break early, LM Studio does not save the cache.

### Cache eviction

LM Studio evicts KV cache for tool-augmented requests after **~3-5 seconds of inactivity**.
Without tools: cache survives 30+ seconds. With `bind_tools`: ~3-5s only.

### Keepalive solution

A background daemon thread sends a ping every 3 seconds during idle wait:
```
ping = cached_prefix + [HumanMessage(last_tail)]
max_tokens = 1, fully drained
```

This keeps the KV cache warm. When a real request arrives, the prefix is already cached.

### Why 1.1s and not 0.2s

Between pings and real requests, new events arrive. The prefix grows
(new AI responses, tool results). The keepalive's tail doesn't match the
real tail exactly (situation context changes — player positions, etc.).

Cache hits on **system prompt + conversation history** (~1100 tokens).
Misses on **new messages + tail** (~500 tokens). 500 tok at ~1000 tok/s = 0.5s + overhead.

## Architecture

```
_cached_prefix (append-only, never rebuilt):
  [0] SystemMessage — personality + output rules (stable)
  [1] HumanMessage  — first events batch
  [2] AIMessage     — LLM response + tool_calls
  [3] ToolMessage   — tool result
  [4] HumanMessage  — next events
  ...grows over time...

Prompt sent to LLM:
  _cached_prefix + [HumanMessage(tail)]
                    ↑ only this changes

Keepalive ping (every 3s):
  _cached_prefix + [HumanMessage(last_known_tail)]
```

## What NOT to do (will break caching)

1. **Don't rebuild prefix** — objects in `_cached_prefix` must never be replaced.
   Use `_append_to_prefix()` to add, never reassign list items.

2. **Don't post-process messages** — no `_ensure_alternation`, no creating new
   message objects from existing ones. The same Python object = same serialization.

3. **Don't put dynamic data in system prompt** — tool statuses, mood, timestamps.
   All dynamic data goes in tail (last HumanMessage).

4. **Don't break stream early without draining** — always read all chunks.
   The `finally` block in `_stream_response` handles this.

5. **Don't insert messages in the middle** — only append to end.
   Trim removes from the beginning (after SystemMessage).

## Configuration

```env
# .env
OVERRIDE_PROMPT_CACHING_PING=auto
# auto (default): enable for lm_studio model, disable for cloud APIs
# true: always enable (useful for local llama.cpp)
# false: always disable (for cloud APIs where pings cost money)
```

## Files

- `src/agent/multi/chat_agent.py` — `_cached_prefix`, `_keepalive_loop`, `_append_to_prefix`
- `src/agent/prompt_generation/message_builder.py` — `events_to_messages()` (converts events to BaseMessages)
- `docs/issues/PROMPT_CACHING_ISSUE.md` — full investigation log
- `docs/eval/prompt_cache_ttft.md` — benchmark results
- `tests/test_prompt_cache.py` — cache benchmark tool
