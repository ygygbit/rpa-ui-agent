"""
Action parser for extracting structured actions from VLM output.

Parses natural language or JSON-formatted action descriptions
into executable Action objects.
"""

import json
import re
from typing import List, Optional, Tuple

from .definitions import (
    Action, ActionType, AnyAction,
    ClickAction, DoubleClickAction, RightClickAction,
    DragAction, ScrollAction, HoverAction,
    MoveMouseAction, ClickNowAction, DoubleClickNowAction, RightClickNowAction,
    TypeAction, KeyAction, HotkeyAction,
    FocusWindowAction, WaitAction, ScreenshotAction,
    DoneAction, FailAction
)


class ActionParser:
    """
    Parser for extracting actions from VLM output.

    Supports multiple formats:
    1. JSON format: {"action": "click", "x": 100, "y": 200, ...}
    2. Structured text: ACTION: click(x=100, y=200)
    3. Natural language with coordinate extraction
    """

    # Patterns for coordinate extraction
    COORD_PATTERN = re.compile(r'\(?\s*(\d+)\s*,\s*(\d+)\s*\)?')
    CLICK_PATTERN = re.compile(r'click\s*(?:at|on)?\s*\(?\s*(\d+)\s*,\s*(\d+)\s*\)?', re.I)
    TYPE_PATTERN = re.compile(r'type\s*[:\s]+["\'](.+?)["\']', re.I)
    KEY_PATTERN = re.compile(r'press\s+(?:key\s+)?(\w+)', re.I)
    SCROLL_PATTERN = re.compile(r'scroll\s+(up|down|left|right)(?:\s+(\d+))?', re.I)

    def parse(self, text: str) -> Tuple[Optional[AnyAction], str]:
        """
        Parse VLM output to extract action.

        Args:
            text: VLM output text

        Returns:
            Tuple of (parsed action or None, reasoning/error message)
        """
        # Try JSON parsing first
        action, msg = self._try_json_parse(text)
        if action:
            return action, msg

        # Try structured format
        action, msg = self._try_structured_parse(text)
        if action:
            return action, msg

        # Try natural language parsing
        action, msg = self._try_natural_language_parse(text)
        if action:
            return action, msg

        return None, f"Could not parse action from: {text[:200]}"

    def _try_json_parse(self, text: str) -> Tuple[Optional[AnyAction], str]:
        """Try to parse JSON-formatted action."""
        # Find JSON object in text
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if not json_match:
            return None, "No JSON found"

        try:
            data = json.loads(json_match.group())
        except json.JSONDecodeError:
            return None, "Invalid JSON"

        action_type = data.get("action", data.get("action_type", "")).lower()
        reasoning = data.get("reasoning", data.get("thought", ""))
        confidence = float(data.get("confidence", 1.0))

        try:
            if action_type in ("click", "left_click"):
                return ClickAction(
                    x=int(data.get("x", 0)),
                    y=int(data.get("y", 0)),
                    element_description=data.get("element", ""),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.CLICK
                ), "Parsed click action"

            elif action_type == "double_click":
                return DoubleClickAction(
                    x=int(data.get("x", 0)),
                    y=int(data.get("y", 0)),
                    element_description=data.get("element", ""),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.DOUBLE_CLICK
                ), "Parsed double click action"

            elif action_type == "right_click":
                return RightClickAction(
                    x=int(data.get("x", 0)),
                    y=int(data.get("y", 0)),
                    element_description=data.get("element", ""),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.RIGHT_CLICK
                ), "Parsed right click action"

            elif action_type == "drag":
                return DragAction(
                    start_x=int(data.get("start_x", data.get("x1", 0))),
                    start_y=int(data.get("start_y", data.get("y1", 0))),
                    end_x=int(data.get("end_x", data.get("x2", 0))),
                    end_y=int(data.get("end_y", data.get("y2", 0))),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.DRAG
                ), "Parsed drag action"

            elif action_type == "scroll":
                return ScrollAction(
                    direction=data.get("direction", "down"),
                    amount=int(data.get("amount", data.get("clicks", 3))),
                    x=data.get("x"),
                    y=data.get("y"),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.SCROLL
                ), "Parsed scroll action"

            elif action_type == "hover":
                return HoverAction(
                    x=int(data.get("x", 0)),
                    y=int(data.get("y", 0)),
                    element_description=data.get("element", ""),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.HOVER
                ), "Parsed hover action"

            elif action_type in ("move_mouse", "move"):
                return MoveMouseAction(
                    direction=data.get("direction", ""),
                    distance=data.get("distance", "medium"),
                    target_element=data.get("target_element", data.get("target", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.MOVE_MOUSE
                ), "Parsed move mouse action"

            elif action_type == "click_now":
                return ClickNowAction(
                    element_description=data.get("element", data.get("element_description", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.CLICK_NOW
                ), "Parsed click now action"

            elif action_type == "double_click_now":
                return DoubleClickNowAction(
                    element_description=data.get("element", data.get("element_description", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.DOUBLE_CLICK_NOW
                ), "Parsed double click now action"

            elif action_type == "right_click_now":
                return RightClickNowAction(
                    element_description=data.get("element", data.get("element_description", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.RIGHT_CLICK_NOW
                ), "Parsed right click now action"

            elif action_type == "type":
                return TypeAction(
                    text=data.get("text", ""),
                    press_enter=data.get("press_enter", data.get("enter", False)),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.TYPE
                ), "Parsed type action"

            elif action_type in ("press_key", "key", "press"):
                return KeyAction(
                    key=data.get("key", ""),
                    modifiers=data.get("modifiers", []),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.PRESS_KEY
                ), "Parsed key action"

            elif action_type == "hotkey":
                return HotkeyAction(
                    keys=data.get("keys", []),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.HOTKEY
                ), "Parsed hotkey action"

            elif action_type in ("focus_window", "focus", "switch_window"):
                return FocusWindowAction(
                    window_title=data.get("window_title", data.get("title", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.FOCUS_WINDOW
                ), "Parsed focus window action"

            elif action_type == "wait":
                return WaitAction(
                    seconds=float(data.get("seconds", data.get("duration", 1.0))),
                    reason=data.get("reason", ""),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.WAIT
                ), "Parsed wait action"

            elif action_type == "screenshot":
                return ScreenshotAction(
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.SCREENSHOT
                ), "Parsed screenshot action"

            elif action_type in ("done", "complete", "finished", "success"):
                return DoneAction(
                    summary=data.get("summary", data.get("message", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.DONE
                ), "Task completed"

            elif action_type in ("fail", "error", "failed"):
                return FailAction(
                    error=data.get("error", data.get("message", "")),
                    reasoning=reasoning,
                    confidence=confidence,
                    action_type=ActionType.FAIL
                ), "Task failed"

        except (ValueError, TypeError) as e:
            return None, f"Error parsing action: {e}"

        return None, f"Unknown action type: {action_type}"

    def _try_structured_parse(self, text: str) -> Tuple[Optional[AnyAction], str]:
        """Try to parse structured format like 'ACTION: click(100, 200)'."""
        # Look for ACTION: pattern
        action_match = re.search(r'ACTION:\s*(\w+)\s*\(([^)]*)\)', text, re.I)
        if not action_match:
            return None, "No structured action found"

        action_name = action_match.group(1).lower()
        params_str = action_match.group(2)

        # Extract reasoning if present
        reasoning_match = re.search(r'REASONING?:\s*(.+?)(?:\n|$)', text, re.I)
        reasoning = reasoning_match.group(1) if reasoning_match else ""

        # Parse parameters
        params = {}
        for param in params_str.split(','):
            if '=' in param:
                key, value = param.split('=', 1)
                params[key.strip()] = value.strip().strip('"\'')
            else:
                # Positional parameter
                coord_match = self.COORD_PATTERN.search(param)
                if coord_match:
                    params['x'] = int(coord_match.group(1))
                    params['y'] = int(coord_match.group(2))

        # Build action data and use JSON parser
        data = {"action": action_name, "reasoning": reasoning, **params}
        return self._try_json_parse(json.dumps(data))

    def _try_natural_language_parse(self, text: str) -> Tuple[Optional[AnyAction], str]:
        """Try to parse natural language action description."""
        text_lower = text.lower()

        # Extract reasoning (everything before action keywords)
        reasoning = text

        # Check for click actions
        click_match = self.CLICK_PATTERN.search(text)
        if click_match:
            return ClickAction(
                x=int(click_match.group(1)),
                y=int(click_match.group(2)),
                reasoning=reasoning,
                action_type=ActionType.CLICK
            ), "Parsed click from natural language"

        # Check for type actions
        type_match = self.TYPE_PATTERN.search(text)
        if type_match:
            return TypeAction(
                text=type_match.group(1),
                press_enter="enter" in text_lower,
                reasoning=reasoning,
                action_type=ActionType.TYPE
            ), "Parsed type from natural language"

        # Check for scroll actions
        scroll_match = self.SCROLL_PATTERN.search(text)
        if scroll_match:
            return ScrollAction(
                direction=scroll_match.group(1).lower(),
                amount=int(scroll_match.group(2)) if scroll_match.group(2) else 3,
                reasoning=reasoning,
                action_type=ActionType.SCROLL
            ), "Parsed scroll from natural language"

        # Check for key press
        key_match = self.KEY_PATTERN.search(text)
        if key_match:
            return KeyAction(
                key=key_match.group(1).lower(),
                reasoning=reasoning,
                action_type=ActionType.PRESS_KEY
            ), "Parsed key press from natural language"

        # Check for done/complete
        if any(word in text_lower for word in ["done", "complete", "finished", "task completed"]):
            return DoneAction(
                summary=text,
                reasoning=reasoning,
                action_type=ActionType.DONE
            ), "Task completed"

        # Check for failure
        if any(word in text_lower for word in ["cannot", "unable", "failed", "impossible"]):
            return FailAction(
                error=text,
                reasoning=reasoning,
                action_type=ActionType.FAIL
            ), "Task failed"

        return None, "Could not parse natural language action"

    def parse_multiple(self, text: str) -> List[AnyAction]:
        """
        Parse multiple actions from text (for action sequences).

        Args:
            text: Text potentially containing multiple actions

        Returns:
            List of parsed actions
        """
        actions = []

        # Try to find JSON array
        array_match = re.search(r'\[([^\[\]]*)\]', text, re.DOTALL)
        if array_match:
            try:
                items = json.loads(f"[{array_match.group(1)}]")
                for item in items:
                    action, _ = self._try_json_parse(json.dumps(item))
                    if action:
                        actions.append(action)
                return actions
            except json.JSONDecodeError:
                pass

        # Try line-by-line parsing
        for line in text.split('\n'):
            if line.strip():
                action, _ = self.parse(line)
                if action:
                    actions.append(action)

        return actions
