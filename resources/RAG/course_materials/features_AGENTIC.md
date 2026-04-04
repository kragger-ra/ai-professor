# Agentic Architecture — Multi-Agent Routing with Prompt Caching

## Problem

1. Universal agent with all tools doesn't understand when to use game commands
2. No way to have deep personal conversations (always brief responses)
3. Prompt processing is slow — conversation history rebuilt from scratch every call
4. Same text goes to TTS and chat — short answers boring for voice, long answers spam chat

## Key insight (from benchmark)

See `docs/eval/prompt_cache_ttft.md`. KV cache = prefix-based:

- Identical prefix: **0.4s** (15x speedup)
- Append at end: **0.85s** (prefix cached)
- Change at start: **3.8s** (full recompute)

**Rule**: everything STABLE goes first, everything DYNAMIC goes last.

## Two-channel output: Voice vs Chat

Core architectural decision: **LLM text output = voice, chat = separate tool**.

| Channel | What | How | Length |
|---|---|---|---|
| Voice (TTS) | LLM's text output, spoken aloud | Automatic from text | Any length, LLM decides |
| Game chat | Minecraft chat, players read | `chat_simple` tool call | Short, <80 chars, optional |

The LLM decides independently what to say (voice) and what to write (chat):

- Simple reaction: short voice + short chat (or no chat)
- Interesting question: long detailed voice + brief chat summary
- Game action: brief tactical voice + tool calls (agent_action, etc.)
- Just listening: no voice, no chat (silent observation)

This solves the "boring short answers" problem — voice can be engaging and detailed,
while chat stays clean and readable.

### Streaming TTS (future)

When voice responses get longer, split text into sentences and feed TTS incrementally:
1. First sentence → TTS immediately (user hears response fast)
2. While sentence 1 is being spoken, generate TTS for sentence 2
3. Seamless playback with no gap

Implementation: split text in `_send_as_speech`, push sentences to `tts_queue` one by one.

## Prompt structure (cache-optimized)

```
CACHED PREFIX (grows over time, append-only)
  system: character identity + personality             ~800 tok (stable)
  tools:  ALL tools bound (never changes)              ~1500 tok (stable)

  conversation history (append-only):
  user: events batch 1                                 cached after call 1
  assistant: response 1                                cached after call 2
  user: events batch 2                                 cached after call 2
  assistant: response 2                                cached after call 3
  ...grows with each interaction...
  user: NEW events batch                               NEW (~100-500 tok)

DYNAMIC TAIL (always recomputed, cheap)
  user: game situation, players, mood, tool statuses   ~500-700 tok
  user: agent mode instruction                         ~100-300 tok
```

Each new event **appends** to the cached prefix. Only the tail is recomputed.

When history exceeds ~25k tokens: trim oldest messages, one-time re-cache.

## Agents

### DEFAULT agent (general + game merged)

The main agent. Handles chat, game actions, personal conversation — everything.

```
## Output format
You have TWO output channels:
- TEXT = your VOICE (spoken aloud via TTS). This is your main output.
- chat_simple tool = minecraft CHAT (players read this). Short, optional.

Text output rules:
- End with single *emotion* tag.
- Simple reaction → 1-2 sentences.
- Interesting question or topic → speak freely, be detailed.
- You decide the length based on how interesting the situation is.

Chat rules:
- Use chat_simple tool to write in game chat. Keep SHORT (<80 chars).
- You can speak long and write short, or speak without writing.
- Players ONLY see chat_simple messages, not your voice text.

You have game tools — use tool calls for actions.
Never write @commands or /commands as text.
```

Why general + game merged:

- One agent, one prompt, no routing overhead
- Better tool descriptions solve the "тупит" problem
- Agent sees game situation AND chat — can respond to attack with both voice AND action

### DIALOGUE mode (future — personal 1-on-1)

Activated when personal conversation detected. Richer context, detailed responses.
Changes only the instruction tail — prefix stays cached.

Extra context injected:

- Full user profile from DB (summary, rank, nicknames, last seen)
- Dedicated dialogue history with this specific user

