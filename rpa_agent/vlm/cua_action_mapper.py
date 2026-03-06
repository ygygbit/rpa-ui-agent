"""
Maps GPT-5.4 CUA computer_call actions to our Action dataclasses.

CUA actions come as objects with .type and action-specific attributes.
This module converts them to the same AnyAction types used by the
existing _execute_action() machinery.
"""

from typing import Any, List

from ..actions.definitions import (
    ActionType,
    AnyAction,
    ClickAction,
    DoubleClickAction,
    RightClickAction,
    DragAction,
    ScrollAction,
    HoverAction,
    TypeAction,
    KeyAction,
    HotkeyAction,
    WaitAction,
    ScreenshotAction,
)


# CUA key names that need remapping to our key names
_KEY_MAP = {
    "SPACE": "space",
    "ENTER": "enter",
    "RETURN": "enter",
    "TAB": "tab",
    "ESCAPE": "escape",
    "ESC": "escape",
    "BACKSPACE": "backspace",
    "DELETE": "delete",
    "UP": "up",
    "DOWN": "down",
    "LEFT": "left",
    "RIGHT": "right",
    "HOME": "home",
    "END": "end",
    "PAGEUP": "pageup",
    "PAGEDOWN": "pagedown",
    "CMD": "win",
    "COMMAND": "win",
    "META": "win",
    "CTRL": "ctrl",
    "CONTROL": "ctrl",
    "ALT": "alt",
    "SHIFT": "shift",
}


def _normalize_key(key: str) -> str:
    """Normalize a CUA key name to our key naming convention."""
    return _KEY_MAP.get(key.upper(), key.lower())


def map_cua_action(action: Any) -> AnyAction:
    """
    Map a single CUA action object to our Action dataclass.

    Args:
        action: A CUA action object with .type and action-specific attrs.

    Returns:
        An AnyAction instance ready for _execute_action().
    """
    action_type = action.type

    if action_type == "click":
        button = getattr(action, "button", "left")
        x = int(getattr(action, "x", 0))
        y = int(getattr(action, "y", 0))
        if button == "right":
            return RightClickAction(
                x=x, y=y,
                element_description=f"CUA click (right) at ({x}, {y})",
                action_type=ActionType.RIGHT_CLICK,
            )
        return ClickAction(
            x=x, y=y,
            element_description=f"CUA click at ({x}, {y})",
            action_type=ActionType.CLICK,
        )

    elif action_type == "double_click":
        x = int(getattr(action, "x", 0))
        y = int(getattr(action, "y", 0))
        return DoubleClickAction(
            x=x, y=y,
            element_description=f"CUA double_click at ({x}, {y})",
            action_type=ActionType.DOUBLE_CLICK,
        )

    elif action_type == "scroll":
        x = int(getattr(action, "x", 0))
        y = int(getattr(action, "y", 0))
        scroll_x = getattr(action, "scroll_x", 0) or 0
        scroll_y = getattr(action, "scroll_y", 0) or 0

        # Determine direction and amount from scroll deltas
        if abs(scroll_y) >= abs(scroll_x):
            direction = "up" if scroll_y < 0 else "down"
            amount = max(1, abs(scroll_y) // 120) if scroll_y != 0 else 3
        else:
            direction = "left" if scroll_x < 0 else "right"
            amount = max(1, abs(scroll_x) // 120) if scroll_x != 0 else 3

        return ScrollAction(
            direction=direction,
            amount=amount,
            x=x, y=y,
            reasoning=f"CUA scroll {direction} by {amount}",
            action_type=ActionType.SCROLL,
        )

    elif action_type == "type":
        text = getattr(action, "text", "")
        return TypeAction(
            text=text,
            reasoning=f"CUA type: {text[:50]}",
            action_type=ActionType.TYPE,
        )

    elif action_type == "keypress":
        keys = getattr(action, "keys", [])
        normalized = [_normalize_key(k) for k in keys]
        if len(normalized) == 1:
            return KeyAction(
                key=normalized[0],
                reasoning=f"CUA keypress: {normalized[0]}",
                action_type=ActionType.PRESS_KEY,
            )
        return HotkeyAction(
            keys=normalized,
            reasoning=f"CUA hotkey: {'+'.join(normalized)}",
            action_type=ActionType.HOTKEY,
        )

    elif action_type == "drag":
        path = getattr(action, "path", [])
        if len(path) >= 2:
            start = path[0]
            end = path[-1]
            return DragAction(
                start_x=int(getattr(start, "x", start.get("x", 0)) if isinstance(start, dict) else start.x),
                start_y=int(getattr(start, "y", start.get("y", 0)) if isinstance(start, dict) else start.y),
                end_x=int(getattr(end, "x", end.get("x", 0)) if isinstance(end, dict) else end.x),
                end_y=int(getattr(end, "y", end.get("y", 0)) if isinstance(end, dict) else end.y),
                reasoning="CUA drag",
                action_type=ActionType.DRAG,
            )
        # Fallback: no path or single point
        return WaitAction(
            seconds=0.1,
            reason="CUA drag with insufficient path points",
            action_type=ActionType.WAIT,
        )

    elif action_type == "move":
        x = int(getattr(action, "x", 0))
        y = int(getattr(action, "y", 0))
        return HoverAction(
            x=x, y=y,
            element_description=f"CUA move to ({x}, {y})",
            action_type=ActionType.HOVER,
        )

    elif action_type == "wait":
        return WaitAction(
            seconds=2.0,
            reason="CUA wait",
            action_type=ActionType.WAIT,
        )

    elif action_type == "screenshot":
        return ScreenshotAction(
            reasoning="CUA screenshot request",
            action_type=ActionType.SCREENSHOT,
        )

    else:
        raise ValueError(f"Unsupported CUA action type: {action_type}")


def map_cua_actions(actions: List[Any]) -> List[AnyAction]:
    """Map a list of CUA actions to our Action dataclasses."""
    return [map_cua_action(a) for a in actions]
