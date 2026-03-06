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
import math
import os
import signal
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFont
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
from .vlm import VLMClient, VLMConfig, CUAClient, CUAConfig, OpenAIVLMClient, OpenAIVLMConfig
from .vlm.prompts import SystemPrompts
from .vlm.cua_action_mapper import map_cua_actions
from .operator import Operator


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
    # Provider: "anthropic" (default VLM), "openai" (GPT-5.4 CUA), or "openai-vlm" (GPT-5.4 as VLM)
    provider: str = "anthropic"

    # VLM settings (used when provider="anthropic")
    vlm_config: VLMConfig = field(default_factory=VLMConfig)

    # CUA settings (used when provider="openai")
    cua_config: Optional[CUAConfig] = None

    # OpenAI VLM settings (used when provider="openai-vlm")
    openai_vlm_config: Optional[OpenAIVLMConfig] = None

    # Execution settings
    max_steps: int = 50
    step_delay: float = 0.0  # Delay between steps (0 = VLM call provides natural pacing)
    screenshot_scale: float = 1.0  # Screenshot scaling (1.0 = no scaling for accurate coordinates)
    screenshot_quality: int = 50  # JPEG quality (1-100, lower = faster)
    save_screenshots: bool = True
    screenshot_dir: Path = field(default_factory=lambda: Path("./screenshots"))

    # VLM image settings
    vlm_image_format: str = "jpeg"  # "png" or "jpeg" — format sent to VLM (jpeg is 76% smaller)
    vlm_image_quality: int = 2  # JPEG quality for VLM images (1-100, lower = fewer tokens)
    vlm_max_edge: int = 1568  # Max long edge for VLM images (Anthropic API limit)
    vlm_max_pixels: int = 1_192_464  # Max total pixels (Anthropic ~1600 token budget)

    # Conversation history
    max_history_turns: int = 10  # Max messages to send to VLM (0 = unlimited, 10 = last 5 exchanges)

    # Coordinate validation: "strict" (y<140), "relaxed" (y<100), "off" (bounds only)
    coordinate_validation: str = "relaxed"

    # Action feedback: inject confirmation message after successful actions
    action_feedback: bool = True

    # Smart wait: add extra delay after navigation-likely actions (clicks, Enter key)
    smart_wait: bool = True
    smart_wait_delay: float = 1.5  # Extra seconds to wait after navigation actions

    # Step budget awareness: tell VLM how many steps used/remaining
    step_budget_awareness: bool = True

    # Adaptive prompt: inject task-specific hints based on task keywords
    adaptive_prompt: bool = True

    # Auto-navigate: extract URL from task and navigate before VLM loop
    auto_navigate: bool = True

    # Custom system prompt override (None = use default GUI_AGENT prompt)
    system_prompt: Optional[str] = None

    # Safety settings
    confirm_actions: bool = False  # Ask before executing
    dry_run: bool = False  # Don't actually execute actions

    # Grid overlay settings
    grid_spacing: int = 400  # Grid line spacing in original pixels

    # Visual feedback
    show_cursor_overlay: bool = True  # Show visual cursor indicator on screen
    show_action_notifier: bool = True  # Show action notification UI
    show_coordinate_grid: bool = False  # Grid overlay unnecessary at 1344px (Exp 66)

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0

    # Sandbox mode - operate inside Docker sandbox via HTTP API
    sandbox_mode: bool = False
    sandbox_url: str = "http://localhost:8000"

    # Guidebook — path to a .md guidebook for navigation reference
    guidebook_path: Optional[Path] = None


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
    token_usage: Optional[Dict[str, int]] = None


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
        console: Optional[Console] = None,
        operator: Optional[Operator] = None
    ):
        """
        Initialize the GUI agent.

        Args:
            config: Agent configuration
            console: Rich console for output
            operator: Optional Operator for screenshot/execute (overrides sandbox_mode)
        """
        self.config = config or AgentConfig()
        self.console = console or Console()
        self.operator = operator

        # Initialize components based on mode
        if self.operator:
            # Operator provided — use it for screenshot/execute
            self.screen = None
            self.controller = None
            self.window_manager = None
            self.config.show_cursor_overlay = False
            self.config.show_action_notifier = False
        elif self.config.sandbox_mode:
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

        # Initialize VLM or CUA client based on provider
        if self.config.provider == "openai":
            self.cua_client = CUAClient(self.config.cua_config)
            self.vlm = None
            self.openai_vlm = None
            self.parser = None
        elif self.config.provider == "openai-vlm":
            self.openai_vlm = OpenAIVLMClient(self.config.openai_vlm_config)
            self.vlm = None
            self.cua_client = None
            self.parser = None
        else:
            self.vlm = VLMClient(self.config.vlm_config)
            self.parser = ActionParser()
            self.cua_client = None
            self.openai_vlm = None

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
        self._vlm_scale_factor: float = 1.0  # Ratio of original/VLM image size

        # Build system prompt — only needed for Anthropic and OpenAI-VLM providers
        if self.config.provider == "openai":
            self._system_prompt = ""  # CUA manages its own prompting
        elif self.config.provider == "openai-vlm":
            self._system_prompt = ""  # CUA-style loop uses built-in prompt
        elif self.config.system_prompt:
            self._system_prompt = self.config.system_prompt
        elif self.operator:
            self._system_prompt = SystemPrompts.GUI_AGENT_COMPRESSED_TEMPLATE.replace(
                "{{action_space}}", self.operator.action_space()
            )
        else:
            self._system_prompt = SystemPrompts.GUI_AGENT_COMPRESSED

        # Ensure screenshot directory exists
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _call_vlm(
        self,
        screenshot_data,
        vlm_media_type: str,
        task: str,
        screen_info: Optional[Dict[str, int]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
    ):
        """Dispatch VLM call to the Anthropic backend."""
        return self.vlm.analyze_screenshot(
            screenshot=screenshot_data,
            task=task,
            screen_info=screen_info,
            history=history if history else None,
            system_prompt=self._system_prompt,
        )

    def _on_stop_hotkey(self) -> None:
        """Callback when stop hotkey (Ctrl+Alt) is pressed."""
        if self.state != AgentState.RUNNING:
            return
        self.console.print("\n[yellow]Stop hotkey detected (Ctrl+Alt). Stopping agent...[/]")
        self.state = AgentState.PAUSED
        # Stop the monitor immediately so it won't fire again
        if self._hotkey_monitor:
            self._hotkey_monitor._running = False
        # Send SIGINT to main thread to interrupt blocking I/O (e.g. HTTP calls)
        os.kill(os.getpid(), signal.SIGINT)

    def _capture_screenshot(self, step_number: int) -> Tuple[str, Path, Dict[str, int]]:
        """Capture screenshot and return base64, path, and screen info."""
        # Pause overlays to prevent them from appearing in screenshot
        if self._cursor_overlay:
            self._cursor_overlay.pause()
        if self._action_notifier:
            self._action_notifier.pause()

        time.sleep(0.05)  # Brief wait to ensure screen is clear

        # Capture screenshot — use operator if available, else legacy screen
        if self.operator:
            img = self.operator.screenshot()
        else:
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

        # Save screenshot as PNG (compressed) — without grid overlay
        screenshot_path = None
        if self.config.save_screenshots:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = self.config.screenshot_dir / f"step_{step_number:03d}_{timestamp}.png"
            img.save(screenshot_path, format="PNG", optimize=True)

        # Resize screenshot for VLM to avoid coordinate mismatch.
        # VLM APIs (Anthropic) internally resize images with long edge > 1568px
        # and a total pixel budget of ~1,192,464. If we send a raw screenshot
        # the VLM sees a downscaled image where visual positions don't match
        # the grid labels, causing systematic coordinate errors.
        # Fix: resize FIRST to fit within both constraints (long edge AND pixel
        # budget), then draw grid with labels showing ORIGINAL screen
        # coordinates mapped to the resized pixel positions.
        vlm_img = img
        original_w, original_h = img.size
        max_edge = self.config.vlm_max_edge
        max_pixels = self.config.vlm_max_pixels
        scale_factor = 1.0

        # Constraint 1: long edge must not exceed max_edge
        if max(original_w, original_h) > max_edge:
            scale_factor = min(scale_factor, max_edge / max(original_w, original_h))

        # Constraint 2: total pixels must not exceed budget
        current_pixels = original_w * original_h
        if current_pixels > max_pixels:
            scale_factor = min(scale_factor, math.sqrt(max_pixels / current_pixels))

        if scale_factor < 1.0:
            new_w = round(original_w * scale_factor)
            new_h = round(original_h * scale_factor)
            vlm_img = img.resize((new_w, new_h), Image.LANCZOS)

        # Store inverse scale so parsed VLM coordinates can be mapped back
        self._vlm_scale_factor = 1.0 / scale_factor

        # Update screen_info to match the VLM image dimensions so the VLM
        # reports coordinates in image-pixel space (which _rescale_action_coords
        # will then map back to original screen coordinates).
        screen_info = {
            "width": vlm_img.width,
            "height": vlm_img.height
        }
        # Keep original screen size for coordinate validation (after rescale)
        original_screen_info = {
            "width": original_w,
            "height": original_h
        }

        # Apply coordinate grid overlay for VLM (not saved to disk)
        if self.config.show_coordinate_grid:
            vlm_img = self._draw_coordinate_grid(
                vlm_img,
                spacing=self.config.grid_spacing,
                original_size=(original_w, original_h),
            )

        # Encode image for VLM
        buffer = io.BytesIO()
        vlm_format = self.config.vlm_image_format.lower()
        if vlm_format == "jpeg":
            if vlm_img.mode == "RGBA":
                vlm_img = vlm_img.convert("RGB")
            vlm_img.save(buffer, format="JPEG", quality=self.config.vlm_image_quality)
        else:
            vlm_img.save(buffer, format="PNG", optimize=True)
        base64_img = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

        return base64_img, screenshot_path, screen_info, original_screen_info

    def _rescale_action_coords(self, action: AnyAction) -> None:
        """Scale VLM-reported coordinates from image space to screen space.

        VLMs report coordinates in the pixel space of the image they receive.
        When the screenshot was resized before sending to the VLM, we need to
        scale those coordinates back to the original screen resolution.
        Modifies the action in-place.

        Uses separate X/Y scale factors for non-uniform scaling (e.g. ultrawide
        3440x1440 native scaled to 1920x1080 for the model).
        """
        sx = getattr(self, '_vlm_scale_factor_x', self._vlm_scale_factor)
        sy = getattr(self, '_vlm_scale_factor_y', self._vlm_scale_factor)
        if sx == 1.0 and sy == 1.0:
            return

        # Absolute x, y (most actions)
        if hasattr(action, 'x') and isinstance(getattr(action, 'x'), (int, float)):
            if action.x is not None:
                action.x = round(action.x * sx)
        if hasattr(action, 'y') and isinstance(getattr(action, 'y'), (int, float)):
            if action.y is not None:
                action.y = round(action.y * sy)

        # DragAction: start_x/y, end_x/y
        if hasattr(action, 'start_x'):
            action.start_x = round(action.start_x * sx)
        if hasattr(action, 'start_y'):
            action.start_y = round(action.start_y * sy)
        if hasattr(action, 'end_x'):
            action.end_x = round(action.end_x * sx)
        if hasattr(action, 'end_y'):
            action.end_y = round(action.end_y * sy)

        # MoveRelativeAction: dx, dy offsets also need scaling
        if hasattr(action, 'dx') and isinstance(getattr(action, 'dx'), (int, float)):
            action.dx = round(action.dx * sx)
        if hasattr(action, 'dy') and isinstance(getattr(action, 'dy'), (int, float)):
            action.dy = round(action.dy * sy)

    @staticmethod
    def _draw_coordinate_grid(
        img: Image.Image,
        spacing: int = 100,
        original_size: Optional[Tuple[int, int]] = None,
    ) -> Image.Image:
        """
        Draw a coordinate grid overlay on a screenshot for VLM coordinate reading.

        When ``original_size`` is given the image is assumed to be a resized
        version of that larger screenshot.  Grid lines and labels are placed so
        that the *label values* correspond to the original (screen) coordinate
        system while the *pixel positions* match the current image dimensions.
        This eliminates the systematic offset that occurs when a VLM API
        internally downscales the image: the visual positions of the grid lines
        now agree with their numeric labels.

        Args:
            img: PIL Image to annotate (not modified in-place).
            spacing: Coordinate spacing in the *original* coordinate system
                     (default 100 — a grid line every 100 original pixels).
            original_size: ``(orig_w, orig_h)`` of the full-resolution
                           screenshot.  If *None* the image is assumed to be
                           at original resolution and labels equal pixel
                           positions.

        Returns:
            New PIL Image with grid overlay.
        """
        img = img.copy()
        draw = ImageDraw.Draw(img, "RGBA")
        w, h = img.size

        # Determine mapping from original coords to current image pixels
        if original_size is not None:
            orig_w, orig_h = original_size
            sx = w / orig_w  # scale factor x
            sy = h / orig_h  # scale factor y
        else:
            orig_w, orig_h = w, h
            sx = sy = 1.0

        # Use a small default font
        try:
            font = ImageFont.truetype("arial.ttf", 11)
        except OSError:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 11)
            except OSError:
                font = ImageFont.load_default()

        grid_color = (255, 0, 0, 50)       # Semi-transparent red lines
        major_grid_color = (255, 0, 0, 90)  # Brighter red for major lines
        label_bg = (0, 0, 0, 160)           # Dark background for readability
        label_fg = (255, 255, 0)            # Yellow text
        major_interval = spacing * 5        # Major line every 5th grid line

        # Draw vertical lines — iterate in original coordinate space
        for orig_x in range(spacing, orig_w, spacing):
            px = round(orig_x * sx)  # pixel position in current image
            if px <= 0 or px >= w:
                continue
            is_major = (orig_x % major_interval == 0)
            color = major_grid_color if is_major else grid_color
            line_width = 2 if is_major else 1
            draw.line([(px, 0), (px, h)], fill=color, width=line_width)

            # Label at top edge — show ORIGINAL coordinate value
            label = str(orig_x)
            bbox = font.getbbox(label)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle([px - tw // 2 - 2, 0, px + tw // 2 + 2, th + 4], fill=label_bg)
            draw.text((px - tw // 2, 1), label, fill=label_fg, font=font)

            # Label at bottom edge
            draw.rectangle([px - tw // 2 - 2, h - th - 5, px + tw // 2 + 2, h], fill=label_bg)
            draw.text((px - tw // 2, h - th - 2), label, fill=label_fg, font=font)

        # Draw horizontal lines — iterate in original coordinate space
        for orig_y in range(spacing, orig_h, spacing):
            py = round(orig_y * sy)  # pixel position in current image
            if py <= 0 or py >= h:
                continue
            is_major = (orig_y % major_interval == 0)
            color = major_grid_color if is_major else grid_color
            line_width = 2 if is_major else 1
            draw.line([(0, py), (w, py)], fill=color, width=line_width)

            # Label at left edge — show ORIGINAL coordinate value
            label = str(orig_y)
            bbox = font.getbbox(label)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw.rectangle([0, py - th // 2 - 2, tw + 4, py + th // 2 + 2], fill=label_bg)
            draw.text((2, py - th // 2), label, fill=label_fg, font=font)

            # Label at right edge
            draw.rectangle([w - tw - 5, py - th // 2 - 2, w, py + th // 2 + 2], fill=label_bg)
            draw.text((w - tw - 3, py - th // 2), label, fill=label_fg, font=font)

        # Draw small crosshair markers at grid intersections for precise reference
        cross_size = 4
        cross_color = (255, 255, 0, 80)
        for orig_x in range(spacing, orig_w, spacing):
            px = round(orig_x * sx)
            if px <= 0 or px >= w:
                continue
            for orig_y in range(spacing, orig_h, spacing):
                py = round(orig_y * sy)
                if py <= 0 or py >= h:
                    continue
                draw.line([(px - cross_size, py), (px + cross_size, py)], fill=cross_color, width=1)
                draw.line([(px, py - cross_size), (px, py + cross_size)], fill=cross_color, width=1)

        return img.convert("RGB")

    def _execute_action(self, action: AnyAction) -> ActionResult:
        """Execute a parsed action."""
        try:
            if self.config.dry_run:
                self.console.print(f"[yellow][DRY RUN] Would execute: {action.action_type.value}[/]")
                return ActionResult(success=True, action=action)

            # Handle agent-level state actions first (not delegated to operator)
            if isinstance(action, DoneAction):
                self.state = AgentState.COMPLETED
                return ActionResult(success=True, action=action)

            if isinstance(action, FailAction):
                self.state = AgentState.FAILED
                return ActionResult(success=False, action=action, error=action.error)

            # Delegate to operator if available
            if self.operator:
                self.operator.execute(action)
                return ActionResult(success=True, action=action)

            # Legacy path: direct controller calls
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

    def _build_success_feedback(self, action: AnyAction) -> str:
        """Build a concise feedback message for a successful action."""
        atype = action.action_type.value
        parts = [f"Action '{atype}' executed successfully."]
        if hasattr(action, 'x') and hasattr(action, 'y') and action.x is not None:
            parts.append(f"Clicked at ({action.x}, {action.y}).")
        if hasattr(action, 'text') and action.text:
            parts.append(f"Typed: '{action.text[:50]}'.")
        if hasattr(action, 'key') and action.key:
            parts.append(f"Key: {action.key}.")
        if hasattr(action, 'keys') and isinstance(action.keys, list):
            parts.append(f"Keys: {'+'.join(action.keys)}.")
        if hasattr(action, 'direction') and action.direction:
            parts.append(f"Scrolled {action.direction}.")
        return " ".join(parts)

    def _is_navigation_action(self, action: AnyAction) -> bool:
        """Check if an action is likely to trigger a page load/navigation."""
        atype = action.action_type
        # Click actions on links often navigate
        if atype in (ActionType.CLICK, ActionType.DOUBLE_CLICK):
            return True
        # Enter key press (form submit, address bar navigate)
        if atype == ActionType.PRESS_KEY and hasattr(action, 'key'):
            if action.key and action.key.lower() in ('enter', 'return'):
                return True
        # Hotkey with Enter (e.g., Ctrl+Enter, or just Enter mapped as hotkey)
        if atype == ActionType.HOTKEY and hasattr(action, 'keys'):
            if action.keys and any(k.lower() in ('enter', 'return') for k in action.keys):
                return True
        return False

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
        if hasattr(action, 'direction'):
            parts.append(f"dir={action.direction}")
        if hasattr(action, 'amount'):
            parts.append(f"amt={action.amount}")
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

        # Scroll and wait actions are inherently repeatable — allow higher thresholds.
        # Wait is especially common during video playback (must wait for progress bar).
        is_scroll = isinstance(action, ScrollAction)
        is_wait = isinstance(action, WaitAction)
        if is_wait:
            block_threshold = 30
            override_threshold = 50
        elif is_scroll:
            block_threshold = 6
            override_threshold = 8
        else:
            block_threshold = 3
            override_threshold = 5

        # Smart override: if agent typed text recently and is now stuck clicking,
        # override earlier (at 3 repeats instead of 5) with Enter key
        if consecutive_count >= 3 and self._should_submit_after_type(action):
            return (
                "OVERRIDE: You typed text into a field and then kept clicking instead of submitting. "
                "The system is pressing Enter to submit. "
                "After this, observe the screen and proceed with the next step of the task.",
                "override"
            )

        # 5+ identical (8+ for scroll): force override with keyboard fallback
        if consecutive_count >= override_threshold:
            return (
                "CRITICAL: You have repeated the EXACT SAME action 5+ times. "
                "The system is now OVERRIDING your action with a keyboard shortcut. "
                "After this override, you MUST analyze the screen fresh and try something completely new.",
                "override"
            )

        # 3-4 identical (6-7 for scroll): block and force re-query
        if consecutive_count >= block_threshold:
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

    def _build_adaptive_hints(self, task: str) -> str:
        """Generate task-specific hints based on keywords in the task description."""
        hints = []
        task_lower = task.lower()

        # Section finding: recommend Ctrl+F
        if any(kw in task_lower for kw in ["find the", "scroll down to find", "find the section",
                                            "locate the", "scroll to the"]):
            hints.append(
                "STRATEGY: To find a specific section on a long page, use Ctrl+F (Find) to search "
                "for the section name instead of scrolling. This is faster and more reliable."
            )

        # Form filling / multi-field tasks
        if any(kw in task_lower for kw in ["fill in", "fill out", "enter your", "type your"]):
            hints.append(
                "STRATEGY: For form fields, use Tab to move between fields instead of clicking each one."
            )

        # Search tasks with explicit submit
        if "search for" in task_lower and "click" not in task_lower:
            hints.append(
                "TIP: After typing a search query, press Enter to submit rather than clicking the search button."
            )

        # URL navigation: press Enter right after typing (skip Escape for autocomplete)
        if any(kw in task_lower for kw in ["go to", "navigate to", "open", "visit"]):
            hints.append(
                "TIP: After typing a URL in the address bar, press Enter immediately to navigate. "
                "Do NOT press Escape first — the autocomplete dropdown will be dismissed automatically when you press Enter."
            )

        # Wikipedia/article with table of contents
        if "wikipedia" in task_lower and any(kw in task_lower for kw in ["section", "find", "scroll"]):
            hints.append(
                "TIP: Wikipedia articles have a Table of Contents near the top. You can click a section link "
                "in the ToC to jump directly to that section instead of scrolling."
            )

        return "\n".join(hints) if hints else ""

    def _extract_target_url(self, task: str) -> Optional[str]:
        """Extract a target URL from the task description.

        Matches patterns like 'Go to duckduckgo.com', 'Open en.wikipedia.org',
        'Navigate to youtube.com'. Returns the URL with scheme or None.
        """
        import re
        pattern = r'(?:go to|open|visit|navigate to)\s+((?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s,]*)?)'
        match = re.search(pattern, task.lower())
        if match:
            url = match.group(1)
            if not url.startswith('http'):
                url = 'https://' + url
            return url
        return None

    def _rewrite_task_after_navigate(self, task: str, url: str) -> str:
        """Rewrite task description after auto-navigation.

        Removes the 'Go to X.com' prefix and prepends context that
        the browser is already on the target page.
        """
        import re
        # Remove the navigation phrase from the task
        # Match: "Go to X.com, " or "Go to X.com and " or "Go to X.com"
        pattern = r'(?:go to|open|visit|navigate to)\s+(?:https?://)?[a-zA-Z0-9][a-zA-Z0-9.-]+\.[a-zA-Z]{2,}(?:/[^\s,]*)?\s*(?:,\s*(?:and\s+)?|(?:\s+and\s+)|\s*$)'
        rewritten = re.sub(pattern, '', task, count=1, flags=re.IGNORECASE).strip()
        # Remove leading "and " if present after substitution
        rewritten = re.sub(r'^and\s+', '', rewritten, flags=re.IGNORECASE).strip()
        # Capitalize first letter
        if rewritten:
            rewritten = rewritten[0].upper() + rewritten[1:]
        # Prepend context about current page
        domain = url.replace('https://', '').replace('http://', '').rstrip('/')
        return f"The browser is already on {domain}. {rewritten}"

    def _validate_coordinates(self, action: AnyAction, screen_info: Dict[str, int]) -> Optional[str]:
        """
        Validate that click/interact coordinates are plausible.

        Catches common VLM mistakes:
        - Coordinates outside screen bounds
        - Clicking browser chrome when the element name suggests a web page element

        Behavior controlled by self.config.coordinate_validation:
        - "strict": Reject web page elements at y < 140 (original behavior)
        - "relaxed": Reject web page elements at y < 100 only (allows y=100-140 zone)
        - "off": Only check screen bounds

        Args:
            action: The parsed action to validate.
            screen_info: Screen dimensions dict with 'width' and 'height'.

        Returns:
            Warning message to inject into conversation if coordinates seem wrong,
            or None if coordinates look fine.
        """
        if not hasattr(action, 'x') or not hasattr(action, 'y'):
            return None

        x, y = action.x, action.y

        # Some actions (e.g. ScrollAction) may have x/y as None
        if x is None or y is None:
            return None

        w, h = screen_info.get("width", 1920), screen_info.get("height", 1080)

        # Out of bounds check (always active)
        if x < 0 or x >= w or y < 0 or y >= h:
            return (
                f"WARNING: Your coordinates ({x}, {y}) are OUTSIDE the screen bounds "
                f"({w}x{h}). Please re-examine the screenshot and provide valid coordinates."
            )

        # If validation is off, only do bounds check
        validation_mode = self.config.coordinate_validation
        if validation_mode == "off":
            return None

        # Determine chrome threshold based on mode
        chrome_threshold = 140 if validation_mode == "strict" else 100

        # Check if element name suggests a web page element but coordinates are in browser chrome
        element_name = ""
        if hasattr(action, 'element') and action.element:
            element_name = action.element.lower()
        elif hasattr(action, 'element_description') and action.element_description:
            element_name = action.element_description.lower()
        elif hasattr(action, 'target_element') and action.target_element:
            element_name = action.target_element.lower()

        # Keywords that indicate a web page element (not browser chrome)
        webpage_keywords = [
            "search", "input", "text field", "text box", "form",
            "button", "link", "menu", "dropdown", "submit",
            "login", "password", "email", "username",
            "search privately",  # DuckDuckGo specific
        ]

        # If element name matches web page keywords AND y < threshold, it's likely wrong
        if y < chrome_threshold and element_name:
            is_webpage_element = any(kw in element_name for kw in webpage_keywords)
            # Exclude browser-specific elements that ARE in the chrome area
            browser_keywords = [
                "address", "url", "tab", "bookmark", "omnibox",
                "address bar", "url bar", "navigation", "chrome",
            ]
            is_browser_element = any(kw in element_name for kw in browser_keywords)

            if is_webpage_element and not is_browser_element:
                return (
                    f"COORDINATE WARNING: You are trying to click '{element_name}' at y={y}, "
                    f"but y < {chrome_threshold} is the browser toolbar area (tabs, address bar). "
                    f"Web page elements like search boxes, buttons, and forms are ALWAYS below y={chrome_threshold}. "
                    f"Look at the grid overlay — the browser address bar is near y=50-75. "
                    f"A 'search bar' at y < {chrome_threshold} is the browser's ADDRESS BAR, NOT the web page search box. "
                    f"The web page search box is typically around y=400-550. "
                    f"Please use the grid lines to find the ACTUAL web page search input."
                )

        # Extra guard: ANY click at y < 100 on an element with "search" in the name
        # is almost certainly a misidentification of the browser address bar
        if y < 100 and element_name and "search" in element_name:
            return (
                f"COORDINATE WARNING: You clicked '{element_name}' at y={y}, which is in the "
                f"browser chrome area. At y < 100, the only clickable elements are browser tabs "
                f"and the address bar. If you want to search, look for the web page's search "
                f"input field which is always below y=140. Use the grid overlay to find it."
            )

        return None

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
        # Dispatch to CUA loop for OpenAI providers
        if self.config.provider == "openai":
            return self.run_cua(task, on_step=on_step, on_action=on_action)
        if self.config.provider == "openai-vlm":
            return self.run_cua_vlm(task, on_step=on_step, on_action=on_action)

        self.state = AgentState.RUNNING
        self.current_task = task
        self.steps = []
        self._conversation_history = []
        self._recent_actions = []

        # Install SIGINT handler so Ctrl+C interrupts blocking I/O on Windows
        prev_sigint = signal.getsignal(signal.SIGINT)

        def _sigint_handler(signum, frame):
            self.state = AgentState.PAUSED
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _sigint_handler)

        # Start hotkey monitor for stopping agent (Ctrl+Alt)
        from .core.hotkey import HotkeyMonitor
        self._hotkey_monitor = HotkeyMonitor(self._on_stop_hotkey)
        self._hotkey_monitor.start()
        self.console.print("[dim]Press Ctrl+C or Ctrl+Alt to stop the agent[/]")

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

        # Auto-navigate: extract URL from task, navigate directly, rewrite task
        if self.config.auto_navigate:
            target_url = self._extract_target_url(task)
            if target_url:
                self.console.print(f"[cyan]Auto-navigate: navigating to {target_url}[/]")
                try:
                    import httpx
                    sandbox_url = None
                    if self.operator and hasattr(self.operator, '_controller'):
                        sandbox_url = getattr(self.operator._controller, 'base_url', None)
                    if sandbox_url:
                        resp = httpx.post(
                            f"{sandbox_url}/chrome/navigate",
                            params={"url": target_url},
                            timeout=10,
                        )
                        if resp.status_code == 200:
                            self.console.print(f"[cyan]Auto-navigate: page loading...[/]")
                            import time as _time
                            _time.sleep(2)
                            # Rewrite task to remove navigation and add context
                            task = self._rewrite_task_after_navigate(task, target_url)
                            self.console.print(f"[cyan]Rewritten task: {task}[/]")
                        else:
                            self.console.print(f"[yellow]Auto-navigate: failed ({resp.status_code})[/]")
                    else:
                        self.console.print("[yellow]Auto-navigate: no sandbox URL available[/]")
                except Exception as e:
                    self.console.print(f"[yellow]Auto-navigate: error - {e}[/]")

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
                base64_img, screenshot_path, screen_info, original_screen_info = self._capture_screenshot(step_number)

                # 2. Analyze with VLM
                self.console.print("[dim]Analyzing screenshot...[/]")
                # Pass as tuple (base64_data, media_type)
                vlm_media_type = "image/jpeg" if self.config.vlm_image_format.lower() == "jpeg" else "image/png"
                screenshot_data = (base64_img, vlm_media_type)

                # Apply sliding window to conversation history if configured
                if self.config.max_history_turns > 0 and self._conversation_history:
                    history_to_send = self._conversation_history[-self.config.max_history_turns:]
                else:
                    history_to_send = self._conversation_history

                # Build task string with optional adaptive hints and step budget awareness
                task_for_vlm = task
                if self.config.grid_spacing != 100:
                    task_for_vlm += (
                        f"\n\n[Grid Info] The coordinate grid overlay has lines every "
                        f"{self.config.grid_spacing} pixels (not 100). Interpolate between "
                        f"grid lines for coordinates that fall between them."
                    )
                if self.config.adaptive_prompt:
                    adaptive_hints = self._build_adaptive_hints(task)
                    if adaptive_hints:
                        task_for_vlm += f"\n\n[Hints]\n{adaptive_hints}\n[End Hints]"
                if self.config.step_budget_awareness:
                    remaining = self.config.max_steps - step_number
                    task_for_vlm += f"\n\n[Step {step_number}/{self.config.max_steps} — {remaining} steps remaining]"
                    if remaining <= 3:
                        task_for_vlm += " URGENT: Very few steps left. Complete the task NOW or report done/fail."
                    elif remaining <= self.config.max_steps // 3:
                        task_for_vlm += " Be efficient — limited steps remaining."

                vlm_response = self._call_vlm(
                    screenshot_data=screenshot_data,
                    vlm_media_type=vlm_media_type,
                    task=task_for_vlm,
                    screen_info=screen_info,
                    history=history_to_send if history_to_send else None,
                )

                # 3. Parse action
                action, parse_msg = self.parser.parse(vlm_response.text)

                # 3.1 Rescale coordinates from VLM image space to screen space
                if action is not None:
                    self._rescale_action_coords(action)

                # Create step record
                step = AgentStep(
                    step_number=step_number,
                    timestamp=timestamp,
                    screenshot_path=screenshot_path,
                    vlm_response=vlm_response.text,
                    action=action,
                    action_result=None,
                    reasoning=action.reasoning if action else parse_msg,
                    token_usage=vlm_response.usage if hasattr(vlm_response, 'usage') else None
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

                # 3.25. Validate coordinates before execution
                coord_warning = self._validate_coordinates(action, original_screen_info)
                if coord_warning:
                    self.console.print(f"[yellow]{coord_warning[:100]}...[/]")
                    # Don't execute — re-query VLM with the warning
                    step.action_result = ActionResult(
                        success=False,
                        action=action,
                        error="Coordinates rejected by validation"
                    )
                    step.reasoning = "SYSTEM: Coordinate validation failed — re-querying VLM"
                    self._conversation_history.append({
                        "role": "assistant",
                        "content": vlm_response.text
                    })
                    self._conversation_history.append({
                        "role": "user",
                        "content": coord_warning
                    })
                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)
                    time.sleep(self.config.step_delay)
                    continue

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
                elif self.config.action_feedback and action.action_type not in (
                    ActionType.DONE, ActionType.FAIL
                ):
                    self._conversation_history.append({
                        "role": "user",
                        "content": self._build_success_feedback(action)
                    })

                # 7. Display and record step
                self._display_step(step)
                self.steps.append(step)

                if on_step:
                    on_step(step)

                # 8. Delay before next step
                if self.state == AgentState.RUNNING:
                    if (self.config.smart_wait and result.success
                            and self._is_navigation_action(action)):
                        self.console.print(f"[dim]Smart wait: {self.config.smart_wait_delay}s for page load[/]")
                        time.sleep(self.config.smart_wait_delay)
                    else:
                        time.sleep(self.config.step_delay)

            except KeyboardInterrupt:
                self.state = AgentState.PAUSED
                break

            except Exception as e:
                self.console.print(f"[red]Error in step {step_number}: {e}[/]")
                self.state = AgentState.FAILED
                break

        # Restore original SIGINT handler
        signal.signal(signal.SIGINT, prev_sigint)

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
        elif self.state == AgentState.PAUSED:
            self.console.print(Panel("[yellow]Interrupted by user[/]", title="Stopped"))
        else:
            self.console.print(Panel("[yellow]Max steps reached[/]", title="Stopped"))

        return self.steps

    # ==================== CUA-VLM (GPT-5.4 CUA loop via Responses API) ====================

    def run_cua_vlm(
        self,
        task: str,
        on_step: Optional[Callable[[AgentStep], None]] = None,
        on_action: Optional[Callable[[AnyAction], bool]] = None
    ) -> List[AgentStep]:
        """
        Run the agent following the official GPT-5.4 CUA loop pattern.

        The model fully controls the flow:
        1. Capture screenshot → send to model with task + turn history
        2. Model returns actions[] → execute all in order
        3. Capture result screenshot → record turn (before, actions, results, after)
        4. Send new screenshot to model with updated history → repeat
        5. Until model sets status="done" or max steps reached

        Each turn in history contains:
        - Screenshot BEFORE actions (compressed JPEG for old turns)
        - Model's action response
        - Execution results
        - Screenshot AFTER actions (compressed JPEG for old turns)

        This gives the model full visual context to learn from past attempts.
        """
        self.state = AgentState.RUNNING
        self.current_task = task
        self.steps = []
        self._recent_actions = []

        # Install SIGINT handler
        prev_sigint = signal.getsignal(signal.SIGINT)

        def _sigint_handler(signum, frame):
            self.state = AgentState.PAUSED
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _sigint_handler)

        # Start hotkey monitor
        from .core.hotkey import HotkeyMonitor
        self._hotkey_monitor = HotkeyMonitor(self._on_stop_hotkey)
        self._hotkey_monitor.start()
        self.console.print("[dim]Press Ctrl+C or Ctrl+Alt to stop the agent[/]")

        # Start cursor overlay
        if self.config.show_cursor_overlay:
            from .core.cursor_overlay import CursorOverlay
            self._cursor_overlay = CursorOverlay(color="red", size=50, line_width=4)
            self._cursor_overlay.start()

        # Start action notifier
        if self.config.show_action_notifier:
            from .core.action_notifier import ActionNotifier
            self._action_notifier = ActionNotifier()
            self._action_notifier.start()
            self._action_notifier.show_action("thinking", f"CUA-VLM: {task[:50]}...")

        display_w = self.openai_vlm.config.display_width
        display_h = self.openai_vlm.config.display_height

        self.console.print(Panel(
            f"[bold]Task:[/] {task}\n[dim]Provider: CUA-VLM ({self.openai_vlm.config.model}), "
            f"display: {display_w}x{display_h}[/]",
            title="GUI Agent Started (CUA-VLM Mode)"
        ))

        from .vlm.openai_vlm_client import TurnRecord

        # Load guidebook if provided
        guidebook_context = None
        if self.config.guidebook_path and self.config.guidebook_path.exists():
            from .explore import load_guidebook, summarize_guidebook_for_prompt
            raw = load_guidebook(self.config.guidebook_path)
            guidebook_context = (
                "## APP GUIDEBOOK — Use this as your navigation reference\n\n"
                "The following guidebook was built from prior exploration of this app. "
                "Use it to understand the app structure, find elements, and navigate efficiently.\n\n"
                + summarize_guidebook_for_prompt(raw)
            )
            self.console.print(f"[dim]Loaded guidebook: {self.config.guidebook_path} ({len(raw)} chars)[/]")

        step_number = 0
        turn_history: List[TurnRecord] = []

        try:
            while self.state == AgentState.RUNNING and step_number < self.config.max_steps:
                # 1. Capture current screenshot (this is the "before" for this turn)
                step_number += 1
                if self._action_notifier:
                    self._action_notifier.show_thinking(step_number)
                self.console.print(f"\n[dim]Step {step_number}: Capturing screenshot...[/]")
                screenshot_before, screenshot_path = self._capture_screenshot_cua(step_number)

                # 2. Send to model with turn history
                self.console.print(f"[dim]Sending to model (history: {len(turn_history)} turns)...[/]")
                vlm_response = self.openai_vlm.send(
                    task=task,
                    current_screenshot=screenshot_before,
                    turn_history=turn_history,
                    extra_context=guidebook_context,
                )

                actions_raw = vlm_response.actions
                status = vlm_response.status

                self.console.print(
                    f"[dim]Model returned {len(actions_raw)} action(s), status={status}, "
                    f"tokens: in={vlm_response.usage.get('input_tokens', 0)} "
                    f"out={vlm_response.usage.get('output_tokens', 0)}[/]"
                )

                # 3. Check if model says done/fail
                if status == "done" or status == "fail":
                    self.state = AgentState.COMPLETED if status == "done" else AgentState.FAILED
                    try:
                        parsed = json.loads(vlm_response.text.strip().lstrip("`").lstrip("json").lstrip("`"))
                        reason = parsed.get("reasoning", vlm_response.text[:200])
                    except (json.JSONDecodeError, AttributeError):
                        reason = vlm_response.text[:200]
                    self.console.print(f"[{'green' if status == 'done' else 'red'}]Model says {status}: {_sanitize_text(reason[:200])}[/]")

                    step = AgentStep(
                        step_number=step_number,
                        timestamp=datetime.now(),
                        screenshot_path=screenshot_path,
                        vlm_response=vlm_response.text,
                        action=DoneAction(reasoning=reason, action_type=ActionType.DONE) if status == "done"
                               else FailAction(reasoning=reason, action_type=ActionType.FAIL),
                        action_result=ActionResult(success=(status == "done"), action=None),
                        reasoning=reason,
                        token_usage=vlm_response.usage,
                    )
                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)
                    break

                # 4. Handle screenshot-only request (model wants to see screen first)
                is_screenshot_only = (
                    len(actions_raw) == 1 and
                    actions_raw[0].get("type") == "screenshot"
                ) or not actions_raw

                if is_screenshot_only:
                    self.console.print(f"[dim]Step {step_number}: Model requested screenshot (no actions)[/]")
                    step = AgentStep(
                        step_number=step_number,
                        timestamp=datetime.now(),
                        screenshot_path=screenshot_path,
                        vlm_response=vlm_response.text,
                        action=ScreenshotAction(reasoning="Model requested screenshot", action_type=ActionType.SCREENSHOT),
                        action_result=ActionResult(success=True, action=ScreenshotAction(action_type=ActionType.SCREENSHOT)),
                        reasoning="Model requested screenshot",
                        token_usage=vlm_response.usage,
                    )
                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)

                    # Record as a turn with identical before/after screenshots
                    turn_history.append(TurnRecord(
                        screenshot_before=screenshot_before,
                        model_response=vlm_response.text,
                        actions_summary="screenshot request (no actions executed)",
                        results_summary="Screenshot captured",
                        screenshot_after=screenshot_before,  # Same — nothing changed
                    ))
                    continue

                # 5. Map and execute CUA actions
                mapped_actions = map_cua_actions(actions_raw)
                for action in mapped_actions:
                    self._rescale_action_coords(action)

                action_summaries = []
                result_summaries = []

                for i, action in enumerate(mapped_actions):
                    if self.state != AgentState.RUNNING:
                        break

                    # Show in notifier
                    if self._action_notifier:
                        detail = self._get_action_detail(action)
                        self._action_notifier.show_step(step_number, action.action_type.value, detail)

                    # Confirm callback
                    if on_action and not on_action(action):
                        self.console.print("[yellow]Action skipped by callback[/]")
                        action_summaries.append(f"{action.action_type.value}: SKIPPED")
                        result_summaries.append("skipped by user")
                        continue

                    # Execute
                    if isinstance(action, ScreenshotAction):
                        self.console.print(f"[dim]  Action {i+1}/{len(mapped_actions)}: screenshot (no-op)[/]")
                        result = ActionResult(success=True, action=action)
                    else:
                        self.console.print(f"[dim]  Action {i+1}/{len(mapped_actions)}: {action.action_type.value}[/]")
                        result = self._execute_action(action)

                    action_desc = action.action_type.value
                    if hasattr(action, 'x') and hasattr(action, 'y'):
                        action_desc += f" at ({getattr(action, 'x', '?')}, {getattr(action, 'y', '?')})"
                    if hasattr(action, 'text'):
                        action_desc += f" text='{getattr(action, 'text', '')[:30]}'"
                    if hasattr(action, 'key'):
                        action_desc += f" key={getattr(action, 'key', '')}"
                    action_summaries.append(action_desc)

                    if result.success:
                        result_summaries.append(f"{action.action_type.value}: OK")
                    else:
                        result_summaries.append(f"{action.action_type.value}: FAILED - {result.error}")

                    # Only create AgentStep for the first action (others are batched)
                    if i == 0:
                        step = AgentStep(
                            step_number=step_number,
                            timestamp=datetime.now(),
                            screenshot_path=screenshot_path,
                            vlm_response=vlm_response.text,
                            action=action,
                            action_result=result,
                            reasoning=action.reasoning,
                            token_usage=vlm_response.usage,
                        )
                        self._display_step(step)
                        self.steps.append(step)
                        if on_step:
                            on_step(step)

                if self.state != AgentState.RUNNING:
                    break

                # 6. Wait for UI to settle, then capture result screenshot
                time.sleep(0.5)
                self.console.print("[dim]Capturing result screenshot...[/]")
                screenshot_after, screenshot_after_path = self._capture_screenshot_cua(step_number)

                # Update last step's screenshot to the after screenshot
                if self.steps:
                    self.steps[-1].screenshot_path = screenshot_after_path

                # 7. Record this turn in history
                turn_history.append(TurnRecord(
                    screenshot_before=screenshot_before,
                    model_response=vlm_response.text,
                    actions_summary="; ".join(action_summaries),
                    results_summary="; ".join(result_summaries),
                    screenshot_after=screenshot_after,
                ))

                self.console.print(
                    f"[dim]Turn recorded. History: {len(turn_history)} turns "
                    f"(sending last {min(len(turn_history), self.openai_vlm.MAX_HISTORY_TURNS)})[/]"
                )

                # Step delay
                if self.config.step_delay > 0:
                    time.sleep(self.config.step_delay)

        except KeyboardInterrupt:
            self.state = AgentState.PAUSED

        except Exception as e:
            self.console.print(f"[red]CUA-VLM error: {e}[/]")
            import traceback
            traceback.print_exc()
            self.state = AgentState.FAILED

        # Restore SIGINT handler
        signal.signal(signal.SIGINT, prev_sigint)

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
            self.console.print(Panel("[green]Task completed successfully![/]", title="CUA-VLM Done"))
        elif self.state == AgentState.FAILED:
            self.console.print(Panel("[red]Task failed[/]", title="CUA-VLM Failed"))
        elif self.state == AgentState.PAUSED:
            self.console.print(Panel("[yellow]Interrupted by user[/]", title="CUA-VLM Stopped"))
        else:
            self.console.print(Panel("[yellow]Max steps reached[/]", title="CUA-VLM Stopped"))

        return self.steps

    # ==================== Explore Mode ====================

    def run_explore(
        self,
        app_description: str,
        output_path: Path,
        on_step: Optional[Callable[[AgentStep], None]] = None,
        on_action: Optional[Callable[[AnyAction], bool]] = None,
    ) -> Path:
        """
        Explore an application and generate a guidebook.

        Uses the CUA-VLM loop with a specialized exploration prompt.
        The model systematically navigates the app, documents pages and elements,
        and builds a structured map. The result is saved as a markdown guidebook.

        Args:
            app_description: Description of the app to explore (e.g., "Security Foundations: Secure on the Go | Viva Learning")
            output_path: Path to save the guidebook .md file
            on_step: Callback after each step
            on_action: Callback before action execution

        Returns:
            Path to the generated guidebook file
        """
        from .explore import EXPLORE_SYSTEM_PROMPT, AppMap, generate_guidebook
        from .vlm.openai_vlm_client import TurnRecord

        self.state = AgentState.RUNNING
        self.current_task = f"Explore: {app_description}"
        self.steps = []
        self._recent_actions = []

        # Install SIGINT handler
        prev_sigint = signal.getsignal(signal.SIGINT)

        def _sigint_handler(signum, frame):
            self.state = AgentState.PAUSED
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _sigint_handler)

        # Start hotkey monitor
        from .core.hotkey import HotkeyMonitor
        self._hotkey_monitor = HotkeyMonitor(self._on_stop_hotkey)
        self._hotkey_monitor.start()
        self.console.print("[dim]Press Ctrl+C or Ctrl+Alt to stop exploration[/]")

        # Start cursor overlay
        if self.config.show_cursor_overlay:
            from .core.cursor_overlay import CursorOverlay
            self._cursor_overlay = CursorOverlay(color="blue", size=50, line_width=4)
            self._cursor_overlay.start()

        # Start action notifier
        if self.config.show_action_notifier:
            from .core.action_notifier import ActionNotifier
            self._action_notifier = ActionNotifier()
            self._action_notifier.start()
            self._action_notifier.show_action("exploring", f"Explore: {app_description[:40]}...")

        display_w = self.openai_vlm.config.display_width
        display_h = self.openai_vlm.config.display_height

        self.console.print(Panel(
            f"[bold]Exploring:[/] {app_description}\n"
            f"[dim]Provider: CUA-VLM ({self.openai_vlm.config.model}), "
            f"display: {display_w}x{display_h}[/]\n"
            f"[dim]Output: {output_path}[/]",
            title="App Explorer Started"
        ))

        app_map = AppMap(
            app_name=app_description,
            explored_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

        step_number = 0
        turn_history: List[TurnRecord] = []

        try:
            while self.state == AgentState.RUNNING and step_number < self.config.max_steps:
                step_number += 1
                if self._action_notifier:
                    self._action_notifier.show_thinking(step_number)
                self.console.print(f"\n[dim]Explore step {step_number}: Capturing screenshot...[/]")
                screenshot_before, screenshot_path = self._capture_screenshot_cua(step_number)

                # Send to model with explore prompt
                self.console.print(f"[dim]Sending to model (history: {len(turn_history)} turns, pages: {len(app_map.pages)})...[/]")

                # Build progress context
                visited_pages = list(app_map.pages.keys())
                progress = (
                    f"\n\n## Exploration Progress\n"
                    f"Pages discovered so far: {', '.join(visited_pages) if visited_pages else 'none yet'}\n"
                    f"Steps taken: {step_number}/{self.config.max_steps}\n"
                )
                if not visited_pages or all(
                    "new_tab" in p or "browser" in p for p in visited_pages
                ):
                    progress += (
                        "\nYou haven't reached the target app yet. "
                        "Navigate to it NOW using the address bar:\n"
                        '1. {"type": "keypress", "keys": ["CTRL", "l"]}\n'
                        '2. {"type": "type", "text": "search query or URL for the app"}\n'
                        '3. {"type": "keypress", "keys": ["ENTER"]}\n'
                        "If there's a shortcut tile visible for the app, you can click it directly instead.\n"
                    )
                elif visited_pages:
                    progress += "Focus on finding NEW pages you haven't visited yet.\n"

                vlm_response = self.openai_vlm.send(
                    task=f"Explore this application: {app_description}",
                    current_screenshot=screenshot_before,
                    turn_history=turn_history,
                    system_prompt_override=EXPLORE_SYSTEM_PROMPT,
                    extra_context=progress,
                )

                # Parse page_report from model response
                try:
                    text = vlm_response.text.strip()
                    if text.startswith("```"):
                        lines = text.split("\n")
                        lines = [l for l in lines if not l.strip().startswith("```")]
                        text = "\n".join(lines).strip()
                    parsed = json.loads(text)
                    page_report = parsed.get("page_report", {})
                    if page_report and page_report.get("page_id"):
                        app_map.add_page(page_report)
                        patterns = page_report.get("patterns_observed", [])
                        app_map.merge_patterns(patterns)
                        self.console.print(
                            f"[cyan]Page discovered: {page_report.get('page_id')} "
                            f"({page_report.get('page_title', '?')}), "
                            f"{len(page_report.get('elements', []))} elements[/]"
                        )
                except (json.JSONDecodeError, AttributeError):
                    pass

                actions_raw = vlm_response.actions
                status = vlm_response.status

                self.console.print(
                    f"[dim]Model: {len(actions_raw)} action(s), status={status}, "
                    f"pages={len(app_map.pages)}, "
                    f"tokens: in={vlm_response.usage.get('input_tokens', 0)} "
                    f"out={vlm_response.usage.get('output_tokens', 0)}[/]"
                )

                # Check if exploration is done
                if status == "done":
                    self.state = AgentState.COMPLETED
                    self.console.print("[green]Exploration complete![/]")
                    break

                # Handle screenshot-only / no actions
                is_screenshot_only = (
                    len(actions_raw) == 1 and
                    actions_raw[0].get("type") == "screenshot"
                ) or not actions_raw

                if is_screenshot_only:
                    self.console.print(f"[dim]Step {step_number}: Screenshot request (no actions)[/]")
                    turn_history.append(TurnRecord(
                        screenshot_before=screenshot_before,
                        model_response=vlm_response.text,
                        actions_summary="screenshot request",
                        results_summary="Screenshot captured",
                        screenshot_after=screenshot_before,
                    ))
                    continue

                # Map and execute actions
                mapped_actions = map_cua_actions(actions_raw)
                for action in mapped_actions:
                    self._rescale_action_coords(action)

                action_summaries = []
                result_summaries = []

                for i, action in enumerate(mapped_actions):
                    if self.state != AgentState.RUNNING:
                        break

                    if self._action_notifier:
                        detail = self._get_action_detail(action)
                        self._action_notifier.show_step(step_number, action.action_type.value, detail)

                    if on_action and not on_action(action):
                        action_summaries.append(f"{action.action_type.value}: SKIPPED")
                        result_summaries.append("skipped by user")
                        continue

                    if isinstance(action, ScreenshotAction):
                        result = ActionResult(success=True, action=action)
                    else:
                        self.console.print(f"[dim]  Action {i+1}/{len(mapped_actions)}: {action.action_type.value}[/]")
                        result = self._execute_action(action)

                    action_desc = action.action_type.value
                    if hasattr(action, 'x') and hasattr(action, 'y'):
                        action_desc += f" at ({getattr(action, 'x', '?')}, {getattr(action, 'y', '?')})"
                    if hasattr(action, 'text'):
                        action_desc += f" text='{getattr(action, 'text', '')[:30]}'"
                    action_summaries.append(action_desc)

                    if result.success:
                        result_summaries.append(f"{action.action_type.value}: OK")
                    else:
                        result_summaries.append(f"{action.action_type.value}: FAILED - {result.error}")

                    if i == 0:
                        step = AgentStep(
                            step_number=step_number,
                            timestamp=datetime.now(),
                            screenshot_path=screenshot_path,
                            vlm_response=vlm_response.text,
                            action=action,
                            action_result=result,
                            reasoning=action.reasoning,
                            token_usage=vlm_response.usage,
                        )
                        self.steps.append(step)
                        if on_step:
                            on_step(step)

                if self.state != AgentState.RUNNING:
                    break

                # Capture result screenshot
                time.sleep(0.5)
                screenshot_after, _ = self._capture_screenshot_cua(step_number)

                # Record turn
                turn_history.append(TurnRecord(
                    screenshot_before=screenshot_before,
                    model_response=vlm_response.text,
                    actions_summary="; ".join(action_summaries),
                    results_summary="; ".join(result_summaries),
                    screenshot_after=screenshot_after,
                ))

                if self.config.step_delay > 0:
                    time.sleep(self.config.step_delay)

        except KeyboardInterrupt:
            self.state = AgentState.PAUSED

        except Exception as e:
            self.console.print(f"[red]Explore error: {e}[/]")
            import traceback
            traceback.print_exc()
            self.state = AgentState.FAILED

        # Restore handlers
        signal.signal(signal.SIGINT, prev_sigint)
        if self._hotkey_monitor:
            self._hotkey_monitor.stop()
            self._hotkey_monitor = None
        if self._cursor_overlay:
            self._cursor_overlay.stop()
            self._cursor_overlay = None
        if self._action_notifier:
            self._action_notifier.stop()
            self._action_notifier = None

        # Generate guidebook even if exploration was interrupted
        self.console.print(f"\n[bold]Generating guidebook ({len(app_map.pages)} pages discovered)...[/]")
        guidebook_path = generate_guidebook(app_map, output_path)
        self.console.print(Panel(
            f"[green]Guidebook saved to: {guidebook_path}[/]\n"
            f"Pages: {len(app_map.pages)}\n"
            f"Use with: --guidebook {guidebook_path}",
            title="Exploration Complete"
        ))

        return guidebook_path


    def _capture_screenshot_cua(self, step_number: int) -> Tuple[str, Optional[Path]]:
        """Capture screenshot for CUA mode.

        Scales to target height (default 1080px) maintaining aspect ratio.
        Stores inverse scale factor so CUA action coordinates can be mapped
        back to native screen resolution.
        """
        # Pause overlays to prevent them from appearing in screenshot
        if self._cursor_overlay:
            self._cursor_overlay.pause()
        if self._action_notifier:
            self._action_notifier.pause()

        time.sleep(0.05)

        # Capture screenshot
        if self.operator:
            img = self.operator.screenshot()
        else:
            img = self.screen.capture(scale=self.config.screenshot_scale)

        # Resume overlays
        if self._cursor_overlay:
            self._cursor_overlay.resume()
        if self._action_notifier:
            self._action_notifier.resume()

        original_w, original_h = img.size

        # Save to disk (original resolution)
        screenshot_path = None
        if self.config.save_screenshots:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = self.config.screenshot_dir / f"step_{step_number:03d}_{timestamp}.png"
            img.save(screenshot_path, format="PNG", optimize=True)

        # Scale to exact display_width x display_height from config
        # The model expects images matching the declared display dimensions
        if self.cua_client:
            target_width = self.cua_client.config.display_width
            target_height = self.cua_client.config.display_height
        elif self.openai_vlm:
            target_width = self.openai_vlm.config.display_width
            target_height = self.openai_vlm.config.display_height
        else:
            target_width = 1920
            target_height = 1080
        if original_w != target_width or original_h != target_height:
            img = img.resize((target_width, target_height), Image.LANCZOS)
            # Store scale factors for coordinate mapping:
            # model returns coords in display space → multiply to get native
            self._vlm_scale_factor_x = original_w / target_width
            self._vlm_scale_factor_y = original_h / target_height
        else:
            self._vlm_scale_factor_x = 1.0
            self._vlm_scale_factor_y = 1.0
        # Legacy single scale factor (used by _rescale_action_coords)
        self._vlm_scale_factor = self._vlm_scale_factor_y

        # Encode as base64 PNG
        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        base64_img = base64.standard_b64encode(buffer.getvalue()).decode("utf-8")

        return base64_img, screenshot_path

    def run_cua(
        self,
        task: str,
        on_step: Optional[Callable[[AgentStep], None]] = None,
        on_action: Optional[Callable[[AnyAction], bool]] = None
    ) -> List[AgentStep]:
        """
        Run the agent using GPT-5.4 Computer Use Agent (CUA) mode.

        The CUA model drives the loop: it returns structured computer_call
        items with batched actions[], we execute them, send a screenshot,
        and repeat until the model stops issuing computer_calls.

        Args:
            task: Natural language task description
            on_step: Callback after each step
            on_action: Callback before action execution

        Returns:
            List of all steps taken
        """
        self.state = AgentState.RUNNING
        self.current_task = task
        self.steps = []

        # Install SIGINT handler so Ctrl+C interrupts blocking I/O on Windows
        prev_sigint = signal.getsignal(signal.SIGINT)

        def _sigint_handler(signum, frame):
            self.state = AgentState.PAUSED
            raise KeyboardInterrupt

        signal.signal(signal.SIGINT, _sigint_handler)

        # Start hotkey monitor for stopping agent (Ctrl+Alt)
        from .core.hotkey import HotkeyMonitor
        self._hotkey_monitor = HotkeyMonitor(self._on_stop_hotkey)
        self._hotkey_monitor.start()
        self.console.print("[dim]Press Ctrl+C or Ctrl+Alt to stop the agent[/]")

        # Start cursor overlay for visual feedback
        if self.config.show_cursor_overlay:
            from .core.cursor_overlay import CursorOverlay
            self._cursor_overlay = CursorOverlay(color="red", size=50, line_width=4)
            self._cursor_overlay.start()

        # Start action notifier
        if self.config.show_action_notifier:
            from .core.action_notifier import ActionNotifier
            self._action_notifier = ActionNotifier()
            self._action_notifier.start()
            self._action_notifier.show_action("thinking", f"CUA: {task[:50]}...")

        self.console.print(Panel(
            f"[bold]Task:[/] {task}\n[dim]Provider: OpenAI CUA ({self.cua_client.config.model})[/]",
            title="GUI Agent Started (CUA Mode)"
        ))

        step_number = 0

        try:
            # Send initial task to CUA
            self.console.print("[dim]Sending task to CUA model...[/]")
            response = self.cua_client.start(task)

            while self.state == AgentState.RUNNING and step_number < self.config.max_steps:
                # Extract computer_call from response
                computer_call = self.cua_client.extract_computer_call(response)

                if computer_call is None:
                    # Model is done — extract final text
                    final_text = self.cua_client.extract_text(response)
                    self.state = AgentState.COMPLETED
                    if final_text:
                        self.console.print(f"[green]CUA final output:[/] {_sanitize_text(final_text[:200])}")
                    break

                # Get actions from the computer_call.
                # Native CUA has .actions[] (batched), translated format has .action (singular).
                if hasattr(computer_call, 'actions') and computer_call.actions:
                    actions_raw = computer_call.actions
                elif hasattr(computer_call, 'action') and computer_call.action:
                    actions_raw = [computer_call.action]
                else:
                    actions_raw = []
                if not actions_raw:
                    # Empty actions — just send screenshot
                    self.console.print("[dim]CUA requested screenshot (no actions)[/]")
                    step_number += 1
                    base64_img, screenshot_path = self._capture_screenshot_cua(step_number)
                    step = AgentStep(
                        step_number=step_number,
                        timestamp=datetime.now(),
                        screenshot_path=screenshot_path,
                        vlm_response="screenshot request",
                        action=ScreenshotAction(reasoning="CUA screenshot request", action_type=ActionType.SCREENSHOT),
                        action_result=ActionResult(success=True, action=ScreenshotAction(action_type=ActionType.SCREENSHOT)),
                        reasoning="CUA requested initial screenshot",
                    )
                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)
                    response = self.cua_client.send_screenshot(
                        previous_response_id=response.id,
                        call_id=computer_call.call_id,
                        screenshot_base64=base64_img,
                    )
                    continue

                # Map CUA actions to our Action types
                mapped_actions = map_cua_actions(actions_raw)

                # Rescale coordinates from model's image space to native screen space
                for action in mapped_actions:
                    self._rescale_action_coords(action)

                # Execute all actions in order (batched)
                for i, action in enumerate(mapped_actions):
                    step_number += 1

                    if self.state != AgentState.RUNNING:
                        break

                    # Show in notifier
                    if self._action_notifier:
                        detail = self._get_action_detail(action)
                        self._action_notifier.show_step(step_number, action.action_type.value, detail)

                    # Confirm callback
                    if on_action and not on_action(action):
                        self.console.print("[yellow]Action skipped by callback[/]")
                        continue

                    # Skip execution for screenshot actions (just capture)
                    if isinstance(action, ScreenshotAction):
                        self.console.print(f"[dim]Step {step_number}: CUA screenshot request[/]")
                        result = ActionResult(success=True, action=action)
                    else:
                        self.console.print(f"[dim]Step {step_number}: Executing {action.action_type.value}[/]")
                        result = self._execute_action(action)

                    step = AgentStep(
                        step_number=step_number,
                        timestamp=datetime.now(),
                        screenshot_path=None,
                        vlm_response=str(getattr(actions_raw[i], 'type', '')),
                        action=action,
                        action_result=result,
                        reasoning=action.reasoning,
                    )

                    self._display_step(step)
                    self.steps.append(step)
                    if on_step:
                        on_step(step)

                if self.state != AgentState.RUNNING:
                    break

                # Capture screenshot after all actions executed
                self.console.print("[dim]Capturing screenshot for CUA...[/]")
                base64_img, screenshot_path = self._capture_screenshot_cua(step_number)

                # Update the last step's screenshot path
                if self.steps:
                    self.steps[-1].screenshot_path = screenshot_path

                # Send screenshot back to CUA
                response = self.cua_client.send_screenshot(
                    previous_response_id=response.id,
                    call_id=computer_call.call_id,
                    screenshot_base64=base64_img,
                )

                # Step delay
                if self.config.step_delay > 0:
                    time.sleep(self.config.step_delay)

        except KeyboardInterrupt:
            self.state = AgentState.PAUSED

        except Exception as e:
            self.console.print(f"[red]CUA error: {e}[/]")
            self.state = AgentState.FAILED

        # Restore original SIGINT handler
        signal.signal(signal.SIGINT, prev_sigint)

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
            self.console.print(Panel("[green]Task completed successfully![/]", title="CUA Done"))
        elif self.state == AgentState.FAILED:
            self.console.print(Panel("[red]Task failed[/]", title="CUA Failed"))
        elif self.state == AgentState.PAUSED:
            self.console.print(Panel("[yellow]Interrupted by user[/]", title="CUA Stopped"))
        else:
            self.console.print(Panel("[yellow]Max steps reached[/]", title="CUA Stopped"))

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
        base64_img, screenshot_path, screen_info, _ = self._capture_screenshot(0)

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
        base64_img, screenshot_path, screen_info, _ = self._capture_screenshot(0)

        response = self.vlm.ground_element(
            screenshot=screenshot_path or base64_img,
            element_description=element_description,
            screen_info=screen_info
        )

        try:
            data = json.loads(response.text)
            if data.get("found"):
                x = round(data["x"] * self._vlm_scale_factor)
                y = round(data["y"] * self._vlm_scale_factor)
                return (x, y)
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
