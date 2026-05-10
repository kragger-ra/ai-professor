# Browser Agent Goals

## Project Objectives

The Browser Agent project aims to create an autonomous agent capable of controlling a web browser through visual understanding and action execution.

### Core Goals:

1. **Visual Understanding**: Capture and analyze screenshots to understand current browser state
2. **Action Planning**: Use LLM to plan appropriate browser actions based on user requests
3. **Action Visualization**: Show users what the agent will do before execution (e.g., red dot for click targets)
4. **Action Execution**: Execute planned actions using mouse, keyboard, and scroll controls
5. **Feedback Loop**: Implement a two-stage cycle for action request and revision

### Technical Implementation:

- **Model**: Use Gemma3 12B / InternVL3 / Qwen 2.5 VL for visual language understanding
- **Architecture**: Two-stage cycle (Action Request → Action Revision → Execution)
- **Tools**: Mouse hover, click, scroll, keyboard input with future extensions
- **Pipeline**: Maximum use of existing pipeline methods and libraries

### Success Metrics:

- Accurate screenshot analysis and action planning
- Reliable action execution with visual feedback
- Smooth integration with existing NetTyan agent framework
- Minimal code complexity while maintaining functionality
