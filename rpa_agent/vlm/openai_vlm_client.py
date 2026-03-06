"""
OpenAI Responses API client for CUA-style GUI automation.

Simulates the official GPT-5.4 Computer Use loop via the Copilot API proxy.
Since the proxy doesn't support `previous_response_id` or the `computer` tool
for multi-turn, we simulate the CUA protocol by:

1. Prompting GPT-5.4 to return CUA-format actions (click, type, scroll, etc.)
2. Passing full conversation history (screenshots + actions) each turn instead
   of using `previous_response_id`
3. The model fully controls the flow — it decides what actions to take and when
   to request screenshots, just like the official CUA loop.

History is structured per turn:
  [user: screenshot_before + "execute these actions"]
  [assistant: {"actions": [...], "status": "continue"}]
  [user: screenshot_after + execution results]

Old screenshots are JPEG-compressed to manage payload size. Only the most
recent N turns keep full-resolution screenshots.
"""

import base64
import io
import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.request import Request, urlopen


# System prompt that makes GPT-5.4 behave like a CUA agent
CUA_SYSTEM_PROMPT = """You are a computer use agent. You control a Windows desktop by looking at screenshots and returning actions.

IMPORTANT: You must respond with ONLY a JSON object. No markdown, no explanation outside the JSON.

## Response Format

Return a JSON object with:
- "reasoning": Brief description of what you see and what you plan to do
- "actions": Array of action objects to execute in order
- "status": "continue" (more actions needed) or "done" (task complete) or "fail" (task cannot be completed)

Example responses:

First turn (need to see the screen):
{"reasoning": "I need to see the current screen state first.", "actions": [{"type": "screenshot"}], "status": "continue"}

Clicking a button:
{"reasoning": "I can see the Next button at coordinates (500, 300). Clicking it.", "actions": [{"type": "click", "x": 500, "y": 300, "button": "left"}], "status": "continue"}

Multiple actions in sequence:
{"reasoning": "I need to click the search box then type the query.", "actions": [{"type": "click", "x": 400, "y": 200, "button": "left"}, {"type": "type", "text": "hello world"}], "status": "continue"}

Task complete:
{"reasoning": "The form has been submitted successfully. I can see the confirmation page.", "actions": [], "status": "done"}

## Available Actions

- {"type": "click", "x": int, "y": int, "button": "left"|"right"} — Click at coordinates
- {"type": "double_click", "x": int, "y": int} — Double-click at coordinates
- {"type": "type", "text": "string"} — Type text (assumes field is focused)
- {"type": "keypress", "keys": ["key1", "key2"]} — Press key(s). Single key or combo (e.g. ["CTRL", "a"])
- {"type": "scroll", "x": int, "y": int, "scroll_x": int, "scroll_y": int} — Scroll. scroll_y negative=up, positive=down. Units are pixels (120=one notch)
- {"type": "drag", "path": [{"x": int, "y": int}, {"x": int, "y": int}]} — Drag from start to end
- {"type": "move", "x": int, "y": int} — Move mouse cursor
- {"type": "wait"} — Wait ~2 seconds (default)
- {"type": "wait", "seconds": 30} — Wait a specific number of seconds (up to 120). Use this for videos, loading screens, or timed content.
- {"type": "screenshot"} — Request a fresh screenshot (no-op, you'll get one after actions run)

## Rules

1. Coordinates are in screen pixels. (0,0) is top-left.
2. The screenshot shows the EXACT current state. Use it to determine coordinates.
3. Execute ALL returned actions before the next screenshot is taken.
4. If you need to see the screen first, return [{"type": "screenshot"}].
5. Be precise with click coordinates — aim for the CENTER of the target element.
6. When a task is done, set status to "done" and empty actions.
7. If stuck, try a different approach rather than repeating the same failed action.
8. Look at the previous screenshots to see what changed after your actions. If the screen didn't change, your action likely missed the target — adjust coordinates or try a different approach.
9. For video/timed content: if you see a video playing and a button (like NEXT) is disabled, use {"type": "wait", "seconds": 30} to wait for the video to finish. Then take another screenshot to check. Repeat until the button enables. Do NOT click a disabled button — it won't work.
10. For training courses with gated sections: always wait for the current section's content to fully complete before trying to advance. Look for visual cues like progress bars, enabled/disabled button states, and checkmarks.
"""


