# Browser Agent

An autonomous browser automation agent that uses computer vision and LLM reasoning to control web browsers through screenshots and actions.

## Features

- **Visual Understanding**: Captures and analyzes screenshots to understand browser state
- **Action Planning**: Uses LLM to plan appropriate browser actions based on user requests
- **Action Visualization**: Shows users what the agent will do before execution (red dot overlays)
- **Action Execution**: Executes planned actions using mouse, keyboard, and scroll controls
- **Two-Stage Cycle**: Action Request → Action Revision → Execution for safety and accuracy

## Architecture

The browser agent follows a two-stage cycle as described in `BROWSER-AGENT-PROJECT.md`:

1. **Action Request**: Take screenshot, analyze with LLM, plan action
2. **Action Revision**: Visualize planned action, get LLM approval/refinement
3. **Execution**: Execute approved action using browser tools

## Installation

### Prerequisites

```bash
pip install pyautogui pillow mss
```

### Setup

The browser agent integrates with the existing NetTyan agent framework:

```python
from src.agent.browser.browser_agent import BrowserAgent

# Create agent instance
agent = BrowserAgent()

# Run a task
result = agent.run_cycle("Click on the login button")
```

## Usage

### Basic Usage

```python
from src.agent.browser.browser_agent import BrowserAgent

# Initialize agent
agent = BrowserAgent()

# Simple task
result = agent.run_cycle("Click on the search button")

if result["success"]:
    print("Task completed successfully!")
    print(f"Result: {result['final_result']}")
else:
    print("Task failed")
```

### Advanced Usage

```python
# Custom configuration
agent = BrowserAgent(ctx={
    "screen_resolution": (1920, 1080),
    "visualization_color": "blue"
})

# Manual cycle control
action_req = agent.action_request("Navigate to settings")
revision = agent.action_revision(action_req)

if revision.get("approved"):
    result = agent.execute_action(action_req)
    print(f"Action executed: {result}")
```

### Interactive Demo

```bash
# Run the demo script
python demo_browser_agent.py

# Interactive mode
python demo_browser_agent.py interactive

# Help
python demo_browser_agent.py help
```

## Available Actions

The agent supports the following browser actions:

### Mouse Actions
- `mouse_hover(position)` - Move mouse to coordinates
- `click(position)` - Click at coordinates
- `release_mouse()` - Release held mouse buttons

### Keyboard Actions
- `keyboard_input(text=None, key=None)` - Type text or press key

### Scroll Actions
- `scroll(direction, amount)` - Scroll up/down by amount

## Configuration

### Environment Variables

- `BROWSER_AGENT_MOCK_ACTIONS=true` - Enable mock mode for testing
- `BROWSER_AGENT_DEBUG=true` - Enable debug logging
- `BROWSER_AGENT_SCREENSHOT_RESIZE=1280,720` - Screenshot resize dimensions
- `BROWSER_AGENT_MAX_RETRIES=3` - Maximum retry attempts
- `BROWSER_AGENT_VIZ_COLOR=red` - Visualization color
- `BROWSER_AGENT_SAVE_SCREENSHOTS=true` - Save screenshots for debugging

### Configuration File

```python
from src.agent.browser.browser_config import get_browser_agent_config

config = get_browser_agent_config()
agent = BrowserAgent(ctx=config)
```

## Testing

### Run Tests

```bash
# Run all tests
python -m pytest tests/test_browser_agent.py -v

# Run specific test
python tests/test_browser_agent.py
```

### Mock Mode

For testing without actual browser interaction:

```python
import os
os.environ["BROWSER_AGENT_MOCK_ACTIONS"] = "true"

# All actions will be mocked
agent = BrowserAgent()
result = agent.run_cycle("Click somewhere")
# Output: "MOCK: Clicked at (100,200)"
```

## File Structure

```
src/agent/browser/
├── browser_agent.py      # Main BrowserAgent class
├── browser_tools.py      # Browser action tools
├── browser_config.py     # Configuration management
├── browser_utils.py      # Utility functions
└── BROWSER-AGENT-PROJECT.md  # Project specification

tests/
└── test_browser_agent.py # Tests

demo_browser_agent.py     # Demo script
```

## Examples

### Click on Element

```python
# Click on a specific button
result = agent.run_cycle("Click on the login button at the top right")

# Click at specific coordinates
result = agent.run_cycle("Click at coordinates 100,200")
```

### Form Interaction

```python
# Fill a form field
result = agent.run_cycle("Type 'john@example.com' in the email field")

# Submit form
result = agent.run_cycle("Click the submit button")
```

### Navigation

```python
# Scroll to see more content
result = agent.run_cycle("Scroll down 3 times to see more content")

# Navigate to menu
result = agent.run_cycle("Click on the settings menu")
```

## Troubleshooting

### Common Issues

1. **Permission Denied**: Run as administrator on Windows for screen capture
2. **pyautogui Not Working**: Install pyautogui and check permissions
3. **Screenshot Analysis Failed**: Check LLM vision model configuration
4. **Coordinates Out of Bounds**: Verify screen resolution settings

### Debug Mode

```python
import os
os.environ["BROWSER_AGENT_DEBUG"] = "true"

# Enable screenshot saving
os.environ["BROWSER_AGENT_SAVE_SCREENSHOTS"] = "true"

agent = BrowserAgent()
# Will save screenshots and show detailed logs
```

### Performance Tips

- Use smaller screenshot dimensions for faster processing
- Enable screenshot caching for similar actions
- Use mock mode for testing without actual browser interaction

## Development

### Adding New Actions

1. Add tool function to `browser_tools.py`
2. Register tool in `BrowserAgent._register_tools()`
3. Add parsing logic in `_parse_action_from_response()`
4. Add visualization in `visualize_action()`

### Extending Visualization

```python
def custom_visualization(screenshot, action_data):
    # Custom visualization logic
    return modified_screenshot

agent.visualize_action = custom_visualization
```

## Integration

### With NetTyan Framework

The browser agent integrates with the existing NetTyan agent system:

- Uses `VisionProcessor` for screenshot analysis
- Integrates with tool registration system
- Follows NetTyan logging patterns
- Uses existing LLM client configuration

### With Other Agents

```python
# Use in agent workflows
def web_automation_task(task_description):
    browser_agent = BrowserAgent()
    return browser_agent.run_cycle(task_description)
```

## License

Part of the NetTyan project.
