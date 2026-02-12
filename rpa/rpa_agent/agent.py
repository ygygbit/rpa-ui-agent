"""
Main GUI Agent orchestration.

The Agent class ties together:
- Screen capture
- VLM analysis
- Action parsing
- UI control execution
- Feedback loop and self-correction
"""

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
    screenshot_scale: float = 1.0  # Screenshot scaling
    save_screenshots: bool = True
    screenshot_dir: Path = field(default_factory=lambda: Path("./screenshots"))

    # Safety settings
    confirm_actions: bool = False  # Ask before executing
    dry_run: bool = False  # Don't actually execute actions

    # Retry settings
    max_retries: int = 3
    retry_delay: float = 1.0


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

        # Initialize components
        self.screen = ScreenCapture()
        self.controller = UIController()
        self.window_manager = WindowManager()
        self.vlm = VLMClient(self.config.vlm_config)
        self.parser = ActionParser()

        # State
        self.state = AgentState.IDLE
        self.steps: List[AgentStep] = []
        self.current_task: Optional[str] = None
        self._conversation_history: List[Dict[str, Any]] = []

        # Ensure screenshot directory exists
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def _capture_screenshot(self, step_number: int) -> Tuple[str, Path, Dict[str, int]]:
        """Capture screenshot and return base64, path, and screen info."""
        # Capture screenshot
        base64_img, screen_info = self.screen.capture_to_base64(
            scale=self.config.screenshot_scale
        )

        # Save screenshot if enabled
        screenshot_path = None
        if self.config.save_screenshots:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = self.config.screenshot_dir / f"step_{step_number:03d}_{timestamp}.png"
            self.screen.save_screenshot(screenshot_path, scale=self.config.screenshot_scale)

        return base64_img, screenshot_path, {
            "width": screen_info.width,
            "height": screen_info.height
        }

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

    def _build_feedback_message(self, result: ActionResult) -> str:
        """Build feedback message for the VLM based on action result."""
        if result.success:
            return f"Action {result.action.action_type.value} executed successfully."
        else:
            return f"Action {result.action.action_type.value} failed: {result.error}"

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
            if hasattr(step.action, 'text'):
                table.add_row("Text", step.action.text[:50])

        if step.action_result:
            status = "[green]Success[/]" if step.action_result.success else f"[red]Failed: {step.action_result.error}[/]"
            table.add_row("Result", status)

        if step.reasoning:
            table.add_row("Reasoning", step.reasoning[:100] + "..." if len(step.reasoning) > 100 else step.reasoning)

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

        self.console.print(Panel(f"[bold]Task:[/] {task}", title="GUI Agent Started"))

        step_number = 0
        retry_count = 0

        while self.state == AgentState.RUNNING and step_number < self.config.max_steps:
            step_number += 1
            timestamp = datetime.now()

            try:
                # 1. Capture screenshot
                self.console.print(f"\n[dim]Step {step_number}: Capturing screenshot...[/]")
                base64_img, screenshot_path, screen_info = self._capture_screenshot(step_number)

                # 2. Analyze with VLM
                self.console.print("[dim]Analyzing screenshot...[/]")
                vlm_response = self.vlm.analyze_screenshot(
                    screenshot=base64_img if not screenshot_path else screenshot_path,
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
                            action=FailAction(error="Max retries exceeded"),
                            error="Max retries exceeded"
                        )
                    self.steps.append(step)
                    continue

                # Reset retry count on successful parse
                retry_count = 0

                # 4. Confirm action if needed
                if on_action and not on_action(action):
                    self.console.print("[yellow]Action skipped by callback[/]")
                    continue

                if self.config.confirm_actions:
                    self.console.print(f"[yellow]Confirm action: {action.action_type.value}?[/]")
                    # In a real implementation, this would wait for user input

                # 5. Execute action
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
