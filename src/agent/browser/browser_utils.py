"""
Browser Agent Utilities

Helper functions for browser automation tasks.
"""

import os
import time
from typing import Any, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont


def validate_coordinates(
    x: int, y: int, screen_size: Optional[Tuple[int, int]] = None
) -> bool:
    """
    Validate that coordinates are within screen bounds.

    Args:
        x, y: Coordinates to validate
        screen_size: Optional screen size tuple (width, height)

    Returns:
        bool: True if coordinates are valid
    """
    if screen_size is None:
        try:
            import pyautogui

            screen_size = pyautogui.size()
        except ImportError:
            # Default screen size if pyautogui not available
            screen_size = (1920, 1080)

    width, height = screen_size
    return 0 <= x < width and 0 <= y < height


def parse_position(position_str: str) -> Tuple[int, int]:
    """
    Parse position string like 'x,y' into tuple.

    Args:
        position_str: String like "100,200"

    Returns:
        Tuple of (x, y) coordinates

    Raises:
        ValueError: If position string is invalid
    """
    try:
        parts = position_str.split(",")
        if len(parts) != 2:
            raise ValueError("Position must be in format 'x,y'")

        x = int(parts[0].strip())
        y = int(parts[1].strip())

        return (x, y)
    except (ValueError, IndexError) as e:
        raise ValueError(f"Invalid position format '{position_str}': {e}")


def scale_coordinates(
    x: int, y: int, from_size: Tuple[int, int], to_size: Tuple[int, int]
) -> Tuple[int, int]:
    """
    Scale coordinates from one screen size to another.

    Args:
        x, y: Original coordinates
        from_size: Original screen size (width, height)
        to_size: Target screen size (width, height)

    Returns:
        Scaled coordinates
    """
    from_width, from_height = from_size
    to_width, to_height = to_size

    scale_x = to_width / from_width
    scale_y = to_height / from_height

    new_x = int(x * scale_x)
    new_y = int(y * scale_y)

    return (new_x, new_y)


