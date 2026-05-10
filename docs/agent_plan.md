# Current realization

## Summary structure

### Related files
- src/agent/ 
  - suprevisor_agent.py - Main agent implementation using AutoGPT
  - autogpt/ - Core AutoGPT implementation
    - agent.py - Main agent loop and execution logic
    - prompt.py - Custom prompt management
    - prompt_generator.py - Custom prompt generation with state tracking
    - output_parser.py - JSON output parsing
  - tools/tools.py - Tool definitions (voice, chat, minecraft controls)
  - rag.py - RAG system for knowledge retrieval
  - monologue_agent.py - Voice speaking handling

The current agent uses an AutoGPT-style architecture with:
- Custom prompt template system for contextual awareness
- Tool-based action execution
- RAG for knowledge retrieval
- State management system for tracking thoughts and game state
- Event-based triggering system

## Pros

1. Strong foundation with proven architectures (AutoGPT + LangGraph experiments)
2. Good state tracking with detailed thought structure
3. Sophisticated tool management system
4. Event-driven architecture with triggers
5. Integrated RAG for knowledge lookup
6. Comprehensive error handling with graduated consequences
7. Multiple feedback loops for behavior correction

## Cons

1. Very high token usage (~7k) making responses slow and expensive
2. Tool overload - too many tools available at once makes decisions complex
3. Lacks clear separation of concerns between different agent roles
4. State transitions not clearly defined
5. No clear tool priority/selection strategy
6. Context window gets cluttered with irrelevant information
7. Error recovery is destructive rather than graceful
8. Lacks systematic approach to different game modes/situations

# Why is bad working: my thoughts

(do not remove this section)

1. 7k tokens on input. It's incredible bad!
2. Too much tools to 1 agent

How can improve i think with SIMPLIEST approach:

The core issue is cognitive overload - trying to do too much at once. We need to split responsibilities while maintaining coordination:

1. Tool Rotation System
- Group tools by function (chat, game control, voice, admin)
- Create triggers for each tool group:
  - Chat tools: on new chat messages
  - Game tools: on game state changes
  - Voice tools: after processing events or on timeout
  - Admin tools: on rule violations
- Implement tool group activation based on:
  - Current state (e.g., in minigame vs lobby)
  - Recent events (deaths, kills, chat activity)
  - Time since last use
  - Priority system (admin > game > chat > voice)

2. State Management Enhancement  
- Split state into domains:
  - Game state (position, health, mode)
  - Social state (chat activity, player relationships)
  - Internal state (goals, thoughts, plans)
  - Response state (queued actions)
- Implement state transition validation
- Add state conflict resolution
- Track state dependencies

3. Context Window Optimization
- Implement relevance filtering for chat history
- Add dynamic context pruning
- Cache frequently used knowledge
- Structure prompt by priority sections

4. Graceful Error Recovery
- Add state checkpoints before risky actions
- Implement partial state recovery
- Add cool-down periods after errors
- Track error patterns for prevention

This creates a more focused agent that:
- Only loads relevant tools for current situation
- Maintains cleaner context
- Recovers gracefully from errors 
- Has clearer decision boundaries
- Uses tokens more efficiently

The key is progressive enhancement - start with basic tool rotation, then add features as needed.

How can improve i think with SIMPLIEST approach:

- Split the agentic tools and make a tools rotation but all the same

Here i mean we can give agent different tools packets based on: triggers (if game - game tools), timeouts (we should for example run speak tool not too rare, if there's always game events).

Approach harder:

- Make the tool groups, add tool group choose tool. So, agent first thinking strategy and choose the tools groups. Then agent use this tools pack provided by the above strategy. Then again.

The most hard approach: multiagent

We have strategy agent, minecraft agent, speak agent, dialog agent. They all have their own tool packs. They need to synchronize between each other. They can use trigger system - chooses last relevant agent + timeout if some agent longly doesn't run.

TODO list for pipeline to implement:
- I DONT KNOW HOW TO IMPLEMENT: agent world static information (may be RAG? but idk this cant be relevant..):
  -  minecraft information (about regions, /rg claim, modes like survival, skywars, murdermystery)
  -  personality detailed information (who has created, what food you like, etc.)
- DATABASE players summary integration and dialog history integration
  - i think this approach can be made via dialogue agent, when AI is entering dialog mode with player, after a dialog if he is not in DB it saves a new summary state. And re-saves everytime after dialog if state is changed.
  - This info can be added with current RAG, concatenated to prompt where we have explanations. We can describe every player in chat (limited by 3 maybe).
  - DB summary should have necessary fields: trust level (digit), -5 -> +5, where 6 is unavailable to set automatically, but it can be set for DEVs since its full-trust level.