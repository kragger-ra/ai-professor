"""
BASE AGENT

Abstract base class for all agent implementations
"""

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Optional

from data_flow.ctx_handler import CtxHandler
from data_schema.ctx_structures import CtxSwarmType


class BaseAgent(ABC):
    """Abstract base class for agent implementations"""

    def __init__(
        self, ctx_swarm: CtxSwarmType, ctx_handler: Optional[CtxHandler] = None
    ):
        """Initialize the agent with context swarm"""
        self.initialized = False
        self.ctx_swarm = ctx_swarm
        self.running = False

    @abstractmethod
    def run(self):
        """Main agent loop - must be implemented by subclasses"""
        pass

    def stop(self):
        """Stop the agent"""
        self.running = False

    def is_running(self):
        """Check if agent is running"""
        return self.running
