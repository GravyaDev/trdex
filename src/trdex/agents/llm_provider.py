"""LLM provider factory and utilities.

Centralises provider-specific logic so agent nodes never deal with
Anthropic vs OpenAI vs Google differences directly.

Key exports:
    get_chat_model — returns a bare ``BaseChatModel`` for a provider/config
    get_structured_chain — returns a chain that produces a Pydantic model
    sanitize_rag_content — strips known injection patterns from RAG text
"""

from __future__ import annotations

import re
import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Patterns stripped from RAG documents before prompt assembly (Rev 1 — C6).
# These cover common prompt-injection vectors that could appear in news text.
_INJECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r'\{\s*"signal"\s*:', re.IGNORECASE),
    re.compile(r'\{\s*"confidence"\s*:', re.IGNORECASE),
    re.compile(r"ignore\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(all\s+)?(previous\s+)?instructions", re.IGNORECASE),
    re.compile(r"system\s*:", re.IGNORECASE),
    re.compile(r"<\|im_start\|>", re.IGNORECASE),
    re.compile(r"<\|im_end\|>", re.IGNORECASE),
    re.compile(r"<\|system\|>", re.IGNORECASE),
    re.compile(r"```\s*json\s*\{", re.IGNORECASE),
]


def sanitize_rag_content(text: str) -> str:
    """Strip known injection patterns from RAG-retrieved text.

    Called before assembling LLM prompts. Replaces matches with
    ``[filtered]`` so downstream context is aware that content
    was removed.
    """
    for pattern in _INJECTION_PATTERNS:
        text = pattern.sub("[filtered]", text)
    return text


def get_chat_model(
    provider: str,
    model_id: str,
    *,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    top_p: float = 1.0,
    api_key: str = "",
) -> BaseChatModel:
    """Return a configured ``BaseChatModel`` for the given provider.

    Raises ``ValueError`` for unknown providers.
    """
    match provider:
        case "anthropic":
            from langchain_anthropic import ChatAnthropic

            kwargs: dict[str, Any] = {
                "model": model_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
            }
            if api_key:
                kwargs["api_key"] = api_key
            return ChatAnthropic(**kwargs)

        case "openai":
            from langchain_openai import ChatOpenAI

            kwargs = {
                "model": model_id,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "top_p": top_p,
            }
            if api_key:
                kwargs["api_key"] = api_key
            return ChatOpenAI(**kwargs)

        case "google":
            from langchain_google_genai import ChatGoogleGenerativeAI

            kwargs = {
                "model": model_id,
                "temperature": temperature,
                "max_output_tokens": max_tokens,
                "top_p": top_p,
            }
            if api_key:
                kwargs["google_api_key"] = api_key
            return ChatGoogleGenerativeAI(**kwargs)

        case _:
            raise ValueError(
                f"Unknown LLM provider {provider!r}. "
                "Supported: 'anthropic', 'openai', 'google'."
            )


def get_structured_chain(
    provider: str,
    model_id: str,
    schema: type[BaseModel],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1024,
    top_p: float = 1.0,
    api_key: str = "",
) -> Runnable:
    """Return a chain that produces structured output (Pydantic model).

    Wraps provider-specific differences:
    - Anthropic/OpenAI: ``llm.with_structured_output(schema)``
    - Google GenAI: ``llm.with_structured_output(schema)`` (langchain-google-genai >=2.0
      supports this natively; falls back to bind + JSON parse if needed)

    Agent nodes should call this, never ``with_structured_output()`` directly.
    """
    llm = get_chat_model(
        provider,
        model_id,
        temperature=temperature,
        max_tokens=max_tokens,
        top_p=top_p,
        api_key=api_key,
    )
    # langchain-google-genai >=2.0 supports with_structured_output natively.
    # If a future version breaks this, add a Google-specific path here.
    return llm.with_structured_output(schema)
