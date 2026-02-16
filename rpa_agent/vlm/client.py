"""
Vision-Language Model client for GUI understanding.

Supports two configuration modes:
1. Custom endpoint (e.g., local server, proxy): Set RPA_VLM_BASE_URL
2. Official Anthropic API: Set ANTHROPIC_API_KEY

Environment Variables:
- RPA_VLM_BASE_URL: Custom API endpoint URL (optional)
- RPA_VLM_API_KEY: API key for custom endpoint (optional)
- RPA_VLM_MODEL: Model name to use (optional)
- ANTHROPIC_API_KEY: Official Anthropic API key (used if no custom endpoint)

Recommended models: claude-opus-4-20250514, claude-sonnet-4-20250514
"""

import base64
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import anthropic
from PIL import Image

from .prompts import SystemPrompts


# Available models for different providers
ANTHROPIC_MODELS = [
    "claude-opus-4-20250514",      # Best for visual tasks (recommended)
    "claude-sonnet-4-20250514",    # Fast and capable
    "claude-3-5-sonnet-20241022",  # Previous generation
]

CUSTOM_ENDPOINT_MODELS = [
    "claude-opus-4.6-fast",  # Fast model for custom endpoints (recommended)
    "claude-opus-4.6",       # Standard model
    "claude-opus-4.6-1m",    # Extended context
]

# Default model based on configuration
DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-20250514"
DEFAULT_CUSTOM_MODEL = "claude-opus-4.6-fast"


def get_config_from_env() -> dict:
    """
    Load VLM configuration from environment variables.

    Priority:
    1. Custom endpoint (RPA_VLM_BASE_URL) if set
    2. Official Anthropic API (ANTHROPIC_API_KEY) if set
    3. Default local endpoint for development
    """
    config = {}

    # Check for custom endpoint first
    custom_url = os.environ.get("RPA_VLM_BASE_URL")
    custom_key = os.environ.get("RPA_VLM_API_KEY")
    custom_model = os.environ.get("RPA_VLM_MODEL")

    # Check for official Anthropic API
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY")

    if custom_url:
        # Custom endpoint mode
        config["base_url"] = custom_url
        config["api_key"] = custom_key or "custom-endpoint"
        config["model"] = custom_model or DEFAULT_CUSTOM_MODEL
        config["use_official_api"] = False
    elif anthropic_key:
        # Official Anthropic API mode
        config["base_url"] = None  # Use default Anthropic URL
        config["api_key"] = anthropic_key
        config["model"] = custom_model or DEFAULT_ANTHROPIC_MODEL
        config["use_official_api"] = True
    else:
        # Default: local development endpoint
        config["base_url"] = "http://localhost:23333/api/anthropic"
        config["api_key"] = "development"
        config["model"] = custom_model or DEFAULT_CUSTOM_MODEL
        config["use_official_api"] = False

    return config


@dataclass
class VLMConfig:
    """
    Configuration for VLM client.

    Can be initialized directly or loaded from environment variables.

    Examples:
        # Use environment variables
        config = VLMConfig.from_env()

        # Custom endpoint
        config = VLMConfig(
            base_url="http://my-server:8080/api",
            api_key="my-key",
            model="claude-opus-4.6-fast"
        )

        # Official Anthropic API
        config = VLMConfig(
            api_key="sk-ant-...",
            model="claude-opus-4-20250514",
            use_official_api=True
        )
    """
    base_url: Optional[str] = None
    api_key: str = ""
    model: str = DEFAULT_CUSTOM_MODEL
    max_tokens: int = 4096
    temperature: float = 0.1
    use_official_api: bool = False

    @classmethod
    def from_env(cls) -> "VLMConfig":
        """Create config from environment variables."""
        env_config = get_config_from_env()
        return cls(
            base_url=env_config.get("base_url"),
            api_key=env_config.get("api_key", ""),
            model=env_config.get("model", DEFAULT_CUSTOM_MODEL),
            use_official_api=env_config.get("use_official_api", False),
        )

    @classmethod
    def for_anthropic(cls, api_key: str, model: Optional[str] = None) -> "VLMConfig":
        """Create config for official Anthropic API."""
        return cls(
            api_key=api_key,
            model=model or DEFAULT_ANTHROPIC_MODEL,
            use_official_api=True,
        )

    @classmethod
    def for_custom_endpoint(
        cls,
        base_url: str,
        api_key: str = "custom",
        model: Optional[str] = None
    ) -> "VLMConfig":
        """Create config for custom endpoint."""
        return cls(
            base_url=base_url,
            api_key=api_key,
            model=model or DEFAULT_CUSTOM_MODEL,
            use_official_api=False,
        )


