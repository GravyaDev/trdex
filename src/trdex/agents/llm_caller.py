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
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone, UTC
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
    # Anthropic
    "claude-haiku-4-5-20251001": (0.80, 4.00),
    "claude-sonnet-4-6-20250514": (3.00, 15.00),
    "claude-opus-4-6-20250514": (15.00, 75.00),
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    # Google
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.0-pro": (1.25, 10.00),
    # Groq (hosted Llama/Mixtral — pricing as of 2025-05)
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "mixtral-8x7b-32768": (0.24, 0.24),
    # Together
    "meta-llama/Llama-3.3-70B-Instruct-Turbo": (0.88, 0.88),
    # DeepSeek
    "deepseek-chat": (0.14, 0.28),
    "deepseek-reasoner": (0.55, 2.19),
    # xAI
    "grok-3-mini": (0.30, 0.50),
    # Mistral
    "mistral-small-latest": (0.10, 0.30),
    "mistral-large-latest": (2.00, 6.00),
    # Ollama (local — zero cost)
    "llama3.2": (0.0, 0.0),
    "qwen2.5": (0.0, 0.0),
    "mistral": (0.0, 0.0),
}

_DEFAULT_COST = (1.00, 5.00)  # fallback for unknown models


def _utc_day() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


@dataclass
class _DailySpend:
    """In-process daily spend, shared by every per-run copy of an LLMCaller.

    Resets when the UTC day changes, so the "daily" budget does not turn
    into a lifetime budget for a long-running process.
    """

    day: str = ""
    amount: float = 0.0

    def current(self) -> float:
        today = _utc_day()
        if self.day != today:
            self.day, self.amount = today, 0.0
        return self.amount

    def add(self, cost: float) -> None:
        self.current()
        self.amount += cost


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
    """Stateful LLM call helper.

    One instance is built at startup; ``run_agent_cycle`` derives a per-run
    copy with ``for_run(run_id)`` so usage records belong to one cycle,
    while the daily spend counter stays shared across cycles.
    Injected into ``AgentState.llm_caller`` (non-serialized).
    """

    configs: dict[str, AgentConfigRecord]
    run_id: str
    api_keys: dict[str, str] = field(default_factory=dict)
    # api_keys: {"anthropic": "sk-ant-...", "openai": "sk-...", "google": "AIza..."}

    daily_budget: float = 20.0
    # In-process daily accumulator (used when no Redis budget_tracker is set).
    _spend: _DailySpend = field(default_factory=_DailySpend, repr=False)

    timeout_seconds: float = 10.0

    # Redis-backed budget tracker (optional — set by runner if Redis available)
    budget_tracker: Any = field(default=None, repr=False)  # LLMBudgetTracker | None

    # Usage records collected during this cycle, persisted by runner at the end.
    usage_records: list[LLMUsageRecord] = field(default_factory=list)

    @property
    def daily_spend(self) -> float:
        return self._spend.current()

    def for_run(self, run_id: str) -> LLMCaller:
        """Copy for one agent cycle: own run_id and usage records, shared spend."""
        return replace(self, run_id=run_id, usage_records=[])

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

        # Budget check — Redis-backed if available, in-process fallback
        if self.budget_tracker is not None:
            allowed, reason = await self.budget_tracker.check_budget()
            if not allowed:
                logger.warning("[LLMCaller] budget blocked: %s — skipping LLM for %s", reason, agent_name)
                self._record_usage(agent_name, config, fallback_used=True, error=reason)
                return None
        elif self.daily_spend >= self.daily_budget:
            logger.warning(
                "[LLMCaller] daily budget exhausted (%.2f/%.2f) — skipping LLM for %s",
                self.daily_spend, self.daily_budget, agent_name,
            )
            self._record_usage(agent_name, config, fallback_used=True, error="budget_exhausted")
            return None

        api_key = self.api_keys.get(config.provider, "")
        base_url = getattr(config, "base_url", "") or ""
        try:
            chain = get_structured_chain(
                provider=config.provider,
                model_id=config.model_id,
                schema=schema,
                temperature=config.temperature,
                max_tokens=config.max_tokens,
                top_p=config.top_p,
                api_key=api_key,
                base_url=base_url,
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
            # The provider may have processed (and billed) the request.
            input_tokens, output_tokens = self._estimate_tokens(messages, config)
            cost = self._estimate_cost(config.model_id, input_tokens, output_tokens)
            await self._charge(cost)
            self._record_usage(
                agent_name, config,
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
                latency_ms=latency_ms, fallback_used=True, error="timeout",
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

        # The chain is built with include_raw=True: {"raw", "parsed", "parsing_error"}.
        parsed, raw, parsing_error = self._unpack(result)
        usage = self._extract_tokens(raw)
        if usage is None:
            # No usage reported: charge a conservative estimate, never zero,
            # otherwise the budget can never be reached.
            usage = self._estimate_tokens(messages, config)
            logger.warning(
                "[LLMCaller] no token usage from %s/%s — charging estimate %d in / %d out",
                config.provider, config.model_id, *usage,
            )
        input_tokens, output_tokens = usage
        cost = self._estimate_cost(config.model_id, input_tokens, output_tokens)
        await self._charge(cost)

        if parsed is None:
            logger.warning("[LLMCaller] structured output parse failed for %s: %s",
                           agent_name, parsing_error)
            self._record_usage(
                agent_name, config,
                input_tokens=input_tokens, output_tokens=output_tokens, cost_usd=cost,
                latency_ms=latency_ms, fallback_used=True,
                error=f"parse error: {parsing_error}"[:500],
            )
            return None

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
        return parsed

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

    async def _charge(self, cost: float) -> None:
        self._spend.add(cost)
        if self.budget_tracker is not None:
            await self.budget_tracker.record_spend(cost)

    @staticmethod
    def _unpack(result: Any) -> tuple[Any, Any, Any]:
        """Return (parsed, raw, parsing_error) from an include_raw=True result.

        A bare Pydantic model (chains built without include_raw) is accepted
        as (model, None, None).
        """
        if isinstance(result, dict) and "parsed" in result:
            return result.get("parsed"), result.get("raw"), result.get("parsing_error")
        return result, None, None

    @staticmethod
    def _extract_tokens(raw: Any) -> tuple[int, int] | None:
        """Token usage from the raw AIMessage, or None if not reported."""
        if raw is None:
            return None
        usage = getattr(raw, "usage_metadata", None)
        if usage:
            i, o = usage.get("input_tokens", 0) or 0, usage.get("output_tokens", 0) or 0
            if i or o:
                return int(i), int(o)
        meta = getattr(raw, "response_metadata", None) or {}
        usage = meta.get("usage") or meta.get("token_usage") or {}
        i = usage.get("input_tokens") or usage.get("prompt_tokens") or 0
        o = usage.get("output_tokens") or usage.get("completion_tokens") or 0
        if i or o:
            return int(i), int(o)
        return None

    @staticmethod
    def _estimate_tokens(messages: list[BaseMessage], config: Any) -> tuple[int, int]:
        """Conservative estimate: ~4 chars per input token, output at max_tokens."""
        chars = sum(len(m.content) if isinstance(m.content, str) else len(str(m.content))
                    for m in messages)
        return chars // 4, int(getattr(config, "max_tokens", 1024) or 1024)

    @staticmethod
    def _estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
        """Estimate USD cost from token counts and model pricing."""
        input_rate, output_rate = _PRICING.get(model_id, _DEFAULT_COST)
        return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
