"""Core modules for UI automation and screen capture."""

from .screen import ScreenCapture
from .controller import UIController, BlockedKeyError
from .window import WindowManager

__all__ = ["ScreenCapture", "UIController", "WindowManager", "BlockedKeyError"]
