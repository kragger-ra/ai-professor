# Agent Architecture

## Agent Types

| Agent | File | Tool Format | Status |
|-------|------|-------------|--------|
| **ChatAgent** | `agent/multi/chat_agent.py` | Native function calling (bind_tools) | **NEW, recommended** |
| CoreAgent | `agent/core_agent.py` | Text-based (`!cmd`, `/cmd`, `@cmd`, `>speak`) | Legacy, works |
| ReactionAgent | `agent/multi/reaction_agent.py` | No tools (raw text -> speak) | Legacy, works |
| PlannerAgent | `agent/multi/planner_agent.py` | No tools (text analysis) | Works, output unused |

## Entry Points (main.py flags)

```
python main.py -c    # MultiAgent + ChatAgent (native tools) — NEW
python main.py -m    # MultiAgent + ReactionAgent (legacy)
python main.py -l    # ReactionAgent standalone (legacy)
python main.py       # CoreAgent standalone (legacy)
```

## MultiAgent Orchestration

```
MultiAgent.run() loop:
  for i in range(3):        # 3 chat iterations
    chat_agent.step()        # or reaction_agent.step() if legacy
  planner_agent.step()       # strategic planning (currently output not used)
  # core_agent.step()        # disabled
```

## Module Layout

```
src/agent/
  parsing/
    response_parser.py     # Text-based tool parsing (moved from tools/tool_executor.py)
  prompt_generation/
    message_builder.py     # Modern message formatting for ChatAgent
    prompt_constructor.py  # Legacy prompt construction for CoreAgent/ReactionAgent
  multi/
    chat_agent.py          # NEW: native function calling agent
    reaction_agent.py      # Legacy: no-tool chat agent
    planner_agent.py       # Strategic planner
  tools/
    tool_executor.py       # Re-export shim -> agent/parsing/response_parser.py
    tools.py               # Tool registration, get_tool_records()
    tools_config.py        # Global tool_bank, llm_model
    base_tools.py          # speak, wait, save_user_info, etc.
    status_tools.py        # register_tool(), get_tool_status()
    ...                    # minecraft_tools, state_tools, etc.
  core_agent.py            # Legacy full agent with text tool parsing
  multiagent.py            # Orchestrator
  base_agent.py            # Abstract base
```
