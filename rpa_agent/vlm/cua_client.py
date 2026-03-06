"""
OpenAI GPT-5.4 Computer Use Agent (CUA) client.

Uses the OpenAI Responses API with the native `computer` tool
to drive GUI automation. The model returns structured `computer_call`
items with batched actions[], and we send back screenshots as
`computer_call_output`.

Endpoint: configurable (default http://localhost:4141/v1 — copilot-api proxy)

Uses raw HTTP requests instead of the OpenAI SDK to ensure compatibility
with the copilot-api translation layer.
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen


@dataclass
class CUAConfig:
    """Configuration for the CUA client."""
    base_url: str = "http://localhost:4141/v1"
    api_key: str = "dummy"
    model: str = "gpt-5.4"
    display_width: int = 1920  # Scaled image width sent to model
    display_height: int = 1080  # Scaled image height sent to model
    environment: str = "windows"  # "windows", "mac", "linux", "browser"


class CUAResponse:
    """Parsed response from the Responses API."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self.id: str = data.get("id", "")
        self.output: List[Dict[str, Any]] = data.get("output", [])
        self.status: str = data.get("status", "")
        self.model: str = data.get("model", "")
        self.usage: Dict[str, int] = data.get("usage", {})


class ComputerCall:
    """Parsed computer_call item from a response."""

    def __init__(self, data: Dict[str, Any]):
        self._data = data
        self.type: str = data.get("type", "computer_call")
        self.id: str = data.get("id", "")
        self.call_id: str = data.get("call_id", "")
        self.action: Dict[str, Any] = data.get("action", {})
        # For native CUA with batched actions
        self.actions: List[Dict[str, Any]] = data.get("actions", [])


class CUAClient:
    """
    Client for GPT-5.4 Computer Use Agent via OpenAI Responses API.

    Uses raw HTTP requests for compatibility with copilot-api proxy.

    Usage:
        client = CUAClient(CUAConfig(...))
        response = client.start("Open Chrome and go to google.com")
        # Loop: extract computer_call, execute actions, send screenshot
        response = client.send_screenshot(response.id, call_id, base64_png)
    """

    def __init__(self, config: Optional[CUAConfig] = None):
        self.config = config or CUAConfig()
        self._responses_url = f"{self.config.base_url.rstrip('/')}/responses"

    def _post(self, payload: Dict[str, Any]) -> CUAResponse:
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
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return CUAResponse(data)

    def start(self, task: str) -> CUAResponse:
        """
        Send the initial task to the CUA model.

        Args:
            task: Natural language task description.

        Returns:
            CUAResponse with .output and .id
        """
        payload = {
            "model": self.config.model,
            "tools": [{"type": "computer"}],
            "input": task,
        }
        return self._post(payload)

    def send_screenshot(
        self,
        previous_response_id: str,
        call_id: str,
        screenshot_base64: str,
    ) -> CUAResponse:
        """
        Send a screenshot back to the CUA model after executing actions.

        Args:
            previous_response_id: The .id from the previous response.
            call_id: The .call_id from the computer_call item.
            screenshot_base64: PNG screenshot encoded as base64 string.

        Returns:
            CUAResponse with .output and .id
        """
        payload = {
            "model": self.config.model,
            "tools": [{"type": "computer"}],
            "previous_response_id": previous_response_id,
            "input": [{
                "type": "computer_call_output",
                "call_id": call_id,
                "output": {
                    "type": "computer_screenshot",
                    "image_url": f"data:image/png;base64,{screenshot_base64}",
                },
            }],
        }
        return self._post(payload)

    @staticmethod
    def extract_computer_call(response: CUAResponse) -> Optional[ComputerCall]:
        """
        Extract the first computer_call item from a response.

        Returns None if the response has no computer_call (model is done).
        """
        for item in response.output:
            if isinstance(item, dict) and item.get("type") == "computer_call":
                return ComputerCall(item)
        return None

    @staticmethod
    def extract_text(response: CUAResponse) -> str:
        """
        Extract text content from a response (model's final answer or reasoning).
        """
        texts = []
        for item in response.output:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "message":
                for block in item.get("content", []):
                    if isinstance(block, dict) and block.get("type") == "output_text":
                        texts.append(block.get("text", ""))
            elif "text" in item:
                texts.append(item["text"])
        return "\n".join(texts)
