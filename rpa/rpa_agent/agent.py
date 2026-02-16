"""
Main GUI Agent orchestration.

The Agent class ties together:
- Screen capture
- VLM analysis
- Action parsing
- UI control execution
- Feedback loop and self-correction
"""

import base64
import io
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .core import ScreenCapture, UIController, WindowManager
from .actions import ActionParser, ActionType, AnyAction, action_to_dict
from .actions.definitions import (
    ClickAction, DoubleClickAction, RightClickAction,
    DragAction, ScrollAction, HoverAction,
    MoveMouseAction, MoveToAction, MoveRelativeAction, ClickNowAction, DoubleClickNowAction, RightClickNowAction,
    TypeAction, KeyAction, HotkeyAction,
    FocusWindowAction, WaitAction, ScreenshotAction,
    DoneAction, FailAction
)
from .vlm import VLMClient, VLMConfig


class AgentState(str, Enum):
    """Agent execution states."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"


def _sanitize_text(text: str) -> str:
    """Sanitize text for Windows console output by replacing problematic Unicode."""
    # Replace common Unicode arrows and symbols with ASCII equivalents
    replacements = {
        '\u2193': 'v',  # ↓
        '\u2191': '^',  # ↑
        '\u2190': '<',  # ←
        '\u2192': '>',  # →
        '\u2713': '[x]',  # ✓
        '\u2717': '[!]',  # ✗
        '\u2022': '*',  # •
        '\u2026': '...',  # …
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    # Encode to cp1252, replacing any remaining problematic chars
    return text.encode('cp1252', errors='replace').decode('cp1252')


@dataclass
class ActionResult:
    """Result of executing an action."""
    success: bool
    action: AnyAction
    error: Optional[str] = None
    screenshot_path: Optional[Path] = None


@dataclass
class AgentConfig:
    """Configuration for the GUI agent."""
    # VLM settings
    vlm_config: VLMConfig = field(default_factory=VLMConfig)

    # Execution settings
    max_steps: int = 50
    step_delay: float = 0.5  # Delay between steps
    screenshot_scale: float = 1.0  # Screenshot scaling (1.0 = no scaling for accurate coordinates)
    screenshot_quality: int = 50  # JPEG quality (1-100, lower = faster)
    save_screenshots: bool = True
    screenshot_dir: Path = field(default_factory=lambda: Path("./screenshots"))

    # Safety settings
    confirm_actions: bool = False  # Ask before executing
    dry_run: bool = False  # Don't actually execute actions

    # Visual feedback
    show_cursor_overlay: bool = True  # Show visual cursor indicator on screen
    show_action_notifier: bool = True  # Show action notification UI

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0

    # Sandbox mode - operate inside Docker sandbox via HTTP API
    sandbox_mode: bool = False
    sandbox_url: str = "http://localhost:8000"


@dataclass
class AgentStep:
    """Record of a single agent step."""
    step_number: int
    timestamp: datetime
    screenshot_path: Optional[Path]
    vlm_response: str
    action: Optional[AnyAction]
    action_result: Optional[ActionResult]
    reasoning: str


class GUIAgent:
    """
    Vision-Language Model based GUI automation agent.

    The agent follows an observe-think-act loop:
    1. Capture screenshot (observe)
    2. Send to VLM for analysis (think)
    3. Parse and execute action (act)
    4. Verify result and continue
    """

    def __init__(
        self,
        config: Optional[AgentConfig] = None,
        console: Optional[Console] = None
    ):
        """
        Initialize the GUI agent.

        Args:
            config: Agent configuration
            console: Rich console for output
        """
        self.config = config or AgentConfig()
        self.console = console or Console()

        # Initialize components based on mode
        if self.config.sandbox_mode:
            # Sandbox mode: use remote screen/controller via HTTP API
            from .core.remote_screen import RemoteScreenCapture
            from .core.remote_controller import RemoteController
            self.screen = RemoteScreenCapture(self.config.sandbox_url)
            self.controller = RemoteController(self.config.sandbox_url)
            self.window_manager = None  # Not supported in sandbox mode
            # Disable overlays in sandbox mode (they would show on Windows, not sandbox)
            self.config.show_cursor_overlay = False
            self.config.show_action_notifier = False
        else:
            # Local Windows mode
            self.screen = ScreenCapture()
            self.controller = UIController()
            self.window_manager = WindowManager()

        self.vlm = VLMClient(self.config.vlm_config)
        self.parser = ActionParser()

        # Visual feedback overlays
        self._cursor_overlay = None
        self._action_notifier = None
        self._hotkey_monitor = None

        # State
        self.state = AgentState.IDLE
        self.steps: List[AgentStep] = []
        self.current_task: Optional[str] = None
        self._conversation_history: List[Dict[str, Any]] = []
        self._recent_actions: List[str] = []  # Track recent actions for stuck detection

        # Ensure screenshot directory exists
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _on_stop_hotkey(self) -> None:
        """Callback when stop hotkey (Ctrl+Alt) is pressed."""
        self.console.print("\n[yellow]Stop hotkey detected (Ctrl+Alt). Stopping agent...[/]")
        self.state = AgentState.FAILED

    def _capture_screenshot(self, step_number: int) -> Tuple[str, Path, Dict[str, int]]:
        """Capture screenshot and return base64, path, and screen info."""
        # Pause overlays to prevent them from appearing in screenshot
        if self._cursor_overlay:
            self._cursor_overlay.pause()
        if self._action_notifier:
            self._action_notifier.pause()

        time.sleep(0.05)  # Brief wait to ensure screen is clear

        # Capture screenshot once
        img = self.screen.capture(scale=self.config.screenshot_scale)

        # Resume overlays immediately after capture
        if self._cursor_overlay:
            self._cursor_overlay.resume()
        if self._action_notifier:
            self._action_notifier.resume()

        # Get screen info
        screen_info = {
            "width": img.width,
            "height": img.height
        }

        # Save screenshot as PNG (compressed)
        screenshot_path = None
        if self.config.save_screenshots:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = self.config.screenshot_dir / f"step_{step_number:03d}_{timestamp}.png"
            img.save(screenshot_path, format="PNG", optimize=True)

        # Encode to base64 PNG for VLM (more reliable than JPEG)
        buffer = io.BytesIO()
        img.save(buffer, format="PNG", optimize=True)
        base64_img = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

        return base64_img, screenshot_path, screen_info

    def _execute_action(self, action: AnyAction) -> ActionResult:
        """Execute a parsed action."""
        try:
            if self.config.dry_run:
                self.console.print(f"[yellow][DRY RUN] Would execute: {action.action_type.value}[/]")
                return ActionResult(success=True, action=action)

            if isinstance(action, ClickAction):
                self.controller.click(action.x, action.y)

            elif isinstance(action, DoubleClickAction):
                self.controller.double_click(action.x, action.y)

            elif isinstance(action, RightClickAction):
                self.controller.right_click(action.x, action.y)

            elif isinstance(action, MoveMouseAction):
                self._execute_move_mouse(action)

            elif isinstance(action, MoveToAction):
                # Move directly to coordinates with smooth animation
                self.controller.move_to(action.x, action.y, duration=0.3)

            elif isinstance(action, MoveRelativeAction):
                # Move relative to current position (dx, dy pixels)
                self.controller.move_relative(action.dx, action.dy, duration=0.2)

            elif isinstance(action, ClickNowAction):
                # Click at current position (no coordinates)
                self.controller.click()

            elif isinstance(action, DoubleClickNowAction):
                # Double-click at current position
                self.controller.double_click()

            elif isinstance(action, RightClickNowAction):
                # Right-click at current position
                self.controller.right_click()

            elif isinstance(action, DragAction):
                self.controller.drag(
                    action.start_x, action.start_y,
                    action.end_x, action.end_y
                )

            elif isinstance(action, ScrollAction):
                clicks = action.amount
                if action.direction == "down":
                    clicks = -clicks
                elif action.direction in ("left", "right"):
                    # Horizontal scroll not directly supported, use scroll
                    pass
                self.controller.scroll(clicks, action.x, action.y)

            elif isinstance(action, HoverAction):
                self.controller.move_to(action.x, action.y)

            elif isinstance(action, TypeAction):
                self.controller.write(action.text)
                if action.press_enter:
                    self.controller.press_key("enter")

            elif isinstance(action, KeyAction):
                if action.modifiers:
                    keys = action.modifiers + [action.key]
                    self.controller.key_combo(keys)
                else:
                    self.controller.press_key(action.key)

            elif isinstance(action, HotkeyAction):
                self.controller.hotkey(*action.keys)

            elif isinstance(action, FocusWindowAction):
                if self.window_manager is None:
                    return ActionResult(
                        success=False,
                        action=action,
                        error="Window focus not supported in sandbox mode"
                    )
                success = self.window_manager.focus_window_by_title(action.window_title)
                if not success:
                    return ActionResult(
                        success=False,
                        action=action,
                        error=f"Window '{action.window_title}' not found"
                    )

            elif isinstance(action, WaitAction):
                time.sleep(action.seconds)

            elif isinstance(action, ScreenshotAction):
                # Just capture a new screenshot (will be done in next iteration)
                pass

            elif isinstance(action, DoneAction):
                self.state = AgentState.COMPLETED

            elif isinstance(action, FailAction):
                self.state = AgentState.FAILED
                return ActionResult(
                    success=False,
                    action=action,
                    error=action.error
                )

            return ActionResult(success=True, action=action)

        except Exception as e:
            return ActionResult(
                success=False,
                action=action,
                error=str(e)
            )

    def _execute_move_mouse(self, action: MoveMouseAction) -> None:
        """Execute a directional mouse movement (human-like navigation)."""
        import random

        # Distance mappings (in pixels)
        distance_map = {
            "small": (20, 50),
            "medium": (80, 150),
            "large": (200, 400),
        }

        # Direction vectors (dx, dy)
        direction_map = {
            "up": (0, -1),
            "down": (0, 1),
            "left": (-1, 0),
            "right": (1, 0),
            "up-left": (-0.707, -0.707),
            "up-right": (0.707, -0.707),
            "down-left": (-0.707, 0.707),
            "down-right": (0.707, 0.707),
        }

        direction = action.direction.lower()
        distance_range = distance_map.get(action.distance.lower(), distance_map["medium"])

        if direction not in direction_map:
            raise ValueError(f"Unknown direction: {direction}")

        dx, dy = direction_map[direction]

        # Add some randomness for human-like movement
        distance = random.randint(*distance_range)
        dx = int(dx * distance)
        dy = int(dy * distance)

        # Get current position and calculate target
        current = self.controller.mouse_position
        target_x = current.x + dx
        target_y = current.y + dy

        # Clamp to screen boundaries
        target_x = max(5, min(target_x, self.controller.screen_size[0] - 5))
        target_y = max(5, min(target_y, self.controller.screen_size[1] - 5))

        # Move to the new position with smooth animation
        self.controller.move_to(target_x, target_y, duration=0.15)

    def _get_action_detail(self, action: AnyAction) -> str:
        """Build detail string for action notification."""
        action_type = action.action_type.value

        if hasattr(action, 'target_element') and action.target_element:
            return action.target_element
        elif hasattr(action, 'element') and action.element:
            return action.element
        elif hasattr(action, 'text') and action.text:
            text = action.text[:30] + "..." if len(action.text) > 30 else action.text
            return f'"{text}"'
        elif hasattr(action, 'key') and action.key:
            return action.key
        elif hasattr(action, 'keys') and action.keys:
            return " + ".join(action.keys)
        elif hasattr(action, 'direction') and action.direction:
            distance = getattr(action, 'distance', '')
            return f"{action.direction} ({distance})"
        elif hasattr(action, 'reason') and action.reason:
            return action.reason
        elif hasattr(action, 'summary') and action.summary:
            return action.summary
        elif hasattr(action, 'error') and action.error:
            return action.error
        else:
            return ""

    def _build_feedback_message(self, result: ActionResult) -> str:
        """Build feedback message for the VLM based on action result."""
        if result.success:
            return f"Action {result.action.action_type.value} executed successfully."
        else:
            return f"Action {result.action.action_type.value} failed: {result.error}"

    def _action_signature(self, action: AnyAction) -> str:
        """Create a string signature of an action for comparison."""
        parts = [action.action_type.value]
        if hasattr(action, 'x') and hasattr(action, 'y'):
            parts.append(f"({action.x},{action.y})")
        if hasattr(action, 'dx') and hasattr(action, 'dy'):
            parts.append(f"(dx={action.dx},dy={action.dy})")
        if hasattr(action, 'text'):
            parts.append(f"text={action.text[:30]}")
        if hasattr(action, 'key') and hasattr(action, 'key'):
            parts.append(f"key={action.key}")
        if hasattr(action, 'keys') and isinstance(action.keys, list):
            parts.append(f"keys={'+'.join(action.keys)}")
        return "|".join(parts)

    def _check_stuck_loop(self, action: AnyAction) -> Tuple[Optional[str], str]:
        """
        Check if agent is stuck in a loop of repeating identical or similar actions.

        Returns:
            Tuple of (warning_message, severity) where severity is one of:
            - "none": no issue detected
            - "warn": soft warning (2 identical actions)
            - "block": block execution and force re-query (3-4 identical actions)
            - "override": auto-execute keyboard fallback (5+ identical actions)
        """
        sig = self._action_signature(action)
        self._recent_actions.append(sig)

        # Keep only last 10 actions for better pattern detection
        if len(self._recent_actions) > 10:
            self._recent_actions = self._recent_actions[-10:]

        # Count consecutive identical actions from the end
        consecutive_count = 1
        for i in range(len(self._recent_actions) - 2, -1, -1):
            if self._recent_actions[i] == sig:
                consecutive_count += 1
            else:
                break

        # Smart override: if agent typed text recently and is now stuck clicking,
        # override earlier (at 3 repeats instead of 5) with Enter key
        if consecutive_count >= 3 and self._should_submit_after_type(action):
            return (
                "OVERRIDE: You typed text into a field and then kept clicking instead of submitting. "
                "The system is pressing Enter to submit. "
                "After this, observe the screen and proceed with the next step of the task.",
                "override"
            )

        # 5+ identical: force override with keyboard fallback
        if consecutive_count >= 5:
            return (
                "CRITICAL: You have repeated the EXACT SAME action 5+ times. "
                "The system is now OVERRIDING your action with a keyboard shortcut. "
                "After this override, you MUST analyze the screen fresh and try something completely new.",
                "override"
            )

        # 3-4 identical: block and force re-query
        if consecutive_count >= 3:
            return (
                "BLOCKED: You have repeated the EXACT SAME action 3+ times in a row. "
                "Your action was NOT executed. The screen has NOT changed. "
                "You MUST choose a COMPLETELY DIFFERENT action type. "
                "FORBIDDEN: Do NOT use the same action type with the same target. "
                "REQUIRED alternatives: "
                "(1) Use press_key with 'enter' to confirm what's on screen, "
                "(2) Use hotkey like ['ctrl','l'] to reset focus, "
                "(3) Click on a DIFFERENT element at DIFFERENT coordinates (at least 100px away), "
                "(4) Use 'type' to enter text directly if you were trying to navigate. "
                "Pick ONE of these alternatives NOW.",
                "block"
            )

        # 2 identical: soft warning
        if consecutive_count >= 2:
            return (
                "NOTE: You performed the same action twice. If it didn't produce the expected result, "
                "try a different approach on your next action.",
                "warn"
            )

        # Check for oscillation (alternating between 2 actions) - strict ABAB
        if len(self._recent_actions) >= 4:
            last_4 = self._recent_actions[-4:]
            if last_4[0] == last_4[2] and last_4[1] == last_4[3] and last_4[0] != last_4[1]:
                return (
                    "WARNING: You are oscillating between two actions without making progress. "
                    "STOP and try a completely different strategy to accomplish this task.",
                    "block"
                )

        # Early detection: 3+ clicks on similar area without any type action
        # This catches the "keep clicking search bar instead of typing" pattern
        if len(self._recent_actions) >= 3 and isinstance(action, (ClickAction, DoubleClickAction)):
            coords = self._extract_recent_coords(3)
            if coords and len(coords) >= 3:
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                x_spread = max(xs) - min(xs)
                y_spread = max(ys) - min(ys)
                if x_spread <= 80 and y_spread <= 40:
                    # 3+ clicks in the same area — check if any were type actions
                    recent_sigs = self._recent_actions[-3:]
                    has_type = any(s.startswith("type|") for s in recent_sigs)
                    if not has_type:
                        return (
                            "BLOCKED: You have clicked the SAME area 3 times without typing. "
                            "The text field IS focused after the first click — repeated clicks are unnecessary. "
                            "You MUST now use 'type' to enter text. "
                            "Your next action MUST be: "
                            '{{"action": "type", "text": "<your text here>", "press_enter": false}}',
                            "block"
                        )

        # Check for coordinate-based stuck loop: agent interacting with the same
        # area (within 30px) across the last 6+ actions regardless of action type
        if len(self._recent_actions) >= 6:
            coords = self._extract_recent_coords(6)
            if coords and len(coords) >= 5:
                # Check if all coordinates cluster within a 60px box
                xs = [c[0] for c in coords]
                ys = [c[1] for c in coords]
                x_spread = max(xs) - min(xs)
                y_spread = max(ys) - min(ys)
                if x_spread <= 60 and y_spread <= 60:
                    # Check if any recent action was a 'type' action
                    recent_sigs = self._recent_actions[-6:]
                    has_type = any(s.startswith("type|") for s in recent_sigs)
                    if not has_type:
                        # All clicks, no typing — the agent needs to TYPE, not press Enter
                        return (
                            "BLOCKED: You have been CLICKING the SAME area "
                            f"(within ~{max(x_spread, y_spread)}px) for the last {len(coords)} actions "
                            "but you have NEVER TYPED any text. "
                            "Clicking a text field FOCUSES it — it does NOT require repeated clicks. "
                            "The field IS already focused from your first click. "
                            "You MUST now use the 'type' action to enter text into this field. "
                            "Do NOT click again. Your next action MUST be: "
                            '{{"action": "type", "text": "<your text here>", "press_enter": false}}',
                            "block"
                        )
                    else:
                        return (
                            "BLOCKED: You have been interacting with the SAME screen area "
                            f"(within ~{max(x_spread, y_spread)}px) for the last {len(coords)} actions "
                            "using different action types, but nothing is changing. "
                            "This area is NOT responding to your actions. "
                            "You MUST try a completely different approach: "
                            "(1) Press Enter to submit/confirm, "
                            "(2) Use Ctrl+L to reset browser focus, "
                            "(3) Press Escape to dismiss any popups, "
                            "(4) Click somewhere COMPLETELY DIFFERENT (at least 200px away). "
                            "Do NOT interact with this area again.",
                            "override"
                        )

        return (None, "none")

    def _should_submit_after_type(self, current_action: AnyAction) -> bool:
        """
        Check if the agent recently typed text and is now stuck clicking/interacting
        with the same area, suggesting it should press Enter to submit instead.

        Returns True if:
        - Current action is a click-type action (click, click_now, etc.)
        - A recent prior action was a 'type' action (within the last 5 actions)
        """
        # Only trigger for click-type actions
        if not isinstance(current_action, (ClickAction, ClickNowAction, DoubleClickAction)):
            return False

        # Look backwards through recent actions for a 'type' action
        for sig in reversed(self._recent_actions[:-1]):  # Exclude current
            if sig.startswith("type|"):
                return True
            # Stop looking once we've checked back far enough
            if sig.startswith("click|") or sig.startswith("click_now|"):
                continue  # Skip past clicks to find the type
            # If we hit a non-click, non-type action, stop searching
            break

        return False

    def _extract_recent_coords(self, n: int) -> List[Tuple[int, int]]:
        """
        Extract (x, y) coordinates from the last n action signatures.

        Parses coordinates from signatures like 'click|(180,75)' or
        actions with explicit x,y. Skips actions without coordinates
        (like press_key, type, hotkey).

        Returns list of (x, y) tuples found.
        """
        coords = []
        for sig in self._recent_actions[-n:]:
            # Parse coordinate from action signature format: "action|(x,y)"
            if "|(" in sig:
                try:
                    coord_part = sig.split("|(")[1].rstrip(")")
                    # Could be like "180,75)" or "180,75)|..."
                    coord_part = coord_part.split(")")[0]
                    parts = coord_part.split(",")
                    if len(parts) >= 2:
                        x, y = int(parts[0]), int(parts[1])
                        coords.append((x, y))
                except (ValueError, IndexError):
                    pass
        return coords

    def _display_step(self, step: AgentStep) -> None:
        """Display step information in console."""
        # Create step panel
        table = Table(show_header=False, box=None)
        table.add_column("Key", style="cyan")
        table.add_column("Value")

        table.add_row("Step", str(step.step_number))
        table.add_row("Time", step.timestamp.strftime("%H:%M:%S"))

        if step.action:
            table.add_row("Action", step.action.action_type.value)
            if hasattr(step.action, 'x') and hasattr(step.action, 'y'):
                table.add_row("Coordinates", f"({step.action.x}, {step.action.y})")
            if hasattr(step.action, 'dx') and hasattr(step.action, 'dy'):
                table.add_row("Offset", f"(dx={step.action.dx}, dy={step.action.dy})")
            if hasattr(step.action, 'direction') and hasattr(step.action, 'distance'):
                table.add_row("Movement", f"{step.action.direction} ({step.action.distance})")
            if hasattr(step.action, 'target_element') and step.action.target_element:
                table.add_row("Target", _sanitize_text(step.action.target_element[:40]))
            if hasattr(step.action, 'element_description') and step.action.element_description:
                table.add_row("Element", _sanitize_text(step.action.element_description[:40]))
            if hasattr(step.action, 'text'):
                table.add_row("Text", _sanitize_text(step.action.text[:50]))

        if step.action_result:
            status = "[green]Success[/]" if step.action_result.success else f"[red]Failed: {step.action_result.error}[/]"
            table.add_row("Result", status)

        if step.reasoning:
            reasoning = _sanitize_text(step.reasoning[:100] + "..." if len(step.reasoning) > 100 else step.reasoning)
            table.add_row("Reasoning", reasoning)

        self.console.print(Panel(table, title=f"Step {step.step_number}"))

    def run(
        self,
        task: str,
        on_step: Optional[Callable[[AgentStep], None]] = None,
        on_action: Optional[Callable[[AnyAction], bool]] = None
    ) -> List[AgentStep]:
        """
        Run the agent to complete a task.

        Args:
            task: Natural language task description
            on_step: Callback after each step (for monitoring)
            on_action: Callback before action execution (return False to skip)

        Returns:
            List of all steps taken
        """
        self.state = AgentState.RUNNING
        self.current_task = task
        self.steps = []
        self._conversation_history = []
        self._recent_actions = []

        # Start hotkey monitor for stopping agent (Ctrl+Alt)
        from .core.hotkey import HotkeyMonitor
        self._hotkey_monitor = HotkeyMonitor(self._on_stop_hotkey)
        self._hotkey_monitor.start()
        self.console.print("[dim]Press Ctrl+Alt to stop the agent[/]")

        # Start cursor overlay for visual feedback
        if self.config.show_cursor_overlay:
            from .core.cursor_overlay import CursorOverlay
            self._cursor_overlay = CursorOverlay(color="red", size=50, line_width=4)
            self._cursor_overlay.start()

        # Start action notifier for showing what agent is doing
        if self.config.show_action_notifier:
            from .core.action_notifier import ActionNotifier
            self._action_notifier = ActionNotifier()
            self._action_notifier.start()
            self._action_notifier.show_action("thinking", f"Task: {task[:50]}...")

        self.console.print(Panel(f"[bold]Task:[/] {task}", title="GUI Agent Started"))

        step_number = 0
        retry_count = 0

        while self.state == AgentState.RUNNING and step_number < self.config.max_steps:
            step_number += 1
            timestamp = datetime.now()

            try:
                # Show "thinking" in notifier
                if self._action_notifier:
                    self._action_notifier.show_thinking(step_number)

                # 1. Capture screenshot
                self.console.print(f"\n[dim]Step {step_number}: Capturing screenshot...[/]")
                base64_img, screenshot_path, screen_info = self._capture_screenshot(step_number)

                # 2. Analyze with VLM
                self.console.print("[dim]Analyzing screenshot...[/]")
                # Pass as tuple (base64_data, media_type) for PNG
                screenshot_data = (base64_img, "image/png")
                vlm_response = self.vlm.analyze_screenshot(
                    screenshot=screenshot_data,
                    task=task,
                    screen_info=screen_info,
                    history=self._conversation_history if self._conversation_history else None
                )

                # 3. Parse action
                action, parse_msg = self.parser.parse(vlm_response.text)

                # Create step record
                step = AgentStep(
                    step_number=step_number,
                    timestamp=timestamp,
                    screenshot_path=screenshot_path,
                    vlm_response=vlm_response.text,
                    action=action,
                    action_result=None,
                    reasoning=action.reasoning if action else parse_msg
                )

                if action is None:
                    self.console.print(f"[yellow]Could not parse action: {parse_msg}[/]")
                    retry_count += 1
                    if retry_count >= self.config.max_retries:
                        self.state = AgentState.FAILED
                        step.action_result = ActionResult(
                            success=False,
                            action=FailAction(action_type=ActionType.FAIL, error="Max retries exceeded"),
                            error="Max retries exceeded"
                        )
                    self.steps.append(step)
                    continue

                # Reset retry count on successful parse
                retry_count = 0

                # 3.5. Check for stuck loop
                stuck_warning, stuck_severity = self._check_stuck_loop(action)

                if stuck_severity == "override":
                    # 5+ identical actions: force a keyboard fallback
                    self.console.print(f"[red bold]OVERRIDE: Forcing keyboard fallback (Enter key) after 5+ identical actions[/]")
                    override_action = KeyAction(action_type=ActionType.PRESS_KEY, key="enter")
                    result = self._execute_action(override_action)
                    step.action = override_action
                    step.action_result = result
                    step.reasoning = "SYSTEM OVERRIDE: Forced Enter key after 5+ repeated identical actions"
                    # Inject override notice into conversation
                    self._conversation_history.append({
                        "role": "assistant",
                        "content": vlm_response.text
                    })
                    self._conversation_history.append({
                        "role": "user",
                        "content": stuck_warning
                    })
                    # Reset stuck counter so VLM gets a fresh chance after override
                    self._recent_actions.clear()
                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)
                    time.sleep(self.config.step_delay)
                    continue

                if stuck_severity == "block":
                    # 3-4 identical actions: block execution, don't execute the action
                    self.console.print(f"[red]BLOCKED: Action not executed (3+ identical repeats). Forcing re-analysis.[/]")
                    step.action_result = ActionResult(
                        success=False,
                        action=action,
                        error="BLOCKED: Identical action repeated 3+ times"
                    )
                    step.reasoning = "SYSTEM BLOCKED: Action not executed due to stuck loop"
                    # Add VLM response and block message to history
                    self._conversation_history.append({
                        "role": "assistant",
                        "content": vlm_response.text
                    })
                    self._conversation_history.append({
                        "role": "user",
                        "content": stuck_warning
                    })
                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)
                    time.sleep(self.config.step_delay)
                    continue

                if stuck_severity == "warn" and stuck_warning:
                    self.console.print(f"[yellow]{stuck_warning[:80]}...[/]")
                    self._conversation_history.append({
                        "role": "user",
                        "content": stuck_warning
                    })

                # 4. Confirm action if needed
                if on_action and not on_action(action):
                    self.console.print("[yellow]Action skipped by callback[/]")
                    continue

                if self.config.confirm_actions:
                    self.console.print(f"[yellow]Confirm action: {action.action_type.value}?[/]")
                    # In a real implementation, this would wait for user input

                # 5. Show action in notifier and execute
                if self._action_notifier:
                    # Build detail string based on action type
                    detail = self._get_action_detail(action)
                    self._action_notifier.show_step(step_number, action.action_type.value, detail)

                self.console.print(f"[dim]Executing: {action.action_type.value}[/]")
                result = self._execute_action(action)
                step.action_result = result

                # 6. Update conversation history
                self._conversation_history.append({
                    "role": "assistant",
                    "content": vlm_response.text
                })

                if not result.success:
                    self._conversation_history.append({
                        "role": "user",
                        "content": self._build_feedback_message(result)
                    })

                # 7. Display and record step
                self._display_step(step)
                self.steps.append(step)

                if on_step:
                    on_step(step)

                # 8. Delay before next step
                if self.state == AgentState.RUNNING:
                    time.sleep(self.config.step_delay)

            except Exception as e:
                self.console.print(f"[red]Error in step {step_number}: {e}[/]")
                self.state = AgentState.FAILED
                break

        # Stop overlays and hotkey monitor
        if self._hotkey_monitor:
            self._hotkey_monitor.stop()
            self._hotkey_monitor = None
        if self._cursor_overlay:
            self._cursor_overlay.stop()
            self._cursor_overlay = None
        if self._action_notifier:
            self._action_notifier.stop()
            self._action_notifier = None

        # Final status
        if self.state == AgentState.COMPLETED:
            self.console.print(Panel("[green]Task completed successfully![/]", title="Done"))
        elif self.state == AgentState.FAILED:
            self.console.print(Panel("[red]Task failed[/]", title="Failed"))
        else:
            self.console.print(Panel("[yellow]Max steps reached[/]", title="Stopped"))

        return self.steps

    def run_with_plan(
        self,
        task: str,
        on_step: Optional[Callable[[AgentStep], None]] = None
    ) -> List[AgentStep]:
        """
        Run the agent with initial planning phase.

        Creates a plan first, then executes it step by step.

        Args:
            task: Task description
            on_step: Step callback

        Returns:
            List of steps
        """
        self.console.print("[dim]Creating execution plan...[/]")

        # Capture initial screenshot
        base64_img, screenshot_path, screen_info = self._capture_screenshot(0)

        # Get plan from VLM
        plan_response = self.vlm.plan_task(
            screenshot=screenshot_path or base64_img,
            task=task,
            screen_info=screen_info
        )

        self.console.print(Panel(plan_response.text[:500], title="Execution Plan"))

        # Run the task
        return self.run(task, on_step)

    def ground_element(self, element_description: str) -> Optional[Tuple[int, int]]:
        """
        Find coordinates of a specific element.

        Args:
            element_description: Description of element to find

        Returns:
            (x, y) coordinates or None if not found
        """
        base64_img, screenshot_path, screen_info = self._capture_screenshot(0)

        response = self.vlm.ground_element(
            screenshot=screenshot_path or base64_img,
            element_description=element_description,
            screen_info=screen_info
        )

        try:
            data = json.loads(response.text)
            if data.get("found"):
                return (data["x"], data["y"])
        except json.JSONDecodeError:
            pass

        return None

    def stop(self) -> None:
        """Stop the agent execution."""
        self.state = AgentState.PAUSED

    def get_history(self) -> List[Dict[str, Any]]:
        """Get step history as dictionaries."""
        return [
            {
                "step": s.step_number,
                "timestamp": s.timestamp.isoformat(),
                "action": action_to_dict(s.action) if s.action else None,
                "success": s.action_result.success if s.action_result else None,
                "reasoning": s.reasoning
            }
            for s in self.steps
        ]

    def save_history(self, path: Path) -> None:
        """Save step history to JSON file."""
        with open(path, "w") as f:
            json.dump(self.get_history(), f, indent=2)
