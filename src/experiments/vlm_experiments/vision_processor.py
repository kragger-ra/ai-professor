import base64
import io
import json

import requests
from PIL import Image


class VisionProcessor:
    def __init__(self):
        self.model = "gemma-3-4b-it-GGUF/gemma-3-4b-it-Q4_K_M.gguf"
        self.api_url = "http://localhost:22227/v1"

    def _encode_image_to_base64(self, image):
        """Convert PIL Image to base64 string"""
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode("utf-8")

    def analyze_image(self, image):
        try:
            # Encode image to base64
            base64_image = self._encode_image_to_base64(image)

            # Prepare prompt for vision analysis
            prompt = (
                "Проанализируй этот экран и опиши что изменилось на русском языке. Обрати внимание на: "
                "1. Содержимое активного окна/вкладки "
                "2. Любые изменения в происходящем на экране "
                "3. Изменения элементов интерфейса, такие как открытые меню или всплывающие окна"
            )

            # Prepare payload for LM Studio API
            payload = {
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image",
                                "image_url": {
                                    "url": f"data:image/png;base64,{base64_image}"
                                },
                            },
                        ],
                    }
                ],
                "stream": False,
            }

            # Call LM Studio API
            headers = {"Content-Type": "application/json"}
            response = requests.post(
                f"{self.api_url}/chat/completions", headers=headers, json=payload
            )

            if response.status_code == 200:
                result = response.json()
                description = result["choices"][0]["message"]["content"]
                return {"description": description, "status": "success"}
            else:
                return {
                    "description": None,
                    "status": "error",
                    "error": f"API Error: {response.status_code} - {response.text}",
                }

        except Exception as e:
            return {"description": None, "status": "error", "error": str(e)}

    def detect_changes(self, previous_state, current_state):
        if previous_state == current_state:
            return "No changes detected"

        try:
            # Prepare prompt for change detection
            prompt = (
                "Previous state: " + previous_state + "\n"
                "Current state: " + current_state + "\n"
                "Describe what changed in a concise way."
            )

            # Prepare payload for LM Studio API (text-only query)
            payload = {
                "model": self.model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }

            # Call LM Studio API
            headers = {"Content-Type": "application/json"}
            response = requests.post(
                f"{self.api_url}/chat/completions", headers=headers, json=payload
            )

            if response.status_code == 200:
                result = response.json()
                changes = result["choices"][0]["message"]["content"]
                return changes
            else:
                return f"Error detecting changes: API returned {response.status_code}"

        except Exception as e:
            return f"Error detecting changes: {str(e)}"
