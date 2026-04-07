"""PortfolioService: mark-to-market, snapshot, and fill persistence.

This service is the single choke point for every mutation of the
portfolio state. The execution gateway (Simulator or LiveExecutor)
produces raw ``ExecutionResult`` objects without knowing anything about
positions or the ledger — it's this service's job to translate a fill
into:

    - a new ``positions`` row (on position open)
    - an updated ``positions`` row + ``account_balance`` trade_fill row
      (on position close, with realised PnL computed here)

Call sites:

    - ``agents/runner.py`` after a successful agent cycle BUY fill
    - ``risk/stop_loss.py`` after a successful auto-close
    - ``telegram/tracker.py`` (future) for telegram-signal fills
"""

from __future__ import annotations

import asyncio
import logging
from decimal import Decimal

from trdex.market.manager import FeedError, PriceFeedManager
from trdex.portfolio.models import Portfolio, Position
from trdex.storage.balance_models import BalanceRecord
from trdex.storage.balance_repo import BalanceRepository
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

    # ── write path: persist fills ─────────────────────────────────────────

    async def record_open_fill(
        self,
        *,
        symbol: str,
        side: str,
        amount: Decimal,
        entry_price: Decimal,
        budget: Decimal,
        source: str = "agent",
        signal_id: str | None = None,
    ) -> PositionRecord | None:
        """Persist an open position after a successful fill.

        This is the single write path for "the executor filled an order
        and we now own a position". Long-only by design: a ``SELL`` fill
        without an existing open position is logged as a warning and
        ignored (opening a short is out of scope for the current system).

        Returns the newly created ``PositionRecord`` or ``None`` if the
        fill was skipped.
        """
        if side == "SELL":
            logger.warning(
                "[PortfolioService] refusing to open SHORT position on %s "
                "(sell fill without existing long) — system is long-only",
                symbol,
            )
            return None

        if side != "BUY":
            logger.warning(
                "[PortfolioService] unknown side %r for %s — ignoring fill",
                side, symbol,
            )
            return None

        record = await self._repo.open_position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            amount=amount,
            budget=budget,
            source=source,
            signal_id=signal_id,
        )
        logger.info(
            "[PortfolioService] opened %s position %d: %s qty=%s @ %s (source=%s)",
            symbol,
            record.id,
            side,
            amount,
            entry_price,
            source,
        )
        return record

    async def record_close_fill(
        self,
        *,
        position: PositionRecord,
        exit_price: Decimal,
        fee: Decimal = Decimal("0"),
    ) -> tuple[PositionRecord, BalanceRecord]:
        """Persist the closing of a position and write realised PnL to ledger.

        Updates ``positions.status = 'closed'`` and writes one
        ``account_balance`` row with ``event_type = 'trade_fill'`` whose
        ``amount`` is the realised PnL net of ``fee``.

        The PnL formula mirrors the one in ``_realized_pnl``:
            BUY  : (exit - entry) * amount - fee
            SELL : (entry - exit) * amount - fee

        Returns the updated position and the new balance ledger row.
        """
        closed = await self._repo.close_position(
            position_id=position.id, exit_price=exit_price
        )
        if closed is None:
            raise RuntimeError(
                f"close_position({position.id}) returned None — position vanished?"
            )

        # Compute realised PnL net of the fee paid on close.
        entry = Decimal(str(position.entry_price))
        amt = Decimal(str(position.amount))
        if position.side == "BUY":
            gross = (exit_price - entry) * amt
        else:  # SELL / short leg (kept for completeness, not reachable today)
            gross = (entry - exit_price) * amt
        pnl = gross - fee

        # Ledger write via raw BalanceRepository so we can use the same
        # session as the position update. The balance_after is computed
        # as (current balance + pnl).
        bal_repo = BalanceRepository(self._repo._session)  # share session
        balance_row = await bal_repo.record_event(
            event_type="trade_fill",
            amount=pnl,
            note=(
                f"close {closed.side} {closed.symbol} "
                f"position {closed.id} @ {exit_price} "
                f"(entry {entry}, qty {amt}, fee {fee})"
            ),
        )

        logger.info(
            "[PortfolioService] closed %s position %d: pnl=%s new_balance=%s",
            closed.symbol, closed.id, pnl, balance_row.balance_after,
        )
        return closed, balance_row


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
