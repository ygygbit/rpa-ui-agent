"""
Remote Controller for sandbox API.

Provides the same interface as UIController but executes actions
via HTTP calls to the sandbox server running in Docker.
"""

import httpx
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List


@dataclass
class MousePosition:
    """Current mouse position."""
    x: int
    y: int


class RemoteController:
    """
    Controller that sends commands to sandbox API.

    Has the same interface as UIController but uses HTTP instead of
    Windows native APIs.
    """

    def __init__(self, base_url: str = "http://localhost:8000"):
        """
        Initialize remote controller.

        Args:
            base_url: Base URL of the sandbox API server.
        """
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=30.0)
        self._screen_size: Optional[Tuple[int, int]] = None

    def _get(self, endpoint: str, **kwargs) -> httpx.Response:
        """Make GET request to sandbox API."""
        return self._client.get(f"{self.base_url}{endpoint}", **kwargs)

    def _post(self, endpoint: str, **kwargs) -> httpx.Response:
        """Make POST request to sandbox API."""
        return self._client.post(f"{self.base_url}{endpoint}", **kwargs)

    @property
    def screen_size(self) -> Tuple[int, int]:
        """Get screen dimensions from sandbox."""
        if self._screen_size is None:
            response = self._get("/status")
            if response.status_code == 200:
                data = response.json()
                self._screen_size = (
                    data["screen_size"]["width"],
                    data["screen_size"]["height"]
                )
            else:
                self._screen_size = (1920, 1080)  # Default
        return self._screen_size

    @property
    def mouse_position(self) -> MousePosition:
        """Get current mouse position from sandbox."""
        response = self._get("/status")
        if response.status_code == 200:
            data = response.json()
            return MousePosition(
                x=data["cursor_position"]["x"],
                y=data["cursor_position"]["y"]
            )
        return MousePosition(x=0, y=0)

    # ==================== Mouse Operations ====================

    def move_to(self, x: int, y: int, duration: float = 0.0) -> None:
        """Move mouse to absolute position."""
        self._post("/mouse/move", params={"x": x, "y": y, "duration": duration})

    def move_relative(self, dx: int, dy: int, duration: float = 0.0) -> None:
        """Move mouse relative to current position."""
        current = self.mouse_position
        new_x = current.x + dx
        new_y = current.y + dy
        # Clamp to screen boundaries
        screen_w, screen_h = self.screen_size
        new_x = max(0, min(new_x, screen_w - 1))
        new_y = max(0, min(new_y, screen_h - 1))
        self.move_to(new_x, new_y, duration)

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left") -> None:
        """Click at position (or current position if not specified)."""
        if x is not None and y is not None:
            self._post("/mouse/click", json={"x": x, "y": y, "button": button})
        else:
            # Click at current position
            pos = self.mouse_position
            self._post("/mouse/click", json={"x": pos.x, "y": pos.y, "button": button})

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Double-click at position."""
        if x is not None and y is not None:
            self.click(x, y)
            time.sleep(0.05)
            self.click(x, y)
        else:
            self.click()
            time.sleep(0.05)
            self.click()

    def right_click(self, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Right-click at position."""
        self.click(x, y, button="right")

    def drag(
        self,
        start_x: int,
        start_y: int,
        end_x: int,
        end_y: int,
        duration: float = 0.5
    ) -> None:
        """Drag from start to end position."""
        # Move to start and click
        self.move_to(start_x, start_y)
        time.sleep(0.1)
        self.click(start_x, start_y)
        time.sleep(0.1)
        # Move to end (simulates drag - true drag needs mousedown/mouseup)
        self.move_to(end_x, end_y, duration)

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None) -> None:
        """Scroll at position."""
        if x is not None and y is not None:
            self.move_to(x, y)
        # Use Page Up/Down as workaround
        if clicks > 0:
            for _ in range(clicks):
                self.press_key("pageup")
        else:
            for _ in range(abs(clicks)):
                self.press_key("pagedown")

    # ==================== Keyboard Operations ====================

    def write(self, text: str) -> None:
        """Type text string."""
        self._post("/keyboard/type", json={"text": text})

    def press_key(self, key: str) -> None:
        """Press a single key."""
        self._post("/keyboard/hotkey", json={"keys": [key]})

    def key_combo(self, keys: List[str]) -> None:
        """Press a key combination."""
        self.hotkey(*keys)

    def hotkey(self, *keys: str) -> None:
        """Press key combination."""
        self._post("/keyboard/hotkey", json={"keys": list(keys)})

    # ==================== Utility ====================

    def focus_window_by_title(self, title: str) -> bool:
        """Focus window by title - limited support via sandbox."""
        # Could add an endpoint for this on the sandbox side
        return False

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
