"""
Abstract Operator base class for environment-agnostic GUI automation.

An Operator encapsulates all environment-specific logic:
- Screenshot capture
- Action execution
- Screen dimensions
- Action space declaration (for VLM prompt generation)
"""

from abc import ABC, abstractmethod
from typing import Tuple

from PIL import Image

from .actions.definitions import AnyAction


class Operator(ABC):
    """Abstract base class for GUI automation operators."""

    @abstractmethod
    def screenshot(self) -> Image.Image:
        """Capture a screenshot from the environment."""
        ...

    @abstractmethod
    def execute(self, action: AnyAction) -> bool:
        """Execute an action in the environment. Returns True on success."""
        ...

    @property
    @abstractmethod
    def screen_dimensions(self) -> Tuple[int, int]:
        """Return (width, height) of the screen."""
        ...

    @staticmethod
    @abstractmethod
    def action_space() -> str:
        """Return action space description for inclusion in VLM system prompt."""
        ...
