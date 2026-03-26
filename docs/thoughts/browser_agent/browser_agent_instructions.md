# Browser Agent Instructions

## Setup and Installation

### Prerequisites
- Python environment with existing NetTyan dependencies
- pyautogui for mouse/keyboard control
- PIL/Pillow for image processing

### Installation
```bash
# Navigate to project root
cd d:\Pets\NetTyan\Python\NetTyanRepo\NetTyan

# Install additional dependencies (if needed)
pip install pyautogui pillow

# From the src directory, the browser agent can be imported
```

## Running the Browser Agent

### Basic Usage
```python
from src.agent.browser.browser_agent import BrowserAgent

# Initialize the agent
agent = BrowserAgent()

# Run a simple action cycle
agent.run_cycle("Click on the login button")
```

### Advanced Usage
```python
# Initialize with custom context
agent = BrowserAgent(ctx={"screen_resolution": (1920, 1080)})

# Manual cycle control
action_req = agent.action_request("Navigate to the settings page")
revision = agent.action_revision(action_req)
if revision.get("approved"):
    agent.execute_action(action_req)
```

## Testing

### Running Tests
```bash
# From project root
python -m pytest tests/ -v

# Run specific browser agent tests
python -m pytest tests/test_browser_agent.py -v

# Run with coverage
python -m pytest tests/ --cov=src.agent.browser --cov-report=html
```

### Manual Testing
```python
# Simple test in Python REPL
from src.agent.browser.browser_agent import BrowserAgent

agent = BrowserAgent()
screenshot = agent.capture_and_display_screenshot()
# Verify screenshot is captured correctly
```

## Development

### Code Structure
- `browser_agent.py`: Main BrowserAgent class with cycle logic
- `browser_tools.py`: Individual action tools (mouse, keyboard, scroll)
- `BROWSER-AGENT-PROJECT.md`: Project specification

### Key Design Patterns
- Use existing NetTyan pipeline methods
- Leverage VisionProcessor for screenshot handling
- Integrate with existing tool registration system
- Follow two-stage cycle: request → revision → execution

### Debugging
- Enable verbose logging in LLM client
- Save screenshots during action planning
- Use mock actions for testing without actual mouse/keyboard events

## Configuration

### Environment Variables
- `BROWSER_AGENT_DEBUG`: Enable debug mode
- `BROWSER_AGENT_MOCK_ACTIONS`: Use mock actions instead of real mouse/keyboard

### Settings
- Screenshot quality and format
- Action timing and delays
- Visualization styles (red dot size, color)

## Troubleshooting

### Common Issues
1. **Permission denied for screen capture**: Run as administrator on Windows
2. **Mouse actions not working**: Check if pyautogui is installed and permissions granted
3. **LLM not understanding screenshots**: Verify vision model is loaded correctly

### Performance Tips
- Use smaller screenshot regions when possible
- Cache screenshots for similar actions
- Optimize LLM prompt length
