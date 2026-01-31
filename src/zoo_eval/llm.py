"""LLM provider utilities with auto-detection.

Auto-detects provider based on model name:
- Models starting with "anthropic/" → Anthropic API direct
- Models with "/" (e.g., "google/gemini-2.5-flash") → OpenRouter
- Models without "/" (e.g., "gpt-5.1") → OpenAI direct

Aliases are supported for convenience:
- "flash" → "google/gemini-2.5-flash"
- "sonnet" → "anthropic/claude-sonnet-4"
- "opus" → "anthropic/claude-opus-4"
- "haiku" → "anthropic/claude-haiku"
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openai import OpenAI

# Model aliases for convenience
MODEL_ALIASES = {
    "flash": "google/gemini-2.5-flash",
    "sonnet": "anthropic/claude-sonnet-4",
    "opus": "anthropic/claude-opus-4",
    "haiku": "anthropic/claude-haiku",
}


def resolve_model(model: str) -> str:
    """Resolve model aliases to full model names."""
    return MODEL_ALIASES.get(model, model)


def detect_provider(model: str) -> str:
    """Auto-detect provider from model name.

    Returns:
        "anthropic" if model starts with "anthropic/"
        "openrouter" if model contains "/"
        "openai" otherwise
    """
    if model.startswith("anthropic/"):
        return "anthropic"
    return "openrouter" if "/" in model else "openai"


def get_api_key(provider: str) -> str | None:
    """Get API key for provider from environment."""
    env_vars = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openrouter": "OPENROUTER_API_KEY",
        "openai": "OPENAI_API_KEY",
    }
    return os.environ.get(env_vars.get(provider, ""))


def _strip_provider_prefix(model: str) -> str:
    """Strip provider prefix from model name (e.g., 'anthropic/claude-sonnet-4' -> 'claude-sonnet-4')."""
    return model.split("/", 1)[1] if "/" in model else model


def create_chat_model(model: str):
    """Create a chat model instance for browser_use agents.

    Args:
        model: Model name (with optional alias resolution)

    Returns:
        Chat model instance configured for the detected provider
    """
    model = resolve_model(model)
    provider = detect_provider(model)

    if provider == "anthropic":
        from browser_use import ChatAnthropic

        return ChatAnthropic(
            model=_strip_provider_prefix(model),
            api_key=get_api_key("anthropic"),
        )
    elif provider == "openrouter":
        from browser_use import ChatOpenAI

        return ChatOpenAI(
            model=model,
            base_url="https://openrouter.ai/api/v1",
            api_key=get_api_key("openrouter"),
        )
    else:
        from browser_use import ChatOpenAI

        return ChatOpenAI(model=model)


# Backwards compatibility alias
create_chat_openai = create_chat_model


def create_openai_client(model: str) -> tuple["OpenAI", str]:
    """Create an OpenAI-compatible client for direct API calls (e.g., judge).

    Note: Anthropic models are routed through OpenRouter for judge compatibility.

    Args:
        model: Model name (with optional alias resolution)

    Returns:
        Tuple of (client, resolved model name)
    """
    from openai import OpenAI

    model = resolve_model(model)
    provider = detect_provider(model)

    # For judge, route Anthropic through OpenRouter (Anthropic doesn't have OpenAI-compatible API)
    if provider in ("anthropic", "openrouter"):
        client = OpenAI(
            base_url="https://openrouter.ai/api/v1",
            api_key=get_api_key("openrouter"),
        )
        return client, model
    else:
        client = OpenAI(api_key=get_api_key("openai"))
        return client, model
