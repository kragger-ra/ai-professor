import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from queue import Queue

import mss
import numpy as np
import torch
from PIL import Image
from vision_processor import VisionProcessor

PROJECT_ROOT = Path(__file__).parent.absolute()

# Define device for torch operations (not directly used by LM Studio API but kept for compatibility)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Screen capture configuration
SCREEN_CONFIG = {
    "capture_interval": 1.0,
    "resize_width": 640,
    "resize_height": 480,
}


class LiveAssistant:
    def __init__(self):
        self.vision_processor = VisionProcessor()
        self.vision_queue = Queue()

        self.sct = mss.mss()
        self.monitor = self.sct.monitors[1]

        self.running = False
        self.last_vision_analysis = None
        self.last_screen_state = None

        self.temp_dir = "."

    def capture_screen(self):
        screenshot = self.sct.grab(self.monitor)
        img = Image.frombytes(
            "RGB", (screenshot.width, screenshot.height), screenshot.rgb
        )
        img = img.resize(
            (SCREEN_CONFIG["resize_width"], SCREEN_CONFIG["resize_height"])
        )

        img_path = os.path.join(self.temp_dir, "temp.png")
        img.save(img_path)

        return img, img_path

    def start(self):
        self.running = True
        print("\nRunning Visual agent...")

        vision_thread = threading.Thread(target=self._vision_loop)
        vision_thread.start()

        try:
            while self.running:
                time.sleep(0.1)
        except KeyboardInterrupt:
            self.stop()

        vision_thread.join()

    def stop(self):
        self.running = False
        print("\nShutting down...")

    def _vision_loop(self):
        last_capture_time = 0

        while self.running:
            current_time = time.time()
            if current_time - last_capture_time >= SCREEN_CONFIG["capture_interval"]:
                try:
                    screen_img, img_path = self.capture_screen()

                    start_time = time.time()
                    analysis = self.vision_processor.analyze_image(screen_img)
                    process_time = time.time() - start_time

                    if analysis["status"] == "success":
                        current_state = analysis["description"]

                        # Compare with previous state if exists
                        changes = (
                            "Initial analysis"
                            if self.last_screen_state is None
                            else self.vision_processor.detect_changes(
                                self.last_screen_state, current_state
                            )
                        )

                        self.last_screen_state = current_state

                        output = {
                            "timestamp": datetime.utcnow().isoformat(),
                            "changes_detected": changes,
                            "current_state": current_state,
                            "process_time": f"{process_time:.2f}s",
                        }

                        self.vision_queue.put(output)

                        print(
                            f"\n[{datetime.now().strftime('%H:%M:%S')}] Screen Analysis:"
                        )
                        print(f"Process time: {process_time:.2f}s")
                        print("Analysis:")
                        print(json.dumps(output, indent=2))
                        print("-" * 80)

                    last_capture_time = current_time

                except Exception as e:
                    print(f"Vision error: {str(e)}")
                    time.sleep(1)


if __name__ == "__main__":
    assistant = LiveAssistant()
    try:
        assistant.start()
    except KeyboardInterrupt:
        assistant.stop()
