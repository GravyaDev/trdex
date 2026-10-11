"""Funding on perpetual positions, booked to the ledger in simulation.

Binance charges funding every 8h (00, 08, 16 UTC) on the position's
notional: longs pay shorts when the rate is positive. In simulation the
StopLossMonitor books it at ``funding_rate_8h`` (``trdex.risk.leverage``)
as ``funding`` ledger rows, one per position per tick that crossed a
funding time, and remembers the last time booked on the position
(``funding_paid_until``) so restarts never charge twice. Live funding is
charged by the exchange and not reconciled here yet.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from trdex.risk.leverage import funding_cash, funding_times

logger = logging.getLogger(__name__)


def _aware(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


async def accrue_funding(
    session_factory: Any,
    positions: list[Any],
    prices: dict[str, float],
    rate: float,
    now: datetime,
) -> float:
    """Book funding due on ``positions`` up to ``now``; returns the total cash change.

    Each position is booked in its own transaction (ledger row + its
    ``funding_paid_until``), so one failure never double-charges another.
    Positions without a price this tick wait for the next one.
    """
    from sqlalchemy import select

    from trdex.storage.balance_models import BalanceRecord
    from trdex.storage.balance_repo import BalanceRepository
    from trdex.storage.portfolio_models import PositionRecord

    total = 0.0
    if rate == 0:
        return total
    for pos in positions:
        price = prices.get(pos.symbol)
        if price is None:
            continue
        start = getattr(pos, "funding_paid_until", None) or getattr(pos, "opened_at", None)
        if start is None:
            continue
        times = funding_times(_aware(start), now)
        if not times:
            continue
        cash = funding_cash(str(pos.side), float(pos.amount), price, rate) * len(times)
        try:
            async with session_factory() as session:
                live = (
                    await session.execute(select(PositionRecord).where(PositionRecord.id == pos.id))
                ).scalar_one_or_none()
                if live is None or live.status != "open":
                    continue
                balance = await BalanceRepository(session).current_balance()
                amount = Decimal(str(round(cash, 8)))
                session.add(
                    BalanceRecord(
                        event_type="funding",
                        amount=amount,
                        balance_after=balance + amount,
                        note=(
                            f"funding {live.side} {live.symbol} position {live.id}: "
                            f"{len(times)} x {rate:.4%} on {float(live.amount)} @ {price}"
                        ),
                        recorded_at=now.astimezone(UTC).replace(tzinfo=None),
                    )
                )
                live.funding_paid_until = times[-1].replace(tzinfo=None)
                await session.commit()
            pos.funding_paid_until = times[-1].replace(tzinfo=None)
            total += cash
        except Exception:
            logger.exception("[funding] could not book funding for position %s", pos.id)
    return total