@dataclass
class OpenAIVLMConfig:
    """Configuration for the OpenAI VLM client."""
    base_url: str = "http://localhost:4141/v1"
    api_key: str = "dummy"
    model: str = "gpt-5.4"
    max_tokens: int = 4096
    temperature: float = 0.1
    display_width: int = 1920
    display_height: int = 1080


@dataclass
class OpenAIVLMResponse:
    """Response from the OpenAI Responses API."""
    text: str
    raw_response: Dict[str, Any]
    usage: Dict[str, int]
    actions: List[Dict[str, Any]]
    status: str  # "continue", "done", or "fail"


@dataclass
class TurnRecord:
    """Record of one complete turn in the CUA loop.

    Each turn has:
    - screenshot_before: the screen state the model saw (base64 PNG)
    - actions: what the model decided to do
    - results: execution feedback (success/failure per action)
    - screenshot_after: the screen state after actions executed (base64 PNG)
    """
    screenshot_before: str  # base64 PNG
    model_response: str  # raw model JSON text
    actions_summary: str  # human-readable summary of actions taken
    results_summary: str  # execution results
    screenshot_after: str  # base64 PNG


def compress_screenshot(base64_png: str, quality: int = 30, max_width: int = 800) -> str:
    """Compress a base64 PNG screenshot to a smaller JPEG for history.

    Reduces resolution and uses JPEG compression to minimize payload size.
    """
    from PIL import Image

    png_data = base64.b64decode(base64_png)
    img = Image.open(io.BytesIO(png_data))

    # Downscale if wider than max_width
    if img.width > max_width:
        ratio = max_width / img.width
        new_size = (max_width, int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    # Convert to JPEG
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality, optimize=True)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


