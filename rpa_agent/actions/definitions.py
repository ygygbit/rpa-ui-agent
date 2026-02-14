"""
Action definitions for UI automation.

Defines structured action types that can be parsed from VLM output
and executed by the UI controller.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Union


class ActionType(str, Enum):
    """Types of UI actions the agent can perform."""

    # Mouse movement actions (human-like)
    MOVE_MOUSE = "move_mouse"  # Move mouse in a direction
    CLICK_NOW = "click_now"  # Click at current mouse position
    DOUBLE_CLICK_NOW = "double_click_now"  # Double-click at current position
    RIGHT_CLICK_NOW = "right_click_now"  # Right-click at current position

    # Legacy coordinate-based actions (deprecated but kept for compatibility)
    CLICK = "click"
    DOUBLE_CLICK = "double_click"
    RIGHT_CLICK = "right_click"
    DRAG = "drag"
    SCROLL = "scroll"
    HOVER = "hover"

    # Keyboard actions
    TYPE = "type"
    PRESS_KEY = "press_key"
    HOTKEY = "hotkey"

    # Window actions
    FOCUS_WINDOW = "focus_window"
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    CLOSE_WINDOW = "close_window"

    # Control actions
    WAIT = "wait"
    SCREENSHOT = "screenshot"
    DONE = "done"
    FAIL = "fail"


@dataclass
class Action:
    """Base action class."""
    action_type: ActionType
    reasoning: str = ""
    confidence: float = 1.0


@dataclass
class ClickAction(Action):
    """Click action at coordinates or element."""
    x: int = 0
    y: int = 0
    element_description: str = ""

    def __post_init__(self):
        self.action_type = ActionType.CLICK


@dataclass
class DoubleClickAction(Action):
    """Double click action."""
    x: int = 0
    y: int = 0
    element_description: str = ""

    def __post_init__(self):
        self.action_type = ActionType.DOUBLE_CLICK


@dataclass
class RightClickAction(Action):
    """Right click action."""
    x: int = 0
    y: int = 0
    element_description: str = ""

    def __post_init__(self):
        self.action_type = ActionType.RIGHT_CLICK


@dataclass
class DragAction(Action):
    """Drag from one point to another."""
    start_x: int = 0
    start_y: int = 0
    end_x: int = 0
    end_y: int = 0

    def __post_init__(self):
        self.action_type = ActionType.DRAG


@dataclass
class ScrollAction(Action):
    """Scroll action."""
    direction: str = "down"  # up, down, left, right
    amount: int = 3  # scroll clicks
    x: Optional[int] = None
    y: Optional[int] = None

    def __post_init__(self):
        self.action_type = ActionType.SCROLL


@dataclass
class HoverAction(Action):
    """Hover at coordinates."""
    x: int = 0
    y: int = 0
    element_description: str = ""

    def __post_init__(self):
        self.action_type = ActionType.HOVER


@dataclass
class MoveMouseAction(Action):
    """Move mouse in a direction toward a target element (human-like navigation)."""
    direction: str = ""  # up, down, left, right, up-left, up-right, down-left, down-right
    distance: str = "medium"  # small (10-30px), medium (50-100px), large (150-300px)
    target_element: str = ""  # Description of what we're moving toward

    def __post_init__(self):
        self.action_type = ActionType.MOVE_MOUSE


@dataclass
class ClickNowAction(Action):
    """Click at the current mouse position."""
    element_description: str = ""  # What element is being clicked

    def __post_init__(self):
        self.action_type = ActionType.CLICK_NOW


@dataclass
class DoubleClickNowAction(Action):
    """Double-click at the current mouse position."""
    element_description: str = ""

    def __post_init__(self):
        self.action_type = ActionType.DOUBLE_CLICK_NOW


@dataclass
class RightClickNowAction(Action):
    """Right-click at the current mouse position."""
    element_description: str = ""

    def __post_init__(self):
        self.action_type = ActionType.RIGHT_CLICK_NOW


@dataclass
class TypeAction(Action):
    """Type text action."""
    text: str = ""
    press_enter: bool = False

    def __post_init__(self):
        self.action_type = ActionType.TYPE


@dataclass
class KeyAction(Action):
    """Press key action."""
    key: str = ""
    modifiers: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.action_type = ActionType.PRESS_KEY


@dataclass
class HotkeyAction(Action):
    """Hotkey combination action."""
    keys: List[str] = field(default_factory=list)

    def __post_init__(self):
        self.action_type = ActionType.HOTKEY


@dataclass
class FocusWindowAction(Action):
    """Focus a window by title."""
    window_title: str = ""

    def __post_init__(self):
        self.action_type = ActionType.FOCUS_WINDOW


@dataclass
class WaitAction(Action):
    """Wait for specified seconds."""
    seconds: float = 1.0
    reason: str = ""

    def __post_init__(self):
        self.action_type = ActionType.WAIT


@dataclass
class ScreenshotAction(Action):
    """Take a screenshot for analysis."""
    region: Optional[tuple] = None

    def __post_init__(self):
        self.action_type = ActionType.SCREENSHOT


@dataclass
class DoneAction(Action):
    """Task completed successfully."""
    summary: str = ""

    def __post_init__(self):
        self.action_type = ActionType.DONE


@dataclass
class FailAction(Action):
    """Task failed."""
    error: str = ""

    def __post_init__(self):
        self.action_type = ActionType.FAIL


# Type alias for any action
AnyAction = Union[
    ClickAction, DoubleClickAction, RightClickAction, DragAction,
    ScrollAction, HoverAction, MoveMouseAction, ClickNowAction,
    DoubleClickNowAction, RightClickNowAction, TypeAction, KeyAction,
    HotkeyAction, FocusWindowAction, WaitAction, ScreenshotAction,
    DoneAction, FailAction
]


def action_to_dict(action: AnyAction) -> Dict[str, Any]:
    """Convert action to dictionary for logging/serialization."""
    result = {
        "action_type": action.action_type.value,
        "reasoning": action.reasoning,
        "confidence": action.confidence,
    }

    # Add action-specific fields
    if isinstance(action, (ClickAction, DoubleClickAction, RightClickAction, HoverAction)):
        result.update({"x": action.x, "y": action.y, "element": action.element_description})
    elif isinstance(action, MoveMouseAction):
        result.update({
            "direction": action.direction, "distance": action.distance,
            "target_element": action.target_element
        })
    elif isinstance(action, (ClickNowAction, DoubleClickNowAction, RightClickNowAction)):
        result.update({"element": action.element_description})
    elif isinstance(action, DragAction):
        result.update({
            "start_x": action.start_x, "start_y": action.start_y,
            "end_x": action.end_x, "end_y": action.end_y
        })
    elif isinstance(action, ScrollAction):
        result.update({
            "direction": action.direction, "amount": action.amount,
            "x": action.x, "y": action.y
        })
    elif isinstance(action, TypeAction):
        result.update({"text": action.text, "press_enter": action.press_enter})
    elif isinstance(action, KeyAction):
        result.update({"key": action.key, "modifiers": action.modifiers})
    elif isinstance(action, HotkeyAction):
        result.update({"keys": action.keys})
    elif isinstance(action, FocusWindowAction):
        result.update({"window_title": action.window_title})
    elif isinstance(action, WaitAction):
        result.update({"seconds": action.seconds, "reason": action.reason})
    elif isinstance(action, DoneAction):
        result.update({"summary": action.summary})
    elif isinstance(action, FailAction):
        result.update({"error": action.error})

    return result
