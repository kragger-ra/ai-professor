import os
import sys
import time
from datetime import datetime, timedelta
from multiprocessing import Manager

import pytest

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_flow.ctx_handler import CtxHandler
from data_schema.structure_templates import CTX_SWARM_EMPTY

def create_test_event(user="test_user", msg="test message", event_type="chat", 
                     date=None, timestamp=None):
    """Helper function to create test events"""
    if date is None:
        date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if timestamp is None:
        timestamp = time.time_ns()
        
    return {
        "type": event_type,
        "user": user,
        "msg": msg,
        "date": date,
        "processing_timestamp": timestamp
    }

@pytest.fixture
def ctx_handler():
    """Fixture to create a CtxHandler instance with test context"""
    manager = Manager()
    ctx_swarm = CTX_SWARM_EMPTY.copy()
    ctx_swarm["ctx_chat"] = manager.list()
    ctx = CtxHandler(ctx_swarm)
    return ctx

def test_add_event_basic(ctx_handler):
    """Test basic event addition"""
    event = create_test_event()
    assert ctx_handler.add_event(event)
    assert len(ctx_handler.ctx_swarm["ctx_chat"]) == 1
    assert ctx_handler.ctx_swarm["ctx_chat"][0]["repeating"] == 1

def test_add_event_missing_fields(ctx_handler):
    """Test event validation with missing fields"""
    event = {"user": "test_user", "msg": "test"}  # Missing required fields
    assert not ctx_handler.add_event(event)
    assert len(ctx_handler.ctx_swarm["ctx_chat"]) == 0

def test_similar_events_combining(ctx_handler):
    """Test that similar events are combined with repeating counter"""
    base_time = datetime.now()
    
    # Add first event
    event1 = create_test_event(date=base_time.strftime('%Y-%m-%d %H:%M:%S'))
    ctx_handler.add_event(event1)
    
    # Add similar event within 30 seconds
    event2 = create_test_event(date=(base_time + timedelta(seconds=5)).strftime('%Y-%m-%d %H:%M:%S'))
    ctx_handler.add_event(event2)
    
    assert len(ctx_handler.ctx_swarm["ctx_chat"]) == 1
    assert ctx_handler.ctx_swarm["ctx_chat"][0]["repeating"] == 2

def test_different_events_not_combining(ctx_handler):
    """Test that different events are not combined"""
    # Add events with different types
    event1 = create_test_event(event_type="chat")
    event2 = create_test_event(event_type="death")
    
    ctx_handler.add_event(event1)
    ctx_handler.add_event(event2)
    
    assert len(ctx_handler.ctx_swarm["ctx_chat"]) == 2

def test_events_time_window(ctx_handler):
    """Test that events outside 30-second window are not combined"""
    base_time = datetime.now()
    
    # Add first event
    event1 = create_test_event(date=base_time.strftime('%Y-%m-%d %H:%M:%S'))
    ctx_handler.add_event(event1)
    
    # Add similar event after 31 seconds
    event2 = create_test_event(date=(base_time + timedelta(seconds=31)).strftime('%Y-%m-%d %H:%M:%S'))
    ctx_handler.add_event(event2)
    
    assert len(ctx_handler.ctx_swarm["ctx_chat"]) == 2

def test_update_event(ctx_handler):
    """Test event updating by processing_timestamp"""
    event = create_test_event()
    ctx_handler.add_event(event)
    
    # Update the event
    timestamp = event["processing_timestamp"]
    updated_event = create_test_event(msg="updated message")
    updated_event["processing_timestamp"] = timestamp
    
    assert ctx_handler.update_event(updated_event)
    assert ctx_handler.ctx_swarm["ctx_chat"][0]["msg"] == "updated message"

def test_update_nonexistent_event(ctx_handler):
    """Test updating an event that doesn't exist"""
    event = create_test_event()
    assert not ctx_handler.update_event(event)

if __name__ == "__main__":
    pytest.main([__file__])