class OpenAIVLMClient:
    """
    CUA-style client using the OpenAI Responses API.

    Simulates the official Computer Use loop. Each turn is structured:
    1. User sends screenshot → model returns actions
    2. We execute actions → capture result screenshot
    3. We record the full turn (before screenshot, actions, results, after screenshot)
    4. On next turn, we send the last N turns as history so the model can learn

    Since the Copilot API proxy doesn't support `previous_response_id`,
    we rebuild the conversation from turn history each request.
    """

    MAX_HISTORY_TURNS = 5  # Keep last 5 turns in conversation

    def __init__(self, config: Optional[OpenAIVLMConfig] = None):
        self.config = config or OpenAIVLMConfig()
        self._responses_url = f"{self.config.base_url.rstrip('/')}/responses"

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send a POST request to the Responses API endpoint."""
        body = json.dumps(payload).encode("utf-8")
        req = Request(
            self._responses_url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
            method="POST",
        )
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data

    def send(
        self,
        task: str,
        current_screenshot: str,
        turn_history: List[TurnRecord],
        system_prompt_override: Optional[str] = None,
        extra_context: Optional[str] = None,
    ) -> OpenAIVLMResponse:
        """
        Send the current state to the model with full turn history.

        Args:
            task: The task description.
            current_screenshot: Base64 PNG of current screen state.
            turn_history: Previous turns for context (last N kept).
            system_prompt_override: Replace the default CUA system prompt entirely.
            extra_context: Additional context appended to system prompt (e.g., guidebook).

        Returns:
            OpenAIVLMResponse with parsed actions and status.
        """
        conversation = self._build_conversation(
            task, current_screenshot, turn_history,
            system_prompt_override=system_prompt_override,
            extra_context=extra_context,
        )

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "input": conversation,
            "temperature": self.config.temperature,
        }
        if self.config.max_tokens:
            payload["max_output_tokens"] = self.config.max_tokens

        data = self._post(payload)

        text = self._extract_text(data)
        usage = data.get("usage", {})
        actions, status = self._parse_cua_response(text)

        return OpenAIVLMResponse(
            text=text,
            raw_response=data,
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
            actions=actions,
            status=status,
        )

    def _build_conversation(
        self,
        task: str,
        current_screenshot: str,
        turn_history: List[TurnRecord],
        system_prompt_override: Optional[str] = None,
        extra_context: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Build the full conversation from turn history.

        Structure:
        1. Developer (system) message with CUA prompt
        2. User message with task
        3. For each past turn:
           - User: "Before screenshot" (compressed) + action request
           - Assistant: model's action response
           - User: "After screenshot" (compressed) + execution results
        4. Current turn:
           - User: current screenshot (full res) + "What should I do?"
        """
        items: List[Dict[str, Any]] = []

        # 1. System prompt
        base_prompt = system_prompt_override if system_prompt_override else CUA_SYSTEM_PROMPT
        prompt = base_prompt + f"\n\nScreen dimensions: {self.config.display_width}x{self.config.display_height}\n"
        if extra_context:
            prompt += f"\n{extra_context}\n"
        items.append({
            "type": "message",
            "role": "developer",
            "content": prompt,
        })

        # 2. Task
        items.append({
            "type": "message",
            "role": "user",
            "content": f"Task: {task}",
        })

        # 3. Past turns — keep only last N, compress screenshots
        recent = turn_history[-self.MAX_HISTORY_TURNS:]
        for i, turn in enumerate(recent):
            is_last_turn = (i == len(recent) - 1)

            # Compress old turn screenshots, keep last turn less compressed
            if is_last_turn:
                before_img = compress_screenshot(turn.screenshot_before, quality=50, max_width=1200)
                after_img = compress_screenshot(turn.screenshot_after, quality=50, max_width=1200)
            else:
                before_img = compress_screenshot(turn.screenshot_before, quality=25, max_width=800)
                after_img = compress_screenshot(turn.screenshot_after, quality=25, max_width=800)

            # User: screenshot before + context
            items.append({
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{before_img}",
                    },
                    {
                        "type": "input_text",
                        "text": f"[Turn {i+1}] Screenshot before actions. What should I do?",
                    },
                ],
            })

            # Assistant: model's response
            items.append({
                "type": "message",
                "role": "assistant",
                "content": turn.model_response,
            })

            # User: screenshot after + execution results
            items.append({
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_image",
                        "image_url": f"data:image/jpeg;base64,{after_img}",
                    },
                    {
                        "type": "input_text",
                        "text": (
                            f"[Turn {i+1} result] Actions executed: {turn.actions_summary}\n"
                            f"Results: {turn.results_summary}\n"
                            f"Screenshot above shows the screen AFTER those actions."
                        ),
                    },
                ],
            })

        # 4. Current turn: full-resolution screenshot
        items.append({
            "type": "message",
            "role": "user",
            "content": [
                {
                    "type": "input_image",
                    "image_url": f"data:image/png;base64,{current_screenshot}",
                },
                {
                    "type": "input_text",
                    "text": "Current screenshot. What actions should I take next?",
                },
            ],
        })

        return items

    @staticmethod
    def _extract_text(data: Dict[str, Any]) -> str:
        """Extract text content from a Responses API response."""
        texts = []
        for item in data.get("output", []):
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        texts.append(block.get("text", ""))
            elif "text" in item:
                texts.append(item["text"])
        return "\n".join(texts)

    @staticmethod
    def _parse_cua_response(text: str) -> Tuple[List[Dict[str, Any]], str]:
        """Parse CUA-style JSON response into (actions, status)."""
        text = text.strip()

        # Strip markdown code fence if present
        if text.startswith("```"):
            lines = text.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines).strip()

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    parsed = json.loads(text[start:end])
                except json.JSONDecodeError:
                    return [], "continue"
            else:
                return [], "continue"

        actions = parsed.get("actions", [])
        status = parsed.get("status", "continue")

        valid_actions = [a for a in actions if isinstance(a, dict) and "type" in a]
        return valid_actions, status
