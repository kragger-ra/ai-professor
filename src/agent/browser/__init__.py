"""
Browser Agent Module

Autonomous browser automation using computer vision and LLM reasoning.

Usage:
    from src.agent.browser import BrowserAgent

    agent = BrowserAgent()
    result = agent.run_cycle("Click on the login button")
"""

from .browser_agent import BrowserAgent
from .browser_config import get_browser_agent_config
from .browser_tools import click, keyboard_input, mouse_hover, release_mouse, scroll
from .browser_utils import (
    create_action_visualization,
    get_screen_info,
    parse_position,
    scale_coordinates,
    validate_coordinates,
)

__all__ = [
    "BrowserAgent",
    "mouse_hover",
    "click",
    "scroll",
    "keyboard_input",
    "release_mouse",
    "get_browser_agent_config",
    "validate_coordinates",
    "parse_position",
    "scale_coordinates",
    "create_action_visualization",
    "get_screen_info",
]

__version__ = "0.1.0"
__author__ = "NetTyan Team"
__description__ = "Autonomous browser automation agent"
