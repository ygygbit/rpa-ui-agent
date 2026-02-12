"""Action definitions and parsers for UI automation."""

from .definitions import (
    Action, ActionType, AnyAction, action_to_dict,
    ClickAction, DoubleClickAction, RightClickAction,
    DragAction, ScrollAction, HoverAction,
    TypeAction, KeyAction, HotkeyAction,
    FocusWindowAction, WaitAction, ScreenshotAction,
    DoneAction, FailAction
)
from .parser import ActionParser

__all__ = [
    "Action", "ActionType", "AnyAction", "action_to_dict",
    "ClickAction", "DoubleClickAction", "RightClickAction",
    "DragAction", "ScrollAction", "HoverAction",
    "TypeAction", "KeyAction", "HotkeyAction",
    "FocusWindowAction", "WaitAction", "ScreenshotAction",
    "DoneAction", "FailAction",
    "ActionParser"
]
