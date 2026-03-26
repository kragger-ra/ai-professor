"""
Browser Agent Configuration

Configuration settings for the browser automation agent.
"""

import os
from typing import Any, Dict, Tuple

# Default configuration
DEFAULT_CONFIG = {
    # Screenshot settings
    "screenshot_resize": (1280, 720),
    "screenshot_quality": "PNG",
    # Visualization settings
    "visualization_color": "red",
    "visualization_size": 20,
    "visualization_line_width": 3,
    # Action settings
    "max_retries": 3,
    "action_timeout": 10.0,
    "mouse_move_speed": 0.5,
    # LLM settings
    "vision_model_name": "",  # Use default from config
    "action_prompt_template": """
You are a browser automation agent. Analyze the screenshot and determine the appropriate action for: {prompt}

Available actions:
- !click x,y - Click at coordinates (x,y)
- !mouse_hover x,y - Move mouse to coordinates (x,y)  
- !scroll up/down amount - Scroll up or down by amount
- !keyboard_input text - Type text
- !release_mouse - Release any held mouse buttons

Look at the screenshot and identify the exact coordinates where you need to click or hover.
Be precise with coordinates. Respond with the exact action command.

Current task: {prompt}
""",
    "revision_prompt_template": """
You are reviewing a planned browser action. The red visualization shows what will happen:

Original response: {response}
Planned action: {action_data}

Look at the screenshot with the red visualization overlay:
- Red circle with dot = Click location
- Red arrow = Scroll direction
- Red text = Action type

Questions to consider:
1. Is the action targeting the correct element?
2. Are the coordinates accurate?
3. Will this action achieve the intended goal?
4. Are there any potential issues?

Respond with either:
- "APPROVED" if the action looks correct
- "REFINE: [explanation]" if changes are needed
- "REJECT: [reason]" if the action should not be performed

Be concise and clear in your assessment.
""",
    # Debug settings
    "debug_mode": False,
    "save_screenshots": False,
    "screenshot_save_path": "data/temp",
    # Mock settings for testing
    "mock_mode": False,
    "mock_screen_size": (1920, 1080),
}


def load_config() -> Dict[str, Any]:
    """Load configuration from environment variables and defaults."""
    config = DEFAULT_CONFIG.copy()

    # Override with environment variables
    env_overrides = {
        "BROWSER_AGENT_DEBUG": ("debug_mode", lambda x: x.lower() == "true"),
        "BROWSER_AGENT_MOCK_ACTIONS": ("mock_mode", lambda x: x.lower() == "true"),
        "BROWSER_AGENT_SCREENSHOT_RESIZE": ("screenshot_resize", parse_tuple),
        "BROWSER_AGENT_MAX_RETRIES": ("max_retries", int),
        "BROWSER_AGENT_MOUSE_SPEED": ("mouse_move_speed", float),
        "BROWSER_AGENT_VIZ_COLOR": ("visualization_color", str),
        "BROWSER_AGENT_VIZ_SIZE": ("visualization_size", int),
        "BROWSER_AGENT_SAVE_SCREENSHOTS": (
            "save_screenshots",
            lambda x: x.lower() == "true",
        ),
        "BROWSER_AGENT_SCREENSHOT_PATH": ("screenshot_save_path", str),
    }

    for env_var, (config_key, converter) in env_overrides.items():
        value = os.getenv(env_var)
        if value is not None:
            try:
                config[config_key] = converter(value)
            except (ValueError, TypeError) as e:
                print(f"Warning: Invalid value for {env_var}: {value} ({e})")

    return config


def parse_tuple(value: str) -> Tuple[int, int]:
    """Parse tuple from string like '1280,720'."""
    try:
        parts = value.split(",")
        if len(parts) == 2:
            return (int(parts[0].strip()), int(parts[1].strip()))
        else:
            raise ValueError("Tuple must have exactly 2 values")
    except (ValueError, IndexError):
        raise ValueError(f"Invalid tuple format: {value}")


def get_browser_agent_config() -> Dict[str, Any]:
    """Get the current browser agent configuration."""
    return load_config()


def print_config():
    """Print current configuration for debugging."""
    config = load_config()
    print("Browser Agent Configuration:")
    print("=" * 40)
    for key, value in config.items():
        print(f"{key}: {value}")
    print()


if __name__ == "__main__":
    print_config()
