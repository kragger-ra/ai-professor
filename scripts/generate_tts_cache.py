"""Pre-generate WAV cache for common professor phrases.

Run this once after starting the Vosk-TTS server:
  python scripts/generate_tts_cache.py

Requires Vosk-TTS server running on http://localhost:22232
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tts.vosk.vosk_tts import generate_phrase_cache

if __name__ == "__main__":
    generate_phrase_cache()
