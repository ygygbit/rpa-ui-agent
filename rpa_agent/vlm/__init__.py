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
from .prompts import SystemPrompts

# Backwards compatibility
AVAILABLE_MODELS = ANTHROPIC_MODELS + CUSTOM_ENDPOINT_MODELS
DEFAULT_MODEL = DEFAULT_CUSTOM_MODEL

__all__ = [
    "VLMClient",
    "VLMConfig",
    "VLMResponse",
    "SystemPrompts",
    "AVAILABLE_MODELS",
    "DEFAULT_MODEL",
    "ANTHROPIC_MODELS",
    "CUSTOM_ENDPOINT_MODELS",
    "DEFAULT_ANTHROPIC_MODEL",
    "DEFAULT_CUSTOM_MODEL",
    "get_config_from_env",
]
