"""
Action notification UI that shows users what the AI agent is doing.
Displays in a small overlay window that doesn't appear in screenshots.
"""

import ctypes
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Optional

# Windows API constants for click-through window
user32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080  # Don't show in taskbar


def make_window_click_through(hwnd: int) -> None:
    """Make a window click-through using Windows API."""
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW)


class ActionNotifier:
    """
    Displays a notification overlay showing what the AI agent is doing.
    The window is click-through and can be hidden during screenshots.
    """

    # Action icons (emoji-style text icons)
    ACTION_ICONS = {
        "click": "🖱️",
        "click_now": "🖱️",
        "double_click": "🖱️🖱️",
        "double_click_now": "🖱️🖱️",
        "right_click": "🖱️",
        "right_click_now": "🖱️",
        "move_mouse": "↗️",
        "type": "⌨️",
        "press_key": "⌨️",
        "hotkey": "⌨️",
        "scroll": "📜",
        "wait": "⏳",
        "done": "✅",
        "fail": "❌",
        "thinking": "🤖",
        "screenshot": "📸",
    }

    def __init__(
        self,
        width: int = 350,
        height: int = 80,
        position: str = "top-right",  # top-left, top-right, bottom-left, bottom-right
        bg_color: str = "#1a1a2e",
        text_color: str = "#ffffff",
        accent_color: str = "#4a9eff",
    ):
        """
        Initialize action notifier.

        Args:
            width: Window width
            height: Window height
            position: Screen position (top-left, top-right, bottom-left, bottom-right)
            bg_color: Background color
            text_color: Text color
            accent_color: Accent color for icons/highlights
        """
        self.width = width
        self.height = height
        self.position = position
        self.bg_color = bg_color
        self.text_color = text_color
        self.accent_color = accent_color

        self._running = False
        self._paused = False
        self._thread: Optional[threading.Thread] = None
        self._root: Optional[tk.Tk] = None
        self._action_label: Optional[tk.Label] = None
        self._detail_label: Optional[tk.Label] = None
        self._icon_label: Optional[tk.Label] = None
        self._current_action = ""
        self._current_detail = ""
        self._update_pending = False

    def _get_screen_position(self) -> tuple:
        """Calculate window position based on screen size and position setting."""
        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)

        margin = 20

        if self.position == "top-left":
            x = margin
            y = margin
        elif self.position == "top-right":
            x = screen_width - self.width - margin
            y = margin
        elif self.position == "bottom-left":
            x = margin
            y = screen_height - self.height - margin - 50  # Account for taskbar
        elif self.position == "bottom-right":
            x = screen_width - self.width - margin
            y = screen_height - self.height - margin - 50
        else:
            x = screen_width - self.width - margin
            y = margin

        return x, y

    def _create_window(self):
        """Create the notification window."""
        self._root = tk.Tk()
        self._root.title("")

        # Window setup
        self._root.attributes("-topmost", True)
        self._root.attributes("-alpha", 0.92)  # Slight transparency
        self._root.overrideredirect(True)  # No window decorations

        # Position window
        x, y = self._get_screen_position()
        self._root.geometry(f"{self.width}x{self.height}+{x}+{y}")

        # Create main frame with rounded corner effect (using padding)
        main_frame = tk.Frame(self._root, bg=self.bg_color)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # Left side - AI icon
        icon_frame = tk.Frame(main_frame, bg=self.bg_color, width=60)
        icon_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(10, 5))
        icon_frame.pack_propagate(False)

        # Robot icon
        try:
            icon_font = tkfont.Font(family="Segoe UI Emoji", size=28)
        except:
            icon_font = tkfont.Font(size=28)

        self._icon_label = tk.Label(
            icon_frame,
            text="🤖",
            font=icon_font,
            bg=self.bg_color,
            fg=self.accent_color
        )
        self._icon_label.pack(expand=True)

        # Right side - Action text
        text_frame = tk.Frame(main_frame, bg=self.bg_color)
        text_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 15), pady=10)

        # Action label (main text)
        try:
            action_font = tkfont.Font(family="Segoe UI", size=11, weight="bold")
        except:
            action_font = tkfont.Font(size=11, weight="bold")

        self._action_label = tk.Label(
            text_frame,
            text="AI Assistant Ready",
            font=action_font,
            bg=self.bg_color,
            fg=self.text_color,
            anchor="w",
            justify=tk.LEFT
        )
        self._action_label.pack(fill=tk.X, pady=(5, 2))

        # Detail label (secondary text)
        try:
            detail_font = tkfont.Font(family="Segoe UI", size=9)
        except:
            detail_font = tkfont.Font(size=9)

        self._detail_label = tk.Label(
            text_frame,
            text="Waiting for task...",
            font=detail_font,
            bg=self.bg_color,
            fg="#aaaaaa",
            anchor="w",
            justify=tk.LEFT,
            wraplength=self.width - 100
        )
        self._detail_label.pack(fill=tk.X)

        # Make window click-through
        self._root.update()
        hwnd = ctypes.windll.user32.GetAncestor(self._root.winfo_id(), 2)
        make_window_click_through(hwnd)

    def _update_display(self):
        """Update the display with current action."""
        if not self._running or not self._root:
            return

        if self._paused:
            self._root.withdraw()
        else:
            self._root.deiconify()
            if self._update_pending:
                if self._action_label:
                    self._action_label.config(text=self._current_action)
                if self._detail_label:
                    self._detail_label.config(text=self._current_detail)
                self._update_pending = False

        if self._running:
            self._root.after(50, self._update_display)

    def _run_mainloop(self):
        """Run the tkinter main loop."""
        self._create_window()
        self._update_display()
        self._root.mainloop()

    def start(self) -> None:
        """Start the notifier."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_mainloop, daemon=True)
        self._thread.start()
        time.sleep(0.2)  # Wait for window to initialize

    def stop(self) -> None:
        """Stop the notifier."""
        self._running = False
        if self._root:
            try:
                self._root.quit()
                self._root.destroy()
            except Exception:
                pass
            self._root = None
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def pause(self) -> None:
        """Hide the notifier temporarily (for screenshots)."""
        self._paused = True
        time.sleep(0.1)

    def resume(self) -> None:
        """Show the notifier again."""
        self._paused = False

    def show_action(self, action_type: str, detail: str = "") -> None:
        """
        Update the display to show current action.

        Args:
            action_type: Type of action (click, move_mouse, type, etc.)
            detail: Additional detail about the action
        """
        icon = self.ACTION_ICONS.get(action_type.lower(), "🤖")

        # Format action text
        action_texts = {
            "click": "Clicking",
            "click_now": "Clicking",
            "double_click": "Double-clicking",
            "double_click_now": "Double-clicking",
            "right_click": "Right-clicking",
            "right_click_now": "Right-clicking",
            "move_mouse": "Moving mouse",
            "type": "Typing",
            "press_key": "Pressing key",
            "hotkey": "Pressing hotkey",
            "scroll": "Scrolling",
            "wait": "Waiting",
            "done": "Task completed!",
            "fail": "Task failed",
            "thinking": "Analyzing screen...",
            "screenshot": "Capturing screenshot",
        }

        action_text = action_texts.get(action_type.lower(), f"Executing: {action_type}")

        self._current_action = f"{icon}  {action_text}"
        self._current_detail = detail if detail else ""
        self._update_pending = True

        # Update icon
        if self._icon_label and self._running:
            try:
                # Use action-specific icon or default robot
                display_icon = icon if action_type.lower() != "thinking" else "🤖"
            except:
                pass

    def show_thinking(self, step: int = 0) -> None:
        """Show that the AI is thinking/analyzing."""
        self.show_action("thinking", f"Step {step}: Processing screenshot...")

    def show_step(self, step: int, action_type: str, target: str = "") -> None:
        """Show current step information."""
        detail = f"Step {step}"
        if target:
            detail += f": {target}"
        self.show_action(action_type, detail)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()


# Global notifier instance
_notifier: Optional[ActionNotifier] = None


def start_action_notifier(**kwargs) -> ActionNotifier:
    """Start the global action notifier."""
    global _notifier
    if _notifier:
        _notifier.stop()
    _notifier = ActionNotifier(**kwargs)
    _notifier.start()
    return _notifier


def stop_action_notifier() -> None:
    """Stop the global action notifier."""
    global _notifier
    if _notifier:
        _notifier.stop()
        _notifier = None


def get_action_notifier() -> Optional[ActionNotifier]:
    """Get the current action notifier instance."""
    return _notifier
