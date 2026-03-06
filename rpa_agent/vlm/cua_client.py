"""
OpenAI GPT-5.4 Computer Use Agent (CUA) client.

Uses the OpenAI Responses API with the native `computer` tool
to drive GUI automation. The model returns structured `computer_call`
items with batched actions[], and we send back screenshots as
`computer_call_output`.

Endpoint: configurable (default http://localhost:23333/api/openai/v1)
"""

from dataclasses import dataclass
from typing import Any, Optional

from openai import OpenAI


@dataclass
class CUAConfig:
    """Configuration for the CUA client."""
    base_url: str = "http://localhost:23333/api/openai/v1"
    api_key: str = "dummy"
    model: str = "gpt-5.4"
    display_width: int = 1600
    display_height: int = 900
    environment: str = "windows"  # "windows", "mac", "linux", "browser"


class CUAClient:
    """
    Client for GPT-5.4 Computer Use Agent via OpenAI Responses API.

    Usage:
        client = CUAClient(CUAConfig(...))
        response = client.start("Open Chrome and go to google.com")
        # Loop: extract computer_call, execute actions, send screenshot
        response = client.send_screenshot(response.id, call_id, base64_png)
    """

    def __init__(self, config: Optional[CUAConfig] = None):
        self.config = config or CUAConfig()
        self.client = OpenAI(
            base_url=self.config.base_url,
            api_key=self.config.api_key,
        )

    def _tool_definition(self) -> dict:
        """Build the computer tool definition."""
        return {
            "type": "computer",
            "display_width": self.config.display_width,
            "display_height": self.config.display_height,
            "environment": self.config.environment,
        }

    def start(self, task: str) -> Any:
        """
        Send the initial task to the CUA model.

        Args:
            task: Natural language task description.

        Returns:
            OpenAI response object with .output and .id
        """
        response = self.client.responses.create(
            model=self.config.model,
            tools=[self._tool_definition()],
            input=[{
                "role": "user",
                "content": task,
            }],
            truncation="auto",
        )
        return response

    def send_screenshot(
        self,
        previous_response_id: str,
        call_id: str,
        screenshot_base64: str,
    ) -> Any:
        """
        Send a screenshot back to the CUA model after executing actions.

        Args:
            previous_response_id: The .id from the previous response.
            call_id: The .call_id from the computer_call item.
            screenshot_base64: PNG screenshot encoded as base64 string.

        Returns:
            OpenAI response object with .output and .id
        """
        response = self.client.responses.create(
            model=self.config.model,
            tools=[self._tool_definition()],
            previous_response_id=previous_response_id,
            input=[{
                "type": "computer_call_output",
                "call_id": call_id,
                "output": {
                    "type": "computer_screenshot",
                    "image_url": f"data:image/png;base64,{screenshot_base64}",
                    "detail": "original",
                },
            }],
            truncation="auto",
        )
        return response

    @staticmethod
    def extract_computer_call(response: Any) -> Optional[Any]:
        """
        Extract the first computer_call item from a response.

        Returns None if the response has no computer_call (model is done).
        """
        for item in response.output:
            if item.type == "computer_call":
                return item
        return None

    @staticmethod
    def extract_text(response: Any) -> str:
        """
        Extract text content from a response (model's final answer or reasoning).
        """
        texts = []
        for item in response.output:
            if hasattr(item, "text"):
                texts.append(item.text)
            elif item.type == "message" and hasattr(item, "content"):
                for block in item.content:
                    if hasattr(block, "text"):
                        texts.append(block.text)
        return "\n".join(texts)
