"""
Browser action tools for BrowserAgent.
Implements actual browser control using pyautogui with proper tool logging.
"""

import os
import time
import traceback
from typing import Optional, Tuple, Union

from agent.tools.control_tools import (
    _add_tool_error_log,
    _add_tool_result_log,
    _add_tool_run_log,
)

# Import pyautogui with fallback for testing
try:
    import pyautogui

    pyautogui.FAILSAFE = True  # Move mouse to top-left to stop execution
    PYAUTOGUI_AVAILABLE = True
except ImportError:
    PYAUTOGUI_AVAILABLE = False
    print("[BROWSER TOOLS WARNING] pyautogui not available - using mock actions")

# Enable mock mode for testing
MOCK_MODE = os.getenv("BROWSER_AGENT_MOCK_ACTIONS", "false").lower() == "true"


def _validate_position(position: Tuple[int, int]) -> bool:
    """Validate that position is within screen bounds"""
    if not PYAUTOGUI_AVAILABLE:
        return True

    try:
        screen_width, screen_height = pyautogui.size()
        x, y = position
        return 0 <= x < screen_width and 0 <= y < screen_height
    except:
        return False


def mouse_hover(position: str, speed: Optional[float] = None) -> str:
    """
    Move the mouse to a new position (x, y).
    Args:
        position: Position as "x,y" string.
        speed: Optional float for movement speed (future).
    """
    tool_name = "mouse_hover"
    call_id = _add_tool_run_log(tool_name, {"position": position, "speed": speed})

    try:
        # Parse position string
        x, y = map(int, position.split(","))
        pos = (x, y)

        if not _validate_position(pos):
            error_msg = f"Invalid position {pos} - out of screen bounds"
            _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
            return error_msg

        if MOCK_MODE or not PYAUTOGUI_AVAILABLE:
            result = f"MOCK: Mouse hovered to {pos} with speed {speed}"
        else:
            duration = 0.5 if speed is None else speed
            pyautogui.moveTo(x, y, duration=duration)
            result = f"Mouse hovered to {pos}"

        _add_tool_result_log(tool_name, {"result": result, "call_id": call_id})
        return result

    except Exception as e:
        error_msg = f"Mouse hover failed: {str(e)}"
        _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
        traceback.print_exc()
        return error_msg


def click(position: str, hold: bool = False) -> str:
    """
    Click at a given position (x, y).
    Args:
        position: Position as "x,y" string.
        hold: If True, hold the click (future).
    """
    tool_name = "click"
    call_id = _add_tool_run_log(tool_name, {"position": position, "hold": hold})

    try:
        # Parse position string
        x, y = map(int, position.split(","))
        pos = (x, y)

        if not _validate_position(pos):
            error_msg = f"Invalid position {pos} - out of screen bounds"
            _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
            return error_msg

        if MOCK_MODE or not PYAUTOGUI_AVAILABLE:
            result = f"MOCK: Clicked at {pos} (hold={hold})"
        else:
            if hold:
                pyautogui.mouseDown(x, y)
                result = f"Started holding click at {pos}"
            else:
                pyautogui.click(x, y)
                result = f"Clicked at {pos}"

        _add_tool_result_log(tool_name, {"result": result, "call_id": call_id})
        return result

    except Exception as e:
        error_msg = f"Click failed: {str(e)}"
        _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
        traceback.print_exc()
        return error_msg


def scroll(direction: str, amount: int = 1) -> str:
    """
    Scroll up or down by a given amount.
    Args:
        direction: 'up' or 'down'.
        amount: Number of scroll steps.
    """
    tool_name = "scroll"
    call_id = _add_tool_run_log(tool_name, {"direction": direction, "amount": amount})

    try:
        if direction not in ["up", "down"]:
            error_msg = f"Invalid direction '{direction}' - must be 'up' or 'down'"
            _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
            return error_msg

        if MOCK_MODE or not PYAUTOGUI_AVAILABLE:
            result = f"MOCK: Scrolled {direction} by {amount}"
        else:
            scroll_amount = amount if direction == "up" else -amount
            pyautogui.scroll(scroll_amount)
            result = f"Scrolled {direction} by {amount}"

        _add_tool_result_log(tool_name, {"result": result, "call_id": call_id})
        return result

    except Exception as e:
        error_msg = f"Scroll failed: {str(e)}"
        _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
        traceback.print_exc()
        return error_msg


def keyboard_input(text: str = None, key: str = None) -> str:
    """
    Input text or press a key on the keyboard.
    Args:
        text: Text to input.
        key: Key to press (if not text input).
    """
    tool_name = "keyboard_input"
    call_id = _add_tool_run_log(tool_name, {"text": text, "key": key})

    try:
        if not text and not key:
            error_msg = "Either text or key must be provided"
            _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
            return error_msg

        if MOCK_MODE or not PYAUTOGUI_AVAILABLE:
            if text:
                result = f"MOCK: Input text: {text}"
            else:
                result = f"MOCK: Pressed key: {key}"
        else:
            if text:
                pyautogui.typewrite(text)
                result = f"Input text: {text}"
            elif key:
                pyautogui.press(key)
                result = f"Pressed key: {key}"

        _add_tool_result_log(tool_name, {"result": result, "call_id": call_id})
        return result

    except Exception as e:
        error_msg = f"Keyboard input failed: {str(e)}"
        _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
        traceback.print_exc()
        return error_msg


def release_mouse() -> str:
    """
    Release any held mouse buttons.
    """
    tool_name = "release_mouse"
    call_id = _add_tool_run_log(tool_name, {})

    try:
        if MOCK_MODE or not PYAUTOGUI_AVAILABLE:
            result = "MOCK: Released mouse buttons"
        else:
            pyautogui.mouseUp()
            result = "Released mouse buttons"

        _add_tool_result_log(tool_name, {"result": result, "call_id": call_id})
        return result

    except Exception as e:
        error_msg = f"Release mouse failed: {str(e)}"
        _add_tool_error_log(tool_name, {"error": error_msg, "call_id": call_id})
        traceback.print_exc()
        return error_msg
