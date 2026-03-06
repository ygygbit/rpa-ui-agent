"""
OpenAI Responses API VLM client for GUI understanding.

Uses GPT-5.4 (or other OpenAI models) via the Responses API as a
standard Vision-Language Model — sends screenshots as images and gets
back structured JSON action responses, just like the Anthropic provider.

This avoids the CUA `computer` tool protocol entirely, which the
Copilot API proxy cannot handle for multi-turn conversations.

Endpoint: configurable (default http://localhost:4141/v1 — copilot-api proxy)
"""

import json
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen


@dataclass
class OpenAIVLMConfig:
    """Configuration for the OpenAI VLM client."""
    base_url: str = "http://localhost:4141/v1"
    api_key: str = "dummy"
    model: str = "gpt-5.4"
    max_tokens: int = 4096
    temperature: float = 0.1


@dataclass
class OpenAIVLMResponse:
    """Response from the OpenAI Responses API."""
    text: str
    raw_response: Dict[str, Any]
    usage: Dict[str, int]


class OpenAIVLMClient:
    """
    VLM client using the OpenAI Responses API.

    Sends screenshots as input_image content blocks and receives
    structured JSON action responses — same interface as VLMClient
    but using the OpenAI API format instead of Anthropic.

    Usage:
        client = OpenAIVLMClient(OpenAIVLMConfig(base_url="http://localhost:4141/v1"))
        response = client.analyze_screenshot(
            screenshot_base64="...",
            task="Click the submit button",
            screen_info={"width": 1920, "height": 1080},
            history=[...],
            system_prompt="You are a GUI automation agent..."
        )
    """

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
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data

    def analyze_screenshot(
        self,
        screenshot_base64: str,
        task: str,
        screen_info: Optional[Dict[str, int]] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        system_prompt: Optional[str] = None,
        media_type: str = "image/png",
    ) -> OpenAIVLMResponse:
        """
        Analyze a screenshot and determine next action.

        Builds an OpenAI Responses API input array with:
        - Developer instructions (system prompt)
        - Conversation history (previous screenshot+response pairs)
        - Current screenshot + task text

        Args:
            screenshot_base64: Base64-encoded screenshot image.
            task: Task description or instruction.
            screen_info: Screen dimensions {"width": w, "height": h}.
            history: Previous conversation history in Anthropic message format.
                     Each entry is {"role": "user"|"assistant", "content": ...}.
            system_prompt: System prompt for the model.
            media_type: MIME type for the screenshot (default image/png).

        Returns:
            OpenAIVLMResponse with .text containing the model's action JSON.
        """
        input_items: List[Dict[str, Any]] = []

        # 1. System prompt as developer instructions
        if system_prompt:
            input_items.append({
                "type": "message",
                "role": "developer",
                "content": system_prompt,
            })

        # 2. Conversation history — convert from Anthropic format to Responses format
        if history:
            for msg in history:
                role = msg["role"]
                content = msg["content"]

                if role == "assistant":
                    # Assistant responses are plain text
                    text = content if isinstance(content, str) else str(content)
                    input_items.append({
                        "type": "message",
                        "role": "assistant",
                        "content": text,
                    })
                elif role == "user":
                    # User messages may contain images + text
                    if isinstance(content, list):
                        # Anthropic format: [{"type": "image", "source": {...}}, {"type": "text", "text": ...}]
                        resp_content = []
                        for block in content:
                            if block.get("type") == "image":
                                source = block.get("source", {})
                                b64_data = source.get("data", "")
                                mt = source.get("media_type", "image/png")
                                resp_content.append({
                                    "type": "input_image",
                                    "image_url": f"data:{mt};base64,{b64_data}",
                                })
                            elif block.get("type") == "text":
                                resp_content.append({
                                    "type": "input_text",
                                    "text": block.get("text", ""),
                                })
                        input_items.append({
                            "type": "message",
                            "role": "user",
                            "content": resp_content,
                        })
                    else:
                        input_items.append({
                            "type": "message",
                            "role": "user",
                            "content": str(content),
                        })

        # 3. Current turn: screenshot + task
        user_text = f"Task: {task}\n"
        if screen_info:
            user_text += f"\nScreen dimensions: {screen_info['width']}x{screen_info['height']}\n"
        user_text += "\nAnalyze this screenshot and determine the next action to accomplish the task."

        current_content: List[Dict[str, Any]] = [
            {
                "type": "input_image",
                "image_url": f"data:{media_type};base64,{screenshot_base64}",
            },
            {
                "type": "input_text",
                "text": user_text,
            },
        ]

        input_items.append({
            "type": "message",
            "role": "user",
            "content": current_content,
        })

        # Build payload
        payload: Dict[str, Any] = {
            "model": self.config.model,
            "input": input_items,
            "temperature": self.config.temperature,
        }
        if self.config.max_tokens:
            payload["max_output_tokens"] = self.config.max_tokens

        # Send request
        data = self._post(payload)

        # Extract text from response
        text = self._extract_text(data)
        usage = data.get("usage", {})

        return OpenAIVLMResponse(
            text=text,
            raw_response=data,
            usage={
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
            },
        )

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
