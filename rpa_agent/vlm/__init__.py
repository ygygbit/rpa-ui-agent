"""Vision-Language Model integration for GUI understanding."""

from .client import (
    VLMClient,
    VLMConfig,
    VLMResponse,
    ANTHROPIC_MODELS,
    CUSTOM_ENDPOINT_MODELS,
    DEFAULT_ANTHROPIC_MODEL,
    DEFAULT_CUSTOM_MODEL,
    get_config_from_env,
)
from .cua_client import CUAClient, CUAConfig
from .openai_vlm_client import OpenAIVLMClient, OpenAIVLMConfig, OpenAIVLMResponse
from .prompts import SystemPrompts

# Model lists by provider
CUA_MODELS = ["gpt-5.4"]

# Backwards compatibility
AVAILABLE_MODELS = ANTHROPIC_MODELS + CUSTOM_ENDPOINT_MODELS + CUA_MODELS
DEFAULT_MODEL = DEFAULT_CUSTOM_MODEL

__all__ = [
    "VLMClient",
    "VLMConfig",
    "VLMResponse",
    "CUAClient",
    "CUAConfig",
    "OpenAIVLMClient",
    "OpenAIVLMConfig",
    "OpenAIVLMResponse",
    "SystemPrompts",
    "AVAILABLE_MODELS",
    "DEFAULT_MODEL",
    "ANTHROPIC_MODELS",
    "CUSTOM_ENDPOINT_MODELS",
    "CUA_MODELS",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_CUSTOM_MODEL",
    "get_config_from_env",
]
