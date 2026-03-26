import base64
import io
import json
import os
from typing import Any, Dict, List, Optional

from PIL import Image, ImageDraw

from agent.llm_clients.lc_clients import get_llm_chain
from agent.prompt_generation.prompt_constructor import construct_prompt_messages
from agent.tools.status_tools import register_tool
from agent.tools.tool_executor import execute_tools
from agent.tools.vision_tools import VisionProcessor

from .browser_tools import click, keyboard_input, mouse_hover, release_mouse, scroll


class BrowserAgent:
    """
    Browser agent that follows the cycle described in BROWSER-AGENT-PROJECT.md:
    1. Action request: Prompt for new action, display screenshot, output action request (tool use)
    2. Action revision: Prompt for future action assessment, display screenshot with visualisation, output approval/refinement
    """

    def __init__(self, ctx: Optional[Dict[str, Any]] = None):
        self.ctx = ctx or {}
        self.llm = get_llm_chain()
        self.vision_processor = VisionProcessor()
        self.running = False
        self.last_screenshot = None
        self.last_action_request = None

        # Register browser action tools in the tool bank
        self.tool_bank = {}
        self._register_tools()

        # Agent configuration
        self.config = {
            "visualization_color": "red",
            "visualization_size": 20,
            "max_retries": 3,
            "screenshot_resize": (1280, 720),
        }

    def _register_tools(self):
        """Register each browser tool using the status_tools pattern"""
        browser_tools = [mouse_hover, click, scroll, keyboard_input, release_mouse]
        for tool in browser_tools:
            tool_record = register_tool(tool.__name__, tool)
            self.tool_bank[tool.__name__] = tool_record

    def capture_screenshot(self) -> Image.Image:
        """Capture and return a screenshot using VisionProcessor."""
        img = self.vision_processor.capture_screen()

        # Resize for better LLM processing
        if self.config["screenshot_resize"]:
            img = img.resize(self.config["screenshot_resize"])

        self.last_screenshot = img
        return img

    def visualize_action(
        self, screenshot: Image.Image, action_data: Dict[str, Any]
    ) -> Image.Image:
        """Add visualization overlay to screenshot for the planned action."""
        if not action_data or "action_type" not in action_data:
            return screenshot

        # Create a copy to avoid modifying original
        vis_img = screenshot.copy()
        draw = ImageDraw.Draw(vis_img)

        color = self.config["visualization_color"]
        size = self.config["visualization_size"]

        action_type = action_data["action_type"]

        if action_type in ["click", "mouse_hover"] and "position" in action_data:
            try:
                pos_str = action_data["position"]
                x, y = map(int, pos_str.split(","))

                # Scale position to resized screenshot
                if self.config["screenshot_resize"]:
                    original_size = self.vision_processor.config.get(
                        "original_size", (1920, 1080)
                    )
                    scale_x = self.config["screenshot_resize"][0] / original_size[0]
                    scale_y = self.config["screenshot_resize"][1] / original_size[1]
                    x = int(x * scale_x)
                    y = int(y * scale_y)

                # Draw red circle
                draw.ellipse(
                    [x - size // 2, y - size // 2, x + size // 2, y + size // 2],
                    outline=color,
                    width=3,
                )

                # Draw center dot
                draw.ellipse([x - 2, y - 2, x + 2, y + 2], fill=color)

                if action_type == "click":
                    # Add click indicator
                    draw.text((x + size // 2 + 5, y - 10), "CLICK", fill=color)

            except (ValueError, IndexError):
                pass

        elif action_type == "scroll":
            # Add scroll indicator in center
            width, height = vis_img.size
            center_x, center_y = width // 2, height // 2

            direction = action_data.get("direction", "up")
            if direction == "up":
                # Arrow pointing up
                draw.polygon(
                    [
                        (center_x, center_y - 20),
                        (center_x - 10, center_y),
                        (center_x + 10, center_y),
                    ],
                    fill=color,
                )
                draw.text((center_x + 15, center_y - 10), "SCROLL UP", fill=color)
            else:
                # Arrow pointing down
                draw.polygon(
                    [
                        (center_x, center_y + 20),
                        (center_x - 10, center_y),
                        (center_x + 10, center_y),
                    ],
                    fill=color,
                )
                draw.text((center_x + 15, center_y - 10), "SCROLL DOWN", fill=color)

        return vis_img

    def _parse_action_from_response(self, response: str) -> Dict[str, Any]:
        """Parse action data from LLM response."""
        response_lower = response.lower()

        # Try to extract action commands
        lines = response.split("\n")
        for line in lines:
            line = line.strip()

            # Look for tool commands
            if line.startswith("!click "):
                pos = line.replace("!click ", "").strip()
                return {"action_type": "click", "position": pos}
            elif line.startswith("!mouse_hover "):
                pos = line.replace("!mouse_hover ", "").strip()
                return {"action_type": "mouse_hover", "position": pos}
            elif line.startswith("!scroll "):
                parts = line.replace("!scroll ", "").strip().split()
                direction = parts[0] if parts else "up"
                amount = int(parts[1]) if len(parts) > 1 else 1
                return {
                    "action_type": "scroll",
                    "direction": direction,
                    "amount": amount,
                }
            elif line.startswith("!keyboard_input "):
                text = line.replace("!keyboard_input ", "").strip()
                return {"action_type": "keyboard_input", "text": text}

        return {}

    def action_request(self, prompt: str) -> Dict[str, Any]:
        """Prompt for new action, display screenshot, and output action request (tool use)."""
        screenshot = self.capture_screenshot()

        # Convert screenshot to base64 for LLM
        img_byte_arr = io.BytesIO()
        screenshot.save(img_byte_arr, format="PNG")
        img_byte_arr = img_byte_arr.getvalue()
        screenshot_b64 = base64.b64encode(img_byte_arr).decode("utf-8")

        # Construct action request prompt
        action_prompt = f"""
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
"""

        # Use vision processor to analyze and get action
        analysis = self.vision_processor.analyze_image(screenshot, action_prompt)

        if analysis["status"] == "success":
            response = analysis["description"]
            action_data = self._parse_action_from_response(response)

            result = {
                "response": response,
                "screenshot": screenshot,
                "action_data": action_data,
                "timestamp": self.vision_processor.last_screen_state,
            }

            self.last_action_request = result
            return result
        else:
            return {
                "response": "Failed to analyze screenshot",
                "screenshot": screenshot,
                "action_data": {},
                "error": analysis.get("error", "Unknown error"),
            }

    def action_revision(self, action_request: Dict[str, Any]) -> Dict[str, Any]:
        """Prompt for future action assessment, display screenshot with visualisation, output approval/refinement."""
        if not action_request or "action_data" not in action_request:
            return {"approved": False, "reason": "No action data provided"}

        screenshot = action_request["screenshot"]
        action_data = action_request["action_data"]

        # Create visualization
        visualized_screenshot = self.visualize_action(screenshot, action_data)

        # Convert to base64 for LLM
        img_byte_arr = io.BytesIO()
        visualized_screenshot.save(img_byte_arr, format="PNG")
        img_byte_arr = img_byte_arr.getvalue()
        vis_screenshot_b64 = base64.b64encode(img_byte_arr).decode("utf-8")

        # Construct revision prompt
        revision_prompt = f"""
You are reviewing a planned browser action. The red visualization shows what will happen:

Original response: {action_request['response']}
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
"""

        # Use vision processor for revision analysis
        revision_analysis = self.vision_processor.analyze_image(
            visualized_screenshot, revision_prompt
        )

        if revision_analysis["status"] == "success":
            response = revision_analysis["description"].strip()

            if response.startswith("APPROVED"):
                return {
                    "approved": True,
                    "visualized_screenshot": visualized_screenshot,
                    "revision_response": response,
                }
            elif response.startswith("REFINE:"):
                return {
                    "approved": False,
                    "refine": True,
                    "reason": response.replace("REFINE:", "").strip(),
                    "visualized_screenshot": visualized_screenshot,
                    "revision_response": response,
                }
            else:
                return {
                    "approved": False,
                    "refine": False,
                    "reason": response.replace("REJECT:", "").strip(),
                    "visualized_screenshot": visualized_screenshot,
                    "revision_response": response,
                }
        else:
            return {
                "approved": False,
                "reason": "Failed to analyze revision",
                "error": revision_analysis.get("error", "Unknown error"),
            }

    def execute_action(self, action_request: Dict[str, Any]) -> Any:
        """Execute the given browser action using the tool pipeline."""
        if not action_request or "action_data" not in action_request:
            return "No action data to execute"

        action_data = action_request["action_data"]
        action_type = action_data.get("action_type")

        if not action_type:
            return "No action type specified"

        try:
            if action_type == "click":
                return click(action_data["position"])
            elif action_type == "mouse_hover":
                return mouse_hover(action_data["position"])
            elif action_type == "scroll":
                return scroll(action_data["direction"], action_data.get("amount", 1))
            elif action_type == "keyboard_input":
                if "text" in action_data:
                    return keyboard_input(text=action_data["text"])
                elif "key" in action_data:
                    return keyboard_input(key=action_data["key"])
            elif action_type == "release_mouse":
                return release_mouse()
            else:
                return f"Unknown action type: {action_type}"

        except Exception as e:
            return f"Action execution failed: {str(e)}"

    def run_cycle(self, prompt: str, max_retries: int = None) -> Dict[str, Any]:
        """Run the full browser agent cycle: action request -> revision -> execution."""
        if max_retries is None:
            max_retries = self.config["max_retries"]

        results = {
            "prompt": prompt,
            "attempts": [],
            "final_result": None,
            "success": False,
        }

        for attempt in range(max_retries):
            try:
                # Step 1: Action request
                action_req = self.action_request(prompt)

                # Step 2: Action revision
                revision = self.action_revision(action_req)

                attempt_data = {
                    "attempt": attempt + 1,
                    "action_request": action_req,
                    "revision": revision,
                    "execution_result": None,
                }

                if revision.get("approved"):
                    # Step 3: Execute action
                    execution_result = self.execute_action(action_req)
                    attempt_data["execution_result"] = execution_result

                    results["attempts"].append(attempt_data)
                    results["final_result"] = execution_result
                    results["success"] = True
                    break

                elif revision.get("refine"):
                    # Try to refine the action
                    refined_prompt = (
                        f"{prompt}\n\nPrevious attempt failed: {revision['reason']}"
                    )
                    attempt_data["refined_prompt"] = refined_prompt
                    results["attempts"].append(attempt_data)
                    prompt = refined_prompt  # Update prompt for next attempt
                    continue

                else:
                    # Action rejected
                    attempt_data["rejection_reason"] = revision.get(
                        "reason", "Action rejected"
                    )
                    results["attempts"].append(attempt_data)
                    break

            except Exception as e:
                attempt_data = {
                    "attempt": attempt + 1,
                    "error": str(e),
                    "action_request": None,
                    "revision": None,
                    "execution_result": None,
                }
                results["attempts"].append(attempt_data)

        return results

    def get_status(self) -> Dict[str, Any]:
        """Get current agent status."""
        return {
            "running": self.running,
            "last_screenshot_available": self.last_screenshot is not None,
            "last_action_request": self.last_action_request is not None,
            "config": self.config,
            "registered_tools": list(self.tool_bank.keys()),
        }
