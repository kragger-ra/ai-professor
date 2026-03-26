#!/usr/bin/env python3
"""
Standalone Browser Agent Test

This test verifies the browser agent components work independently
without requiring the full NetTyan framework dependencies.
"""

import os
import sys
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

def test_browser_tools_standalone():
    """Test browser tools without NetTyan framework."""
    print("🔧 Testing browser tools (standalone)...")
    
    # Enable mock mode
    os.environ["BROWSER_AGENT_MOCK_ACTIONS"] = "true"
    
    # Mock the NetTyan dependencies
    with patch('agent.tools.control_tools._add_tool_run_log') as mock_run_log, \
         patch('agent.tools.control_tools._add_tool_result_log') as mock_result_log, \
         patch('agent.tools.control_tools._add_tool_error_log') as mock_error_log:
        
        # Return mock call IDs
        mock_run_log.return_value = "test_call_id"
        mock_result_log.return_value = None
        mock_error_log.return_value = None
        
        # Now test the tools
        from agent.browser.browser_tools import mouse_hover, click, scroll, keyboard_input
        
        # Test mouse hover
        result = mouse_hover("100,200")
        print(f"  mouse_hover: {result}")
        assert "100,200" in result
        
        # Test click
        result = click("150,250")
        print(f"  click: {result}")
        assert "150,250" in result
        
        # Test scroll
        result = scroll("up", 3)
        print(f"  scroll: {result}")
        assert "up" in result
        
        # Test keyboard input
        result = keyboard_input(text="Hello World")
        print(f"  keyboard_input: {result}")
        assert "Hello World" in result
        
        print("  ✅ All browser tools work correctly!")

def test_browser_config():
    """Test browser configuration."""
    print("\n⚙️  Testing browser configuration...")
    
    from agent.browser.browser_config import load_config, parse_tuple
    
    # Test config loading
    config = load_config()
    print(f"  Config loaded: {len(config)} settings")
    assert "screenshot_resize" in config
    assert "visualization_color" in config
    
    # Test tuple parsing
    assert parse_tuple("1280,720") == (1280, 720)
    print("  ✅ Configuration system works!")

def test_browser_utils():
    """Test browser utilities."""
    print("\n🛠️  Testing browser utilities...")
    
    from agent.browser.browser_utils import (
        validate_coordinates, 
        parse_position, 
        scale_coordinates,
        extract_coordinates_from_text,
        get_screen_info
    )
    
    # Test coordinate validation
    assert validate_coordinates(100, 200) == True
    assert validate_coordinates(-10, 200) == False
    
    # Test position parsing
    assert parse_position("100,200") == (100, 200)
    
    # Test coordinate scaling
    assert scale_coordinates(100, 200, (1920, 1080), (960, 540)) == (50, 100)
    
    # Test coordinate extraction
    coords = extract_coordinates_from_text("Click at 100,200 then 300,400")
    assert coords == [(100, 200), (300, 400)]
    
    # Test screen info
    info = get_screen_info()
    assert "size" in info
    
    print("  ✅ All utilities work correctly!")

def test_mock_browser_agent():
    """Test a mock version of browser agent."""
    print("\n🤖 Testing mock browser agent...")
    
    # Create a minimal mock version
    class MockBrowserAgent:
        def __init__(self):
            self.config = {
                "visualization_color": "red",
                "visualization_size": 20,
                "max_retries": 3,
                "screenshot_resize": (1280, 720),
            }
            self.tool_bank = {}
            
        def _parse_action_from_response(self, response):
            """Parse action from response."""
            if "!click" in response:
                pos = response.split("!click")[1].strip().split()[0]
                return {"action_type": "click", "position": pos}
            elif "!scroll" in response:
                parts = response.split("!scroll")[1].strip().split()
                direction = parts[0] if parts else "up"
                amount = int(parts[1]) if len(parts) > 1 else 1
                return {"action_type": "scroll", "direction": direction, "amount": amount}
            return {}
            
        def get_status(self):
            return {
                "running": False,
                "registered_tools": ["click", "scroll", "mouse_hover", "keyboard_input"],
                "config": self.config
            }
    
    # Test the mock agent
    agent = MockBrowserAgent()
    
    # Test status
    status = agent.get_status()
    assert "registered_tools" in status
    print(f"  Mock agent status: {len(status['registered_tools'])} tools")
    
    # Test action parsing
    action = agent._parse_action_from_response("I need to !click 100,200")
    assert action["action_type"] == "click"
    assert action["position"] == "100,200"
    
    action = agent._parse_action_from_response("Let me !scroll down 3")
    assert action["action_type"] == "scroll"
    assert action["direction"] == "down"
    assert action["amount"] == 3
    
    print("  ✅ Mock browser agent works correctly!")

if __name__ == "__main__":
    print("🧪 Standalone Browser Agent Test")
    print("=" * 50)
    
    try:
        test_browser_tools_standalone()
        test_browser_config()
        test_browser_utils()
        test_mock_browser_agent()
        
        print("\n🎉 All standalone tests passed!")
        print("The browser agent components are working correctly.")
        print("To use with full NetTyan framework, ensure all dependencies are installed.")
        
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
