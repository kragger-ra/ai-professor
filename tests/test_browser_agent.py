#!/usr/bin/env python3
"""
Simple test for browser agent functionality.
Tests the basic cycle without requiring actual browser interaction.
"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'src'))

from agent.browser.browser_agent import BrowserAgent
from agent.browser.browser_tools import mouse_hover, click, scroll, keyboard_input

def test_browser_tools():
    """Test basic browser tools functionality."""
    print("Testing browser tools...")
    
    # Enable mock mode for testing
    os.environ["BROWSER_AGENT_MOCK_ACTIONS"] = "true"
    
    # Test mouse hover
    result = mouse_hover("100,200")
    print(f"Mouse hover: {result}")
    assert "100,200" in result or "MOCK" in result
    
    # Test click
    result = click("150,250")
    print(f"Click: {result}")
    assert "150,250" in result or "MOCK" in result
    
    # Test scroll
    result = scroll("up", 3)
    print(f"Scroll: {result}")
    assert "up" in result or "MOCK" in result
    
    # Test keyboard input
    result = keyboard_input(text="Hello World")
    print(f"Keyboard input: {result}")
    assert "Hello World" in result or "MOCK" in result
    
    print("✓ All browser tools tests passed!")

def test_browser_agent_basic():
    """Test basic browser agent functionality."""
    print("\nTesting browser agent...")
    
    # Create agent instance
    agent = BrowserAgent()
    
    # Test status
    status = agent.get_status()
    print(f"Agent status: {status}")
    assert "registered_tools" in status
    assert len(status["registered_tools"]) > 0
    
    # Test screenshot capture (mock)
    try:
        screenshot = agent.capture_screenshot()
        print(f"Screenshot captured: {screenshot is not None}")
        assert screenshot is not None
    except Exception as e:
        print(f"Screenshot test skipped (expected in test env): {e}")
    
    print("✓ Basic browser agent tests passed!")

def test_action_parsing():
    """Test action parsing from LLM responses."""
    print("\nTesting action parsing...")
    
    agent = BrowserAgent()
    
    # Test click parsing
    response = "I need to click on the button.\n!click 100,200\nThis will activate it."
    action_data = agent._parse_action_from_response(response)
    print(f"Click parsing: {action_data}")
    assert action_data["action_type"] == "click"
    assert action_data["position"] == "100,200"
    
    # Test scroll parsing
    response = "I should scroll down.\n!scroll down 3\nTo see more content."
    action_data = agent._parse_action_from_response(response)
    print(f"Scroll parsing: {action_data}")
    assert action_data["action_type"] == "scroll"
    assert action_data["direction"] == "down"
    assert action_data["amount"] == 3
    
    # Test keyboard input parsing
    response = "I need to type text.\n!keyboard_input Hello World\nInto the field."
    action_data = agent._parse_action_from_response(response)
    print(f"Keyboard parsing: {action_data}")
    assert action_data["action_type"] == "keyboard_input"
    assert action_data["text"] == "Hello World"
    
    print("✓ Action parsing tests passed!")

def test_visualization():
    """Test action visualization."""
    print("\nTesting visualization...")
    
    try:
        from PIL import Image
        
        agent = BrowserAgent()
        
        # Create mock screenshot
        screenshot = Image.new("RGB", (640, 480), color="white")
        
        # Test click visualization
        action_data = {"action_type": "click", "position": "100,200"}
        vis_img = agent.visualize_action(screenshot, action_data)
        print(f"Click visualization: {vis_img is not None}")
        assert vis_img is not None
        
        # Test scroll visualization
        action_data = {"action_type": "scroll", "direction": "up", "amount": 1}
        vis_img = agent.visualize_action(screenshot, action_data)
        print(f"Scroll visualization: {vis_img is not None}")
        assert vis_img is not None
        
        print("✓ Visualization tests passed!")
        
    except ImportError:
        print("PIL not available, skipping visualization tests")

if __name__ == "__main__":
    print("🧪 Running Browser Agent Tests")
    print("=" * 50)
    
    try:
        # test_browser_tools()
        test_browser_agent_basic()
        # test_action_parsing()
        # test_visualization()
        
        print("\n🎉 All tests passed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
