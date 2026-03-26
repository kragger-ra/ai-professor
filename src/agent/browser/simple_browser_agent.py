#!/usr/bin/env python3
"""
Simple Browser Agent - One file, works!
"""

import os
import sys
import time
from datetime import datetime
from typing import Any, Dict

# Add src to path
sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
)

# Import the real browser agent
try:
    from agent.browser.browser_agent import BrowserAgent

    AGENT_AVAILABLE = True
    print("✅ Real BrowserAgent available")
except ImportError:
    AGENT_AVAILABLE = False
    print("❌ Real BrowserAgent not available")

import gradio as gr
import mss
import pyautogui
from PIL import Image, ImageDraw

pyautogui.FAILSAFE = True


class SimpleAgent:
    """Simple agent that uses the real browser agent."""

    def __init__(self):
        self.running = False
        self.history = []

        if AGENT_AVAILABLE:
            try:
                self.agent = BrowserAgent()
                print("✅ Real agent initialized")
            except Exception as e:
                print(f"❌ Agent init failed: {e}")
                self.agent = None
        else:
            self.agent = None

    def run_task(self, task: str):
        """Run a single task."""
        if not self.agent:
            return {"error": "Agent not available", "success": False}

        try:
            # Use real agent
            result = self.agent.run_cycle(task)

            # Get screenshot
            screenshot = self.agent.capture_screenshot()

            # Get visualized screenshot if available
            visualized_screenshot = None
            if result.get("attempts") and len(result["attempts"]) > 0:
                last_attempt = result["attempts"][-1]
                if (
                    "revision" in last_attempt
                    and "visualized_screenshot" in last_attempt["revision"]
                ):
                    visualized_screenshot = last_attempt["revision"][
                        "visualized_screenshot"
                    ]

            # Record
            record = {
                "task": task,
                "result": result,
                "screenshot": screenshot,
                "visualized_screenshot": visualized_screenshot,
                "success": result.get("success", False),
                "timestamp": datetime.now().isoformat(),
            }

            self.history.append(record)
            return record

        except Exception as e:
            error_record = {
                "task": task,
                "result": {"error": str(e), "success": False},
                "screenshot": None,
                "visualized_screenshot": None,
                "success": False,
                "timestamp": datetime.now().isoformat(),
            }
            self.history.append(error_record)
            return error_record

    def run_loop(self, tasks_text: str, delay: float = 1.0):
        """Run tasks in loop."""
        if not tasks_text.strip():
            return "No tasks"

        tasks = [t.strip() for t in tasks_text.split("\n") if t.strip()]

        self.running = True
        results = []

        for task in tasks:
            if not self.running:
                break

            result = self.run_task(task)

            if result["success"]:
                results.append(f"✅ {task}")
            else:
                results.append(f"❌ {task}: {result['result']}")

            time.sleep(delay)

        return "\n".join(results)

    def stop_loop(self):
        """Stop loop."""
        self.running = False

    def get_screenshot(self):
        """Get current screenshot."""
        if not self.agent:
            return None
        try:
            return self.agent.capture_screenshot()
        except:
            return None


# Global agent
agent = SimpleAgent()


def execute_task(task):
    """Execute single task."""
    if not task.strip():
        return "Enter task", None, None, ""

    result = agent.run_task(task)

    # Raw output for user
    output = f"""
TASK: {task}
SUCCESS: {result['success']}
RESULT: {result['result']}
TIME: {result['timestamp']}
"""

    # Get screenshots
    screenshot = result.get("screenshot")
    visualized_screenshot = result.get("visualized_screenshot")

    return output, screenshot, visualized_screenshot, str(result)


def run_loop(tasks_text, delay):
    """Run loop."""
    return agent.run_loop(tasks_text, delay)


def stop_loop():
    """Stop loop."""
    agent.stop_loop()
    return "Stopped"


def get_screenshot():
    """Get screenshot."""
    return agent.get_screenshot()


# Simple interface
with gr.Blocks(title="Browser Agent") as demo:
    gr.Markdown("# 🤖 Browser Agent")

    with gr.Row():
        with gr.Column():
            task_input = gr.Textbox(label="Task", placeholder="Click at 200,300")
            execute_btn = gr.Button("Execute", variant="primary")

            gr.Markdown("### Loop Mode")
            tasks_input = gr.Textbox(label="Tasks (one per line)", lines=5)
            delay_input = gr.Number(label="Delay (seconds)", value=1.0)

            with gr.Row():
                start_btn = gr.Button("Start Loop", variant="primary")
                stop_btn = gr.Button("Stop", variant="secondary")

        with gr.Column():
            with gr.Row():
                screenshot_img = gr.Image(label="Screenshot", height=300)
                visualized_img = gr.Image(label="Action Visualization", height=300)
            screenshot_btn = gr.Button("Screenshot")

    # Outputs
    output_text = gr.Textbox(label="Output", lines=10)
    raw_output = gr.Textbox(label="Raw Output", lines=5)
    loop_output = gr.Textbox(label="Loop Output", lines=5)

    # Events
    execute_btn.click(
        fn=execute_task,
        inputs=[task_input],
        outputs=[output_text, screenshot_img, visualized_img, raw_output],
    )

    start_btn.click(
        fn=run_loop, inputs=[tasks_input, delay_input], outputs=[loop_output]
    )

    stop_btn.click(fn=stop_loop, outputs=[loop_output])

    screenshot_btn.click(fn=get_screenshot, outputs=[screenshot_img])

    # Load initial screenshot
    demo.load(fn=get_screenshot, outputs=[screenshot_img])

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7860, share=False)