@dataclass
class VLMResponse:
    """Response from VLM."""
    text: str
    raw_response: Any
    usage: Dict[str, int]


class VLMClient:
    """
    Vision-Language Model client for GUI analysis.

    Supports both custom endpoints and official Anthropic API.
    Configuration is loaded from environment variables by default.

    Usage:
        # Auto-configure from environment
        client = VLMClient()

        # Custom endpoint
        client = VLMClient(VLMConfig.for_custom_endpoint("http://localhost:8080/api"))

        # Official Anthropic API
        client = VLMClient(VLMConfig.for_anthropic("sk-ant-..."))
    """

    def __init__(self, config: Optional[VLMConfig] = None):
        """
        Initialize VLM client.

        Args:
            config: VLM configuration. If None, loads from environment variables.
        """
        self.config = config or VLMConfig.from_env()

        # Initialize Anthropic client
        if self.config.use_official_api or self.config.base_url is None:
            # Official Anthropic API
            self.client = anthropic.Anthropic(api_key=self.config.api_key)
        else:
            # Custom endpoint
            self.client = anthropic.Anthropic(
                api_key=self.config.api_key,
                base_url=self.config.base_url
            )

    def _encode_image(self, image: Union[str, Path, Image.Image, bytes, Tuple[str, str]]) -> Tuple[str, str]:
        """
        Encode image to base64.

        Args:
            image: Image as path, PIL Image, bytes, or tuple of (base64_data, media_type)

        Returns:
            Tuple of (base64 string, media type)
        """
        # Handle tuple of (base64_data, media_type) - already encoded
        if isinstance(image, tuple) and len(image) == 2:
            return image[0], image[1]

        if isinstance(image, (str, Path)):
            path = Path(image)
            # Check if it looks like a base64 string (no path separators, very long)
            if isinstance(image, str) and '/' not in image and '\\' not in image and len(image) > 500:
                # Assume it's raw base64 PNG data
                return image, "image/png"
            with open(path, "rb") as f:
                image_bytes = f.read()
            media_type = self._get_media_type(path.suffix)
        elif isinstance(image, Image.Image):
            import io
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            image_bytes = buffer.getvalue()
            media_type = "image/png"
        elif isinstance(image, bytes):
            image_bytes = image
            media_type = "image/png"  # Assume PNG for raw bytes
        else:
            raise ValueError(f"Unsupported image type: {type(image)}")

        return base64.standard_b64encode(image_bytes).decode("utf-8"), media_type

    def _get_media_type(self, suffix: str) -> str:
        """Get media type from file extension."""
        types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
        }
        return types.get(suffix.lower(), "image/png")

    def _build_message_content(
        self,
        text: str,
        images: Optional[List[Union[str, Path, Image.Image, bytes]]] = None
    ) -> List[Dict[str, Any]]:
        """Build message content with text and images."""
        content = []

        # Add images first
        if images:
            for img in images:
                img_data, media_type = self._encode_image(img)
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": img_data
                    }
                })

        # Add text
        content.append({
            "type": "text",
            "text": text
        })

        return content

    def analyze_screenshot(
        self,
        screenshot: Union[str, Path, Image.Image, bytes],
        task: str,
        screen_info: Optional[Dict[str, int]] = None,
        history: Optional[List[Dict[str, str]]] = None,
        system_prompt: Optional[str] = None
    ) -> VLMResponse:
        """
        Analyze a screenshot and determine next action.

        Args:
            screenshot: Screenshot image
            task: Task description or instruction
            screen_info: Screen dimensions {"width": w, "height": h}
            history: Previous conversation history
            system_prompt: Custom system prompt (uses default if None)

        Returns:
            VLMResponse with action recommendation
        """
        # Build user message
        user_text = f"Task: {task}\n"
        if screen_info:
            user_text += f"\nScreen dimensions: {screen_info['width']}x{screen_info['height']}\n"
        user_text += "\nAnalyze this screenshot and determine the next action to accomplish the task."

        content = self._build_message_content(user_text, [screenshot])

        # Build messages
        messages = []
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": content})

        # Make API call
        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system_prompt or SystemPrompts.GUI_AGENT,
            messages=messages,
            temperature=self.config.temperature
        )

        return VLMResponse(
            text=response.content[0].text,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )

    def ground_element(
        self,
        screenshot: Union[str, Path, Image.Image, bytes],
        element_description: str,
        screen_info: Optional[Dict[str, int]] = None
    ) -> VLMResponse:
        """
        Find coordinates of a specific element.

        Args:
            screenshot: Screenshot image
            element_description: Description of element to find
            screen_info: Screen dimensions

        Returns:
            VLMResponse with element coordinates
        """
        user_text = f"Find this element: {element_description}\n"
        if screen_info:
            user_text += f"\nScreen dimensions: {screen_info['width']}x{screen_info['height']}\n"

        content = self._build_message_content(user_text, [screenshot])

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=SystemPrompts.GROUNDING,
            messages=[{"role": "user", "content": content}],
            temperature=0.0  # More deterministic for grounding
        )

        return VLMResponse(
            text=response.content[0].text,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )

    def plan_task(
        self,
        screenshot: Union[str, Path, Image.Image, bytes],
        task: str,
        screen_info: Optional[Dict[str, int]] = None
    ) -> VLMResponse:
        """
        Create a plan for accomplishing a task.

        Args:
            screenshot: Current screenshot
            task: Task to accomplish
            screen_info: Screen dimensions

        Returns:
            VLMResponse with task plan
        """
        user_text = f"Create a plan to accomplish this task: {task}\n"
        if screen_info:
            user_text += f"\nScreen dimensions: {screen_info['width']}x{screen_info['height']}\n"

        content = self._build_message_content(user_text, [screenshot])

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=SystemPrompts.PLANNING,
            messages=[{"role": "user", "content": content}],
            temperature=0.2
        )

        return VLMResponse(
            text=response.content[0].text,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )

    def verify_action(
        self,
        before_screenshot: Union[str, Path, Image.Image, bytes],
        after_screenshot: Union[str, Path, Image.Image, bytes],
        action_description: str,
        expected_result: str
    ) -> VLMResponse:
        """
        Verify that an action had the expected effect.

        Args:
            before_screenshot: Screenshot before action
            after_screenshot: Screenshot after action
            action_description: What action was performed
            expected_result: What should have happened

        Returns:
            VLMResponse with verification result
        """
        user_text = f"""Action performed: {action_description}
Expected result: {expected_result}

Compare the before and after screenshots to verify if the action succeeded."""

        content = self._build_message_content(
            user_text,
            [before_screenshot, after_screenshot]
        )

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=SystemPrompts.VERIFICATION,
            messages=[{"role": "user", "content": content}],
            temperature=0.1
        )

        return VLMResponse(
            text=response.content[0].text,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )

    def extract_text(
        self,
        screenshot: Union[str, Path, Image.Image, bytes]
    ) -> VLMResponse:
        """
        Extract all visible text from screenshot.

        Args:
            screenshot: Screenshot image

        Returns:
            VLMResponse with extracted text
        """
        content = self._build_message_content(
            "Extract all visible text from this screenshot.",
            [screenshot]
        )

        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=SystemPrompts.OCR,
            messages=[{"role": "user", "content": content}],
            temperature=0.0
        )

        return VLMResponse(
            text=response.content[0].text,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )

    def chat(
        self,
        messages: List[Dict[str, Any]],
        system: Optional[str] = None
    ) -> VLMResponse:
        """
        Send a raw chat completion request.

        Args:
            messages: List of message dicts
            system: System prompt

        Returns:
            VLMResponse
        """
        response = self.client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system or "",
            messages=messages,
            temperature=self.config.temperature
        )

        return VLMResponse(
            text=response.content[0].text,
            raw_response=response,
            usage={
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens
            }
        )
