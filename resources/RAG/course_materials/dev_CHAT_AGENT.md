# ChatAgent — Modern Agent with Native Function Calling

**File:** `src/agent/multi/chat_agent.py`
**Message builder:** `src/agent/prompt_generation/message_builder.py`

## Overview

Modern replacement for ReactionAgent that works correctly with Claude, GPT-4o, Gemini,
and other current LLMs. Uses LiteLLM's native function calling (`bind_tools`) instead
of text-based tool command parsing.

## How to Run

```bash
python main.py -c          # ChatAgent mode (native tool calling)
python main.py -m          # MultiAgent mode (legacy ReactionAgent)
python main.py             # CoreAgent mode (legacy text-based tools)
```

## Architecture

```
ChatAgent.step()
  -> wait_for_sync(timeout=15s)
  -> ChatAgent.respond(trigger_event)
    -> build_chat_messages()        # message_builder.py — clean alternation
    -> llm_with_tools.stream()      # native function calling via bind_tools
    -> if tool_calls in response:
        -> execute each tool call
        -> append ToolMessage results
        -> call LLM again (tool loop)
    -> until: text-only response or MAX_TOOL_ROUNDS
```

## Prompt Trace

```
ChatAgent.respond(trigger_event)
  1. Get events from ctx_handler
  2. build_events_block() -> consolidates ALL events into single text blocks
  3. _build_system_prompt() -> character_prompt + emotion hints
  4. _build_situation_context() -> game status + users info
  5. build_chat_messages() -> clean message list with alternation
  6. Convert to langchain messages
  7. Stream with llm_with_tools (tools bound via bind_tools)
```

## Message Structure (what LLM sees)

```
messages = [
  {role: "system", content: "
    {character_prompt}

    When using the speak tool, set emotion to one of: neutral, happy, sad, angry, ...
  "}
  {role: "user", content: "
    # Current Situation:
    ## Game Status:
    ...
    ## Nearby Users & Players:
    ...

    --- Old context (>1 min ago) ---
    MINECRAFT CHAT [2m ago] User1: hello
    MINECRAFT CHAT [1.5m ago] User2: yo

    --- Happening now ---
    MINECRAFT CHAT [2s ago] User1: cool

    Respond to the latest events. Be BRIEF and in-character.
    Use the speak tool to say something (with emotion).
  "}
  {role: "assistant", content: "privet *happy*"}   # previous response, if any
  {role: "user", content: "Respond to the latest events..."}  # reminder after assistant
]
```

Key differences from ReactionAgent:
- **All events in ONE user message** — no alternation problems
- **Dividers are text sections** — not separate messages
- **Tools via native API** — LLM returns structured `tool_calls`, not text to parse
- **Tool loop** — LLM can call multiple tools, see results, and respond

## Tool Calling Flow

```
LLM Response: {content: "", tool_calls: [{name: "speak", args: {comment: "Hello!", emotion: "happy"}}]}
  -> execute speak("Hello!", emotion="happy")
  -> result: True
  -> ToolMessage(content="True", tool_call_id=...)
  -> LLM Response: {content: "Done speaking", tool_calls: []}
  -> Final text response (or empty if tool did the job)
```

## Available Tools

All enabled tools from `tool_bank` are automatically bound via `_rebind_tools()`.
Each tool's langchain `StructuredTool` (from `register_tool()`) provides:
- Name and description (from function docstring)
- Args schema (auto-generated from type hints)

The LLM sees these as native function definitions, not text descriptions.

## Key Files

| File | Purpose |
|------|---------|
| `agent/multi/chat_agent.py` | Main agent logic |
| `agent/prompt_generation/message_builder.py` | Clean message formatting |
| `agent/multiagent.py` | Orchestrator (use_chat_agent flag) |
| `main.py` | Entry point (-c flag) |
