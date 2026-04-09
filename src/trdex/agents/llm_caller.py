"""LLMCaller — injected into AgentState, handles invoke/fallback/budget.

Created once per ``AgentRunner.run()`` call. Holds the loaded
``agent_config`` rows and tracks budget via a simple in-process counter
(Redis budget tracking is added in Task 6).

Agent nodes call:
    result = await state.llm_caller.invoke("analyst", messages, AnalystOutput)

If the agent's ``llm_enabled`` is False, or the budget is exhausted, or the
LLM call fails, ``invoke()`` returns ``None`` and the caller falls back to
its deterministic path.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import BaseMessage
from pydantic import BaseModel

from trdex.agents.llm_provider import get_structured_chain
from trdex.storage.agent_config_models import AgentConfigRecord

logger = logging.getLogger(__name__)

# Pricing table — input/output cost per 1M tokens.
# Updated manually; the LLMCaller uses this for cost estimation.
_PRICING: dict[str, tuple[float, float]] = {
    # (input $/1M, output $/1M)
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6-20250514": (3.00, 15.00),
    "claude-opus-4-6-20250514": (15.00, 75.00),
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-pro": (1.25, 10.00),
}

_DEFAULT_COST = (1.00, 5.00)  # fallback for unknown models


@dataclass
class LLMUsageRecord:
    """In-memory record of a single LLM call. Persisted by the runner."""

    run_id: str
    agent_name: str
    provider: str
    model_id: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    fallback_used: bool = False
    error: str | None = None


@dataclass
class LLMCaller:
    """Stateful LLM call helper, one instance per agent cycle.

    Injected into ``AgentState.llm_caller`` (non-serialized).
    """

    configs: dict[str, AgentConfigRecord]
    run_id: str
    api_keys: dict[str, str] = field(default_factory=dict)
    # api_keys: {"anthropic": "sk-ant-...", "openai": "sk-...", "google": "AIza..."}

    daily_budget: float = 20.0
    daily_spend: float = 0.0  # accumulated during this process lifetime

    timeout_seconds: float = 10.0

    # Usage records collected during this cycle, persisted by runner at the end.
    usage_records: list[LLMUsageRecord] = field(default_factory=list)

    async def invoke(
        self,
        agent_name: str,
        messages: list[BaseMessage],
        schema: type[BaseModel],
    ) -> BaseModel | None:
        """Call the LLM for ``agent_name`` with structured output.

        Returns the parsed Pydantic model, or ``None`` if:
        - LLM is disabled for this agent
        - Budget is exhausted
        - The call fails (timeout, API error, parse error)

        The caller is responsible for falling back to its deterministic path
        when ``None`` is returned.
        """
        config = self.configs.get(agent_name)
        if config is None or not config.llm_enabled:
            return None

        # Budget check (simple in-process; Redis version in Task 6)
        if self.daily_spend >= self.daily_budget:
            logger.warning(
                "[LLMCaller] daily budget exhausted (%.2f/%.2f) — skipping LLM for %s",
                self.daily_spend, self.daily_budget, agent_name,
            )
            self._record_usage(agent_name, config, fallback_used=True, error="budget_exhausted")
            return None

        api_key = self.api_keys.get(config.provider, "")
        try:
            chain = get_structured_chain(
                provider=config.provider,
                model_id=config.model_id,
                schema=schema,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                api_key=api_key,
            )
        except Exception as exc:
            logger.exception("[LLMCaller] failed to build chain for %s: %s", agent_name, exc)
            self._record_usage(agent_name, config, fallback_used=True, error=str(exc))
            return None

        t0 = time.monotonic()
        try:
            result = await asyncio.wait_for(
                chain.ainvoke(messages),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.warning("[LLMCaller] timeout (%ds) for %s", self.timeout_seconds, agent_name)
            self._record_usage(
                agent_name, config, latency_ms=latency_ms,
                fallback_used=True, error="timeout",
            )
            return None
        except Exception as exc:
            latency_ms = int((time.monotonic() - t0) * 1000)
            logger.exception("[LLMCaller] LLM call failed for %s: %s", agent_name, exc)
            self._record_usage(
                agent_name, config, latency_ms=latency_ms,
                fallback_used=True, error=str(exc)[:500],
            )
            return None

        latency_ms = int((time.monotonic() - t0) * 1000)

        # Extract token usage from the result metadata if available
        input_tokens, output_tokens = self._extract_tokens(result)
        cost = self._estimate_cost(config.model_id, input_tokens, output_tokens)
        self.daily_spend += cost

        self._record_usage(
            agent_name, config,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            latency_ms=latency_ms,
        )

        logger.info(
            "[LLMCaller] %s → %s | %d in / %d out | $%.4f | %dms",
            agent_name, config.model_id,
            input_tokens, output_tokens, cost, latency_ms,
        )
        return result

    def _record_usage(
        self,
        agent_name: str,
        config: AgentConfigRecord,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cost_usd: float = 0.0,
        latency_ms: int = 0,
        fallback_used: bool = False,
        error: str | None = None,
    ) -> None:
        self.usage_records.append(LLMUsageRecord(
            run_id=self.run_id,
            agent_name=agent_name,
            provider=config.provider,
            model_id=config.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost_usd,
            latency_ms=latency_ms,
            fallback_used=fallback_used,
            error=error,
        ))

    @staticmethod
    def _extract_tokens(result: Any) -> tuple[int, int]:
        """Best-effort extraction of token counts from LangChain result.

        LangChain structured output returns a Pydantic model, not an
        AIMessage, so usage metadata may not be available. Return (0, 0)
        if we can't extract.
        """
        # If the result has response_metadata (AIMessage-like)
        meta = getattr(result, "response_metadata", None)
        if meta and isinstance(meta, dict):
            usage = meta.get("usage", {})
            return (
                usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0),
                usage.get("output_tokens", 0) or usage.get("completion_tokens", 0),
            )
        return (0, 0)

    @staticmethod
    def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost from token counts and model pricing."""
        input_rate, output_rate = _PRICING.get(model_id, _DEFAULT_COST)
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
