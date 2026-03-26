model: > gemma3 12B / InternVL3 / Qwen 2.5 VL

## Cycle

1. Action request

Input: Prompt for new action choose & Display screenshot

Output: Action request (tool use)

2. Action revision

Input:
- Prompt for future action assesement and result prediction
- Display screenshot
  - with VISUALISATION of what agent will do
    - e.g. BRIGHT RED DOT with circle around it in place on screen agent requested to click

Output: Action approval or refining actions

## Prompt

- base role
- output format description
- tools description and tools info (with examples (few shots)) or not)

Available actions: (F = future)
- Mouse hover
  - new position
  - (F) speed
- Click
  - on position
  - (F) hold / instant click
- Scroll
  - up / down
  - amount to scroll
- Keyboard input
  - Text input
  - Key press