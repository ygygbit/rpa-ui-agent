"""
RPA UI Agent - Vision-Language Model based GUI Automation

A multimodal AI agent that can understand screenshots and perform
UI automation tasks through natural language instructions.
"""

__version__ = "0.1.0"

from .agent import GUIAgent, AgentConfig, AgentState, AgentStep, ActionResult

__all__ = [
    "GUIAgent",
    "AgentConfig",
    "AgentState",
    "AgentStep",
    "ActionResult",
]
