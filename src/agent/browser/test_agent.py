#!/usr/bin/env python3
"""
Simple test to check browser agent functionality
"""

import os
import sys

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

print("Testing browser agent imports...")

try:
    from src.agent.browser.browser_agent import BrowserAgent

    print("✅ BrowserAgent imported successfully")

    # Test initialization
    agent = BrowserAgent()
    print("✅ BrowserAgent initialized successfully")

    # Test screenshot
    screenshot = agent.capture_screenshot()
    print(f"✅ Screenshot captured: {screenshot.size}")

    # Test simple task
    print("🔄 Testing simple task...")
    result = agent.run_cycle("Click at coordinates 100,100")
    print(f"✅ Task result: {result['success']}")

except Exception as e:
    print(f"❌ Error: {e}")
    import traceback

    traceback.print_exc()

print("Test complete!")
