"""LLM provider utilities with auto-detection.

Auto-detects provider based on model name:
- Models with "/" (e.g., "google/gemini-2.5-flash") → OpenRouter
- Models without "/" (e.g., "gpt-4o") → OpenAI direct

Aliases are supported for convenience:
- "flash" → "google/gemini-2.5-flash"
- "flash-lite" → "google/gemini-2.5-flash-lite"
- "sonnet" → "anthropic/claude-sonnet-4.5"
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

# Model aliases for convenience
MODEL_ALIASES = {
    "flash": "google/gemini-2.5-flash",
    "flash-lite": "google/gemini-2.5-flash-lite",
    "sonnet": "anthropic/claude-sonnet-4.5",
}


def resolve_model(model: str) -> str:
    """Resolve model aliases to full model names."""
    return MODEL_ALIASES.get(model, model)


def detect_provider(model: str) -> str:
    """Auto-detect provider from model name.

    Returns:
        "openrouter" if model contains "/", else "openai"
    """
    return "openrouter" if "/" in model else "openai"


def get_api_key(provider: str) -> str | None:
    """Get API key for provider from environment."""
    env_vars = {
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    return os.environ.get(env_vars.get(provider, ""))


def create_chat_openai(model: str):
    """Create a ChatOpenAI instance for browser_use agents.

    Args:
        model: Model name (with optional alias resolution)

    Returns:
        ChatOpenAI instance configured for the detected provider
    """
    from browser_use import ChatOpenAI

    model = resolve_model(model)
    provider = detect_provider(model)

    if provider == "openrouter":
        return ChatOpenAI(
            model=model,
            base_url="https://openrouter.ai/api/v1",
            api_key=get_api_key("openrouter"),
        )
    else:
        return ChatOpenAI(model=model)


def create_openai_client(model: str) -> tuple["OpenAI", str]:
    """Create an OpenAI client for direct API calls (e.g., judge).

    Args:
        model: Model name (with optional alias resolution)

    Returns:
        Tuple of (OpenAI client, resolved model name)
    """
    from openai import OpenAI

    model = resolve_model(model)
    provider = detect_provider(model)

    if provider == "openrouter":
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=get_api_key("openrouter"),
        )
    else:
        client = OpenAI(api_key=get_api_key("openai"))

    return client, model
