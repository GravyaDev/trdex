"""Redis-backed LLM cost budget tracker.

Tracks daily and monthly spend across all process instances. The LLMCaller
checks this before every LLM call and records spend after each successful call.

Redis keys:
    trdex:llm:spend:daily:{YYYY-MM-DD}   → float (USD)
    trdex:llm:spend:monthly:{YYYY-MM}     → float (USD)

Keys expire automatically (daily: 48h, monthly: 35 days) so no cleanup needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class LLMBudgetTracker:
    """Async Redis-backed budget tracker for LLM spend."""

    def __init__(
        self,
        redis_url: str,
        daily_budget: float = 20.0,
        monthly_budget: float = 500.0,
    ) -> None:
        self._redis_url = redis_url
        self._daily_budget = daily_budget
        self._monthly_budget = monthly_budget
        self._client: aioredis.Redis | None = None

    async def _get_client(self) -> aioredis.Redis:
        if self._client is None:
            self._client = aioredis.from_url(self._redis_url, decode_responses=True)
        return self._client

    def _daily_key(self) -> str:
        day = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        return f"trdex:llm:spend:daily:{day}"

    def _monthly_key(self) -> str:
        month = datetime.now(tz=timezone.utc).strftime("%Y-%m")
        return f"trdex:llm:spend:monthly:{month}"

    async def check_budget(self) -> tuple[bool, str]:
        """Check if daily and monthly budgets allow another LLM call.

        Returns (allowed, reason). If not allowed, reason explains which
        budget was exceeded.
        """
        try:
            client = await self._get_client()
            daily_raw = await client.get(self._daily_key())
            monthly_raw = await client.get(self._monthly_key())

            daily_spend = float(daily_raw) if daily_raw else 0.0
            monthly_spend = float(monthly_raw) if monthly_raw else 0.0

            if daily_spend >= self._daily_budget:
                return False, f"daily_budget_exceeded ({daily_spend:.2f}/{self._daily_budget:.2f})"
            if monthly_spend >= self._monthly_budget:
                return False, f"monthly_budget_exceeded ({monthly_spend:.2f}/{self._monthly_budget:.2f})"
            return True, "ok"
        except Exception:
            # Redis down → fail-open (allow the call, log warning)
            logger.warning("[LLMBudget] Redis unreachable — fail-open, allowing call")
            return True, "redis_unavailable"

    async def record_spend(self, cost_usd: float) -> None:
        """Increment daily and monthly spend counters."""
        if cost_usd <= 0:
            return
        try:
            client = await self._get_client()
            pipe = client.pipeline()
            daily_key = self._daily_key()
            monthly_key = self._monthly_key()
            pipe.incrbyfloat(daily_key, cost_usd)
            pipe.expire(daily_key, 48 * 3600)  # 48h TTL
            pipe.incrbyfloat(monthly_key, cost_usd)
            pipe.expire(monthly_key, 35 * 86400)  # 35 day TTL
            await pipe.execute()
        except Exception:
            logger.warning("[LLMBudget] failed to record spend $%.4f — Redis may be down", cost_usd)

    async def get_spend(self) -> dict[str, float]:
        """Return current daily and monthly spend for dashboard display."""
        try:
            client = await self._get_client()
            daily_raw = await client.get(self._daily_key())
            monthly_raw = await client.get(self._monthly_key())
            return {
                "daily": float(daily_raw) if daily_raw else 0.0,
                "monthly": float(monthly_raw) if monthly_raw else 0.0,
                "daily_budget": self._daily_budget,
                "monthly_budget": self._monthly_budget,
            }
        except Exception:
            return {
                "daily": 0.0,
                "monthly": 0.0,
                "daily_budget": self._daily_budget,
                "monthly_budget": self._monthly_budget,
            }

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
