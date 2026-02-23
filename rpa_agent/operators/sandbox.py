"""Sandbox operator — executes actions via HTTP API to Docker sandbox."""

import time
import random
from typing import Tuple

from PIL import Image

from ..operator import Operator
from ..actions.definitions import (
    AnyAction, ClickAction, DoubleClickAction, RightClickAction,
    DragAction, ScrollAction, HoverAction,
    MoveMouseAction, MoveToAction, MoveRelativeAction,
    ClickNowAction, DoubleClickNowAction, RightClickNowAction,
    TypeAction, KeyAction, HotkeyAction,
    FocusWindowAction, WaitAction, ScreenshotAction,
    DoneAction, FailAction,
)
from ..core.remote_screen import RemoteScreenCapture
from ..core.remote_controller import RemoteController


class SandboxOperator(Operator):
    """Operator for Docker sandbox environment via HTTP API."""

    def __init__(self, sandbox_url: str = "http://localhost:8000"):
        self._screen = RemoteScreenCapture(sandbox_url)
        self._controller = RemoteController(sandbox_url)

    def screenshot(self) -> Image.Image:
        return self._screen.capture()

    @property
    def screen_dimensions(self) -> Tuple[int, int]:
        return self._screen.screen_size

    def execute(self, action: AnyAction) -> bool:
        """Execute action via sandbox HTTP API. Returns True on success."""
        if isinstance(action, ClickAction):
            self._controller.click(action.x, action.y)

        elif isinstance(action, DoubleClickAction):
            self._controller.double_click(action.x, action.y)

        elif isinstance(action, RightClickAction):
            self._controller.right_click(action.x, action.y)

        elif isinstance(action, MoveMouseAction):
            self._execute_move_mouse(action)

        elif isinstance(action, MoveToAction):
            self._controller.move_to(action.x, action.y, duration=0.3)

        elif isinstance(action, MoveRelativeAction):
            self._controller.move_relative(action.dx, action.dy, duration=0.2)

        elif isinstance(action, ClickNowAction):
            self._controller.click()

        elif isinstance(action, DoubleClickNowAction):
            self._controller.double_click()

        elif isinstance(action, RightClickNowAction):
            self._controller.right_click()

        elif isinstance(action, DragAction):
            self._controller.drag(
                action.start_x, action.start_y,
                action.end_x, action.end_y
            )

        elif isinstance(action, ScrollAction):
            clicks = action.amount
            if action.direction == "down":
                clicks = -clicks
            self._controller.scroll(clicks, action.x, action.y)

        elif isinstance(action, HoverAction):
            self._controller.move_to(action.x, action.y)

        elif isinstance(action, TypeAction):
            self._controller.write(action.text)
            if action.press_enter:
                self._controller.press_key("enter")

        elif isinstance(action, KeyAction):
            if action.modifiers:
                keys = action.modifiers + [action.key]
                self._controller.key_combo(keys)
            else:
                self._controller.press_key(action.key)

        elif isinstance(action, HotkeyAction):
            self._controller.hotkey(*action.keys)

        elif isinstance(action, WaitAction):
            time.sleep(action.seconds)

        elif isinstance(action, (ScreenshotAction, DoneAction, FailAction,
                                 FocusWindowAction)):
            pass  # Handled by agent, not operator

        return True

    def _execute_move_mouse(self, action: MoveMouseAction) -> None:
        distance_map = {
            "small": (20, 50),
            "medium": (80, 150),
            "large": (200, 400),
        }
        direction_map = {
            "up": (0, -1), "down": (0, 1),
            "left": (-1, 0), "right": (1, 0),
            "up-left": (-0.707, -0.707), "up-right": (0.707, -0.707),
            "down-left": (-0.707, 0.707), "down-right": (0.707, 0.707),
        }

        direction = action.direction.lower()
        distance_range = distance_map.get(action.distance.lower(), distance_map["medium"])
        dx, dy = direction_map.get(direction, (0, 0))
        distance = random.randint(*distance_range)
        dx = int(dx * distance)
        dy = int(dy * distance)

        current = self._controller.mouse_position
        target_x = max(5, min(current.x + dx, self.screen_dimensions[0] - 5))
        target_y = max(5, min(current.y + dy, self.screen_dimensions[1] - 5))
        self._controller.move_to(target_x, target_y, duration=0.15)

    @staticmethod
    def action_space() -> str:
        return """### Direct Click (PREFERRED for interacting with visible elements)
- **click**: Click at specific coordinates
  `{"action": "click", "x": 500, "y": 300, "element": "Search button"}`

- **double_click**: Double-click at coordinates
  `{"action": "double_click", "x": 500, "y": 300, "element": "File icon"}`

- **right_click**: Right-click at coordinates
  `{"action": "right_click", "x": 500, "y": 300, "element": "Desktop"}`

### Mouse Movement (use when you need to position cursor first)
- **move_relative**: Move cursor by pixel offset from current position
  `{"action": "move_relative", "dx": 150, "dy": -80}`

- **click_now**: Click at current cursor position
  `{"action": "click_now", "element": "Button name"}`

### Typing
- **type**: Type text (types into the currently focused element)
  `{"action": "type", "text": "Hello World", "press_enter": false}`

### Keyboard
- **press_key**: Press a single key
  `{"action": "press_key", "key": "enter"}`

- **hotkey**: Press key combination
  `{"action": "hotkey", "keys": ["ctrl", "a"]}`

### Scrolling
- **scroll**: Scroll at position
  `{"action": "scroll", "direction": "down", "amount": 3}`

### Control
- **wait**: Pause execution
  `{"action": "wait", "seconds": 2}`

- **done**: Task completed successfully
  `{"action": "done", "summary": "Description of what was accomplished"}`

- **fail**: Cannot complete task
  `{"action": "fail", "error": "Reason why task cannot be completed"}`"""