Routing: Python heuristics for obvious cases (active dialogue tracking),
LLM self-routing via `start_dialogue(user)` / `end_dialogue()` tools for judgment calls.

## Tool strategy

ALL tools bound ALWAYS. Keeps tool definitions in cached prefix.

| Tool | Purpose | Notes |
|---|---|---|
| chat_simple | Write to minecraft chat | NEW: separate from voice |
| agent_action | Game movement/combat/gestures | @follow, @strike, @gesture |
| minecraft_command | Server commands | /tpa, /tell, /spawn |
| focus | Set attention topic | |
| like/dislike | Rate users | |
| save_user_info | Remember facts about users | |
| plan | Set behavior plan | |
| pattern | Set behavior pattern | |
| analyze_nickname | Analyze user nicknames | |
| vote tools | Voting system | |
| fx | Sound effects | |

speak/speak_list excluded from tool binding — voice handled directly from LLM text output.

## Implementation status

### Phase 1: Universal agent (IN PROGRESS)

- [x] Improve tool descriptions for agent_action and minecraft_command
- [x] Inject tool statuses into situation context
- [x] Fix emotion parsing (`**emotion**`, multiple emotions)
- [x] Separate voice (TTS) from chat (chat_simple tool)
- [x] Rewrite system prompt: two-channel output, variable response length
- [ ] Test game actions + chat_simple in practice

### Phase 2: Append-only conversation history with NATIVE tool calls

**CRITICAL**: conversation history MUST use native langchain message types, not text approximations.

Current problem: tool calls shown as text `[sent to game chat]: msg` in AIMessage.content.
LLM sees this as text, not as its own tool usage. Result: LLM doesn't learn to use tools,
may start writing `[sent to game chat]` literally, or ignores tools entirely.

Required format (native langchain):
```
AIMessage(content="Привет! *happy*", tool_calls=[
    {"name": "chat", "id": "call_1", "args": {"message": "Привет!"}}
])
ToolMessage(content="True", tool_call_id="call_1")
AIMessage(content="", tool_calls=[
    {"name": "agent_action", "id": "call_2", "args": {"action": "follow Chochok"}}
])
ToolMessage(content="Action sent", tool_call_id="call_2")
```

This is how the LLM natively understands tool usage — it's the format it was trained on.

Implementation:

- [ ] Store tool_call_id in ctx_chat events when tools are executed
- [ ] message_builder returns langchain message objects (not dicts)
- [ ] Own tool calls → AIMessage with tool_calls field + ToolMessage for results
- [ ] Own speak → AIMessage with text content (voice output)
- [ ] External events → HumanMessage batches
- [ ] Append-only: new messages extend cached prefix
- [ ] Situation + instruction always at the end (tail)
- [ ] History overflow trimming at 25k context
- [ ] _to_langchain_messages becomes unnecessary (builder returns native types)

### Phase 3: DIALOGUE mode

- [ ] Add DialogueTracker (tracks active dialogues per user)
- [ ] Add start_dialogue / end_dialogue tools
- [ ] Inject user data from DB into dialogue prompt
- [ ] Mode-specific tail instructions

### Phase 4: Streaming TTS

- [ ] Split long voice text into sentences
- [ ] Push to tts_queue incrementally
- [ ] Measure latency improvement

### Idea: Synthetic tool calls for world state (cache-friendly)

Instead of injecting player positions, game status etc. as a text block in the user message
(which changes every call and breaks cache), embed them as **fake tool call/result pairs**
in the conversation history:

```
assistant: [tool_call: check_players()]
tool: {result: "Chochok (5m, aggressive, diamond sword), Worshiper (10m, looking at you)"}
assistant: [tool_call: game_status()]
tool: {result: "Survival, no tasks, MysteryWorld server"}
```

Benefits:
- LLM naturally understands "I asked for status and got this" — better reasoning
- Tool call format is native to the model (trained on it)
- Results can be placed at the point in history where they're relevant
  (not always at the end — e.g. player positions from 30s ago stay in history)
- If world state hasn't changed, the cached tool call/result pair is identical → cache hit

This pattern works for any periodic data: game state, player list, inventory, mood updates.
Can be combined with append-only history — inject status "polls" at natural breakpoints.
