"""Pydantic schemas for LLM structured output.

These models are used with LangChain's ``with_structured_output()`` (or the
Google GenAI equivalent) to guarantee type-safe, parseable responses from
any provider.

Each schema maps to one agent's LLM output contract.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class AnalystOutput(BaseModel):
    """Structured output from the Analyst LLM call."""

    signal: Literal["BUY", "SELL", "HOLD"]
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = Field(min_length=1, max_length=2000)
    suggested_stop_loss: float = Field(ge=0.005, le=0.20, default=0.03)
    suggested_take_profit: float = Field(ge=0.01, le=0.40, default=0.06)


class ScoutOutput(BaseModel):
    """Structured output from the Scout LLM call."""

    summary: str = Field(min_length=1, max_length=2000)
    sentiment_score: float = Field(ge=-1.0, le=1.0)
    key_events: list[str] = Field(default_factory=list, max_length=10)
    contradictions: list[str] = Field(default_factory=list, max_length=5)
    confidence_in_sentiment: float = Field(ge=0.0, le=1.0, default=0.5)
