"""PortfolioService: mark-to-market and portfolio snapshot."""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from trdex.market.manager import FeedError, PriceFeedManager
from trdex.portfolio.models import Portfolio, Position
from trdex.storage.portfolio_models import PositionRecord
from trdex.storage.portfolio_repo import PortfolioRepository

logger = logging.getLogger(__name__)


class PortfolioService:
    def __init__(self, repo: PortfolioRepository, feed_manager: PriceFeedManager) -> None:
        self._repo = repo
        self._feeds = feed_manager

    async def mark_to_market(self) -> list[Position]:
        """Return open positions with current_price filled in via live feed."""
        records = await self._repo.get_open_positions()
        if not records:
            return []

        # Fan out ticker fetches in parallel — one per unique symbol
        symbols = list({r.symbol for r in records})
        tickers = await asyncio.gather(
            *[self._fetch_price(sym) for sym in symbols],
            return_exceptions=True,
        )
        price_map: dict[str, Decimal] = {}
        for sym, result in zip(symbols, tickers):
            if isinstance(result, Exception):
                logger.warning("[portfolio] price fetch failed for %s: %s", sym, result)
            else:
                price_map[sym] = Decimal(str(result.price))

        return [_record_to_position(r, price_map.get(r.symbol, Decimal("0"))) for r in records]

    async def snapshot(self) -> Portfolio:
        """Full portfolio snapshot: open positions + realized P&L stats."""
        positions = await self.mark_to_market()
        closed = await self._repo.get_closed_positions(limit=10_000)

        total_trades = len(closed)
        winning_trades = sum(1 for r in closed if _is_win(r))
        realized_pnl = sum(_realized_pnl(r) for r in closed)

        return Portfolio(
            positions=positions,
            total_trades=total_trades,
            winning_trades=winning_trades,
            total_pnl=Decimal(str(realized_pnl)),
        )

    async def _fetch_price(self, symbol: str):  # type: ignore[return]
        return await self._feeds.get_ticker(symbol)


# ── helpers ────────────────────────────────────────────────────────────────

def _record_to_position(r: PositionRecord, current_price: Decimal) -> Position:
    side = "long" if r.side == "BUY" else "short"
    return Position(
        symbol=r.symbol,
        side=side,
        entry_price=Decimal(str(r.entry_price)),
        amount=Decimal(str(r.amount)),
        current_price=current_price,
        opened_at=r.opened_at,
    )


def _is_win(r: PositionRecord) -> bool:
    if r.exit_price is None:
        return False
    if r.side == "BUY":
        return r.exit_price > r.entry_price
    return r.exit_price < r.entry_price


def _realized_pnl(r: PositionRecord) -> float:
    if r.exit_price is None:
        return 0.0
    ep = float(r.entry_price)
    xp = float(r.exit_price)
    amt = float(r.amount)
    return (xp - ep) * amt if r.side == "BUY" else (ep - xp) * amt
