"""AgentRunRepository — Tier 6 (session log) reader/helper.

Reads from the existing `agent_runs` table (writes still happen inline in
`agents/runner.py`). Adds a `narrative_context()` helper that turns the last
N runs into a compact, LLM-friendly recap so future agent cycles can see what
happened on the same symbol recently.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trdex.storage.agent_run_models import AgentRunRecord

logger = logging.getLogger(__name__)


@dataclass
class RunNarrative:
    """Compact recap of recent agent runs for one symbol."""

    symbol: str
    count: int
    text: str  # multiline narrative ready for an LLM prompt
    last_ran_at: datetime | None
    signals: dict[str, int]  # {"BUY": 3, "SELL": 1, "HOLD": 6}
    approval_rate: float  # ratio of risk_approved over count
    fill_rate: float  # ratio of order_status=='filled' over count


class AgentRunRepository:
    """Read helper around the agent_runs table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def recent_for_symbol(
        self,
        symbol: str,
        *,
        limit: int = 10,
    ) -> list[AgentRunRecord]:
        """Return the most recent runs for a symbol, newest first."""
        result = await self._session.execute(
            select(AgentRunRecord)
            .where(AgentRunRecord.symbol == symbol)
            .order_by(AgentRunRecord.ran_at.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def narrative_context(
        self,
        symbol: str,
        *,
        limit: int = 10,
    ) -> RunNarrative:
        """Build a compact narrative recap of the last N runs for a symbol.

        The text output is intended to be injected into an agent prompt as
        "recent history". It's deterministic and stays under ~600 chars for
        limit=10.
        """
        runs = await self.recent_for_symbol(symbol, limit=limit)
        count = len(runs)

        if count == 0:
            return RunNarrative(
                symbol=symbol,
                count=0,
                text=f"No prior runs recorded for {symbol}.",
                last_ran_at=None,
                signals={},
                approval_rate=0.0,
                fill_rate=0.0,
            )

        signals: dict[str, int] = {}
        approved = 0
        filled = 0
        lines: list[str] = []

        for r in runs:
            # D11/D24: the DB column is still called `signal` but stores
            # Intent string values since 2026-04-08 (``open_long``,
            # ``close_long``, ``hold``, …). No normalisation: the strings
            # are already canonical.
            sig = r.signal or "hold"
            signals[sig] = signals.get(sig, 0) + 1
            if r.risk_approved:
                approved += 1
            if (r.order_status or "") == "filled":
                filled += 1

            ts = r.ran_at.strftime("%Y-%m-%d %H:%M") if r.ran_at else "?"
            conf = float(r.confidence or 0)
            status = r.order_status or "skipped"
            lines.append(
                f"- {ts} | {sig} conf={conf:.2f} | "
                f"risk={'OK' if r.risk_approved else 'BLOCK'} | order={status}"
            )

        approval_rate = approved / count
        fill_rate = filled / count
        sig_summary = ", ".join(f"{k}:{v}" for k, v in sorted(signals.items()))
        header = (
            f"Recent {count} runs for {symbol} — "
            f"signals: {sig_summary} | approval={approval_rate:.0%} | fill={fill_rate:.0%}"
        )
        text = header + "\n" + "\n".join(lines)

        return RunNarrative(
            symbol=symbol,
            count=count,
            text=text,
            last_ran_at=runs[0].ran_at,
            signals=signals,
            approval_rate=approval_rate,
            fill_rate=fill_rate,
        )
