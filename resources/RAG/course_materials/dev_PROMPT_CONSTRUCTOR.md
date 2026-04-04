# Prompt Construction — Architecture Overview

## Two Systems

The project has two prompt construction paths:

### 1. Legacy: `prompt_constructor.py` + `format_helper.py`
Used by: **CoreAgent**, **ReactionAgent**, **PlannerAgent**

```
prompt_constructor.construct_prompt_messages()
  -> format_events_with_roles()          # format_helper.py
    -> preprocess_events()
      -> merge_tool_calls()              # merge consecutive tool calls
      -> merge_user_events()             # merge consecutive same-user messages
      -> filter_spam_events()            # remove spam, limit system msgs
    -> categorize_events()               # split into recent/relevant/old
    -> for each event:
      -> format_single_event()           # "MINECRAFT CHAT [2m ago] User: msg"
      -> assign role: user or assistant  # based on event type
    -> add dividers between categories   # as separate user messages (!)
  -> construct_prompt()                  # system prompt with tools, game status, users
  -> add events as conversation turns
  -> add goal/suggestion message
  -> optionally add assistant prefill (unfinished_response)
```

**Problems:**
- Each event = separate message = broken alternation
- Dividers as user messages
- Assistant prefill incompatible with many modern APIs
- Tool format descriptions baked into prompt text

### 2. Modern: `message_builder.py`
Used by: **ChatAgent**

```
message_builder.build_chat_messages()
  -> build_events_block()
    -> preprocess_events()               # reuses format_helper preprocessing
    -> categorize_events()               # reuses format_helper categorization
    -> format_single_event()             # reuses format_helper event formatting
    -> consolidate into TWO text blocks: user_events + assistant_events
  -> Assemble messages:
    system: character prompt + tool hints
    user: situation + ALL events as text + reminder
    assistant: last response (optional, for context)
    user: reminder (if after assistant turn)
  -> ensure_alternation()                # merge any remaining consecutive same-role msgs
```

**Improvements:**
- All events in one user message block
- Strict alternation guaranteed
- No assistant prefill hack
- Tools defined via native API (bind_tools), not text descriptions

## Shared Components

Both systems reuse from `format_helper.py`:
- `preprocess_events()` — merging and filtering
- `categorize_events()` — time-based categorization
- `format_single_event()` — single event to string

## Response Parser

**File:** `agent/parsing/response_parser.py` (moved from `agent/tools/tool_executor.py`)

Text-based tool parsing for legacy agents (CoreAgent). Parses commands like:
- `!command arg1 arg2` — general tools
- `/minecraft_cmd args` — minecraft commands
- `@agent_action args` — baritone actions
- `>text *emotion*` — speak tool

**Not used by ChatAgent** — it uses native `tool_calls` from the LLM API.
