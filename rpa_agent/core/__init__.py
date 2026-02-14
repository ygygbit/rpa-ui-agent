"""Core modules for UI automation and screen capture."""

from .screen import ScreenCapture
from .controller import UIController, BlockedKeyError
from .window import WindowManager
from .cursor_overlay import CursorOverlay, start_cursor_overlay, stop_cursor_overlay
from .action_notifier import ActionNotifier, start_action_notifier, stop_action_notifier

__all__ = [
    "ScreenCapture",
    "UIController",
    "WindowManager",
    "BlockedKeyError",
    "CursorOverlay",
    "start_cursor_overlay",
    "stop_cursor_overlay",
    "ActionNotifier",
    "start_action_notifier",
    "stop_action_notifier",
]