def create_action_visualization(
    screenshot: Image.Image,
    action_type: str,
    position: Optional[Tuple[int, int]] = None,
    direction: Optional[str] = None,
    color: str = "red",
    size: int = 20,
) -> Image.Image:
    """
    Create visualization overlay for browser actions.

    Args:
        screenshot: PIL Image to overlay on
        action_type: Type of action (click, hover, scroll, etc.)
        position: Optional position tuple for click/hover
        direction: Optional direction for scroll
        color: Color for visualization
        size: Size of visualization elements

    Returns:
        Image with visualization overlay
    """
    # Create a copy to avoid modifying original
    vis_img = screenshot.copy()
    draw = ImageDraw.Draw(vis_img)

    if action_type in ["click", "mouse_hover"] and position:
        x, y = position

        # Draw circle
        draw.ellipse(
            [x - size // 2, y - size // 2, x + size // 2, y + size // 2],
            outline=color,
            width=3,
        )

        # Draw center dot
        draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)

        # Add text label
        if action_type == "click":
            draw.text((x + size // 2 + 5, y - 10), "CLICK", fill=color)
        else:
            draw.text((x + size // 2 + 5, y - 10), "HOVER", fill=color)

    elif action_type == "scroll":
        # Add scroll indicator in center
        width, height = vis_img.size
        center_x, center_y = width // 2, height // 2

        if direction == "up":
            # Arrow pointing up
            points = [
                (center_x, center_y - 20),
                (center_x - 10, center_y),
                (center_x + 10, center_y),
            ]
            draw.polygon(points, fill=color)
            draw.text((center_x + 15, center_y - 10), "SCROLL UP", fill=color)
        else:
            # Arrow pointing down
            points = [
                (center_x, center_y + 20),
                (center_x - 10, center_y),
                (center_x + 10, center_y),
            ]
            draw.polygon(points, fill=color)
            draw.text((center_x + 15, center_y - 10), "SCROLL DOWN", fill=color)

    return vis_img


def save_screenshot_with_timestamp(
    screenshot: Image.Image, save_path: str, prefix: str = "screenshot"
) -> str:
    """
    Save screenshot with timestamp filename.

    Args:
        screenshot: PIL Image to save
        save_path: Directory to save to
        prefix: Filename prefix

    Returns:
        Full path to saved file
    """
    os.makedirs(save_path, exist_ok=True)

    timestamp = int(time.time())
    filename = f"{prefix}_{timestamp}.png"
    filepath = os.path.join(save_path, filename)

    screenshot.save(filepath)
    return filepath


def extract_coordinates_from_text(text: str) -> List[Tuple[int, int]]:
    """
    Extract coordinate pairs from text using regex.

    Args:
        text: Text to search for coordinates

    Returns:
        List of (x, y) coordinate tuples found
    """
    import re

    # Pattern to match numbers separated by comma (with optional spaces)
    pattern = r"(\d+)\s*,\s*(\d+)"
    matches = re.findall(pattern, text)

    coordinates = []
    for match in matches:
        try:
            x, y = int(match[0]), int(match[1])
            coordinates.append((x, y))
        except ValueError:
            continue

    return coordinates


def get_screen_info() -> Dict[str, Any]:
    """
    Get current screen information.

    Returns:
        Dict with screen size and other info
    """
    try:
        import pyautogui

        size = pyautogui.size()
        position = pyautogui.position()

        return {
            "size": size,
            "width": size[0],
            "height": size[1],
            "mouse_position": position,
            "pyautogui_available": True,
        }
    except ImportError:
        return {
            "size": (1920, 1080),
            "width": 1920,
            "height": 1080,
            "mouse_position": (0, 0),
            "pyautogui_available": False,
        }


def format_action_result(
    action_type: str, result: str, execution_time: Optional[float] = None
) -> str:
    """
    Format action result for display.

    Args:
        action_type: Type of action performed
        result: Raw result string
        execution_time: Optional execution time in seconds

    Returns:
        Formatted result string
    """
    time_str = f" ({execution_time:.2f}s)" if execution_time else ""

    if "MOCK" in result:
        return f"🔧 {action_type.upper()}: {result}{time_str}"
    elif "failed" in result.lower() or "error" in result.lower():
        return f"❌ {action_type.upper()}: {result}{time_str}"
    else:
        return f"✅ {action_type.upper()}: {result}{time_str}"


def create_debug_report(
    action_request: Dict[str, Any], revision: Dict[str, Any], execution_result: Any
) -> str:
    """
    Create a debug report for an action cycle.

    Args:
        action_request: Action request data
        revision: Revision data
        execution_result: Execution result

    Returns:
        Formatted debug report
    """
    report = []
    report.append("=== Browser Agent Debug Report ===")
    report.append(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")

    # Action request
    report.append("📋 Action Request:")
    if "action_data" in action_request:
        action_data = action_request["action_data"]
        report.append(f"  Type: {action_data.get('action_type', 'Unknown')}")
        report.append(f"  Data: {action_data}")
    report.append(
        f"  Response: {action_request.get('response', 'No response')[:100]}..."
    )
    report.append("")

    # Revision
    report.append("🔍 Revision:")
    report.append(f"  Approved: {revision.get('approved', False)}")
    if "reason" in revision:
        report.append(f"  Reason: {revision['reason']}")
    report.append("")

    # Execution
    report.append("⚡ Execution:")
    report.append(f"  Result: {execution_result}")
    report.append("")

    return "\n".join(report)


if __name__ == "__main__":
    # Test utilities
    print("🔧 Browser Agent Utilities Test")
    print("=" * 40)

    # Test coordinate validation
    assert validate_coordinates(100, 200) == True
    assert validate_coordinates(-10, 200) == False
    print("✅ Coordinate validation works")

    # Test position parsing
    assert parse_position("100,200") == (100, 200)
    try:
        parse_position("invalid")
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
    print("✅ Position parsing works")

    # Test coordinate scaling
    assert scale_coordinates(100, 200, (1920, 1080), (960, 540)) == (50, 100)
    print("✅ Coordinate scaling works")

    # Test coordinate extraction
    coords = extract_coordinates_from_text("Click at 100,200 then move to 300, 400")
    assert coords == [(100, 200), (300, 400)]
    print("✅ Coordinate extraction works")

    # Test screen info
    info = get_screen_info()
    assert "size" in info
    assert "width" in info
    print("✅ Screen info works")

    print("\n🎉 All utility tests passed!")
