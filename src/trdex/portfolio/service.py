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
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from sqlalchemy import select

from trdex.market.manager import FeedError, PriceFeedManager
from trdex.portfolio.models import Portfolio, Position
from trdex.storage.balance_models import BalanceRecord
from trdex.storage.balance_repo import BalanceRepository
from trdex.storage.portfolio_models import PositionRecord
from trdex.storage.portfolio_repo import PortfolioRepository


ClosedBy = Literal[
    "agent_signal",
    "stop_loss",
    "take_profit",
    "trailing_stop",
    "kill_switch",
    "manual",
]


def _utcnow_naive() -> datetime:
    return datetime.now(tz=timezone.utc).replace(tzinfo=None)

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
        """Full portfolio snapshot: open positions + realized P&L stats.

        Balance and total realised P&L are read from the ``account_balance``
        ledger — the single source of truth. Previously ``balance`` fell
        back to the Pydantic default ($10,000) because it was never set,
        and ``total_pnl`` was recomputed from ``positions`` without fees,
        drifting from the ledger by one round-trip fee per trade.
        """
        positions = await self.mark_to_market()
        closed = await self._repo.get_closed_positions(limit=10_000)

        bal_repo = BalanceRepository(self._repo._session)
        balance = await bal_repo.current_balance()
        total_pnl = await bal_repo.total_trade_pnl()

        total_trades = len(closed)
        winning_trades = sum(1 for r in closed if _is_win(r))

        return Portfolio(
            balance=balance,
            positions=positions,
            total_trades=total_trades,
            winning_trades=winning_trades,
            total_pnl=total_pnl,
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
        fee: Decimal = Decimal("0"),
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
        # Persist opening fee for full round-trip P&L accounting
        record.fee_open = float(fee)
        session = self._repo._session
        await session.commit()
        await session.refresh(record)
        logger.info(
            "[PortfolioService] opened %s position %d: %s qty=%s @ %s fee=%s (source=%s)",
            symbol,
            record.id,
            side,
            amount,
            entry_price,
            fee,
            source,
        )
        return record

    async def record_close_fill(
        self,
        *,
        position: PositionRecord,
        exit_price: Decimal,
        fee: Decimal = Decimal("0"),
        closed_by: ClosedBy = "agent_signal",
    ) -> tuple[PositionRecord, BalanceRecord]:
        """Persist the closing of a position and write realised PnL to ledger.

        **Atomicity (D17)**: the position update and the balance ledger
        insert are committed in a **single** transaction. Previously the
        WIP commit `815614d` flushed each write with its own commit,
        leaving a window where ``positions.status='closed'`` was
        persisted but no matching ``trade_fill`` row existed (on a crash
        mid-call, the realised PnL would be silently lost). The new
        path uses ``session.add`` + a single terminal ``commit`` so the
        two rows live or die together.

        **Closed-by (D20)**: the caller must indicate which subsystem
        triggered the close. The value is persisted inside the
        ``account_balance.note`` field as ``closed_by=<value>; ...``
        (no column added per D11 rev — inspect_runs parses the note).
        Possible values:

            - ``agent_signal``  — agent runner dispatched a CLOSE intent
            - ``stop_loss``     — StopLossMonitor hit the SL threshold
            - ``take_profit``   — SL monitor hit TP
            - ``trailing_stop`` — SL monitor trailing exit
            - ``kill_switch``   — emergency flatten
            - ``manual``        — telegram or manual tool

        The PnL formula mirrors the one in ``_realized_pnl``:
            BUY  : (exit - entry) * amount - fee
            SELL : (entry - exit) * amount - fee

        Residual risk (D15): in live mode, local DB and exchange state
        can diverge if this call raises AFTER the exchange has filled
        the close order. A future ``fill_reconciliation`` table will
        close that gap — not in scope today.

        Returns the updated position and the new balance ledger row.
        """
        session = self._repo._session

        # 1. Load the live row (inside this session, not trusting the
        #    caller's snapshot). If it vanished — concurrent close by
        #    another subsystem — we raise so the caller can abort.
        result = await session.execute(
            select(PositionRecord).where(PositionRecord.id == position.id)
        )
        live = result.scalar_one_or_none()
        if live is None:
            raise RuntimeError(
                f"record_close_fill: position {position.id} vanished before close"
            )
        if live.status != "open":
            raise RuntimeError(
                f"record_close_fill: position {position.id} is already "
                f"{live.status}, refusing double-close"
            )

        # 2. Compute PnL from the LIVE row (not the caller's snapshot).
        #    Full round-trip cost: fee_open (paid at entry) + fee (paid now at close).
        entry = Decimal(str(live.entry_price))
        amt = Decimal(str(live.amount))
        fee_open = Decimal(str(live.fee_open or 0))
        if live.side == "BUY":
            gross = (exit_price - entry) * amt
        else:  # SELL / short leg (kept for completeness, not reachable today)
            gross = (entry - exit_price) * amt
        pnl = gross - fee - fee_open

        # 3. Mutate the position row. The ORM will flush on commit.
        live.exit_price = exit_price
        live.status = "closed"
        live.closed_at = _utcnow_naive()

        # 4. Compute the new balance_after by reading the latest ledger
        #    row within the same session — still uncommitted writes are
        #    not visible, so this is the authoritative "before" balance.
        bal_repo = BalanceRepository(session)
        current_balance = await bal_repo.current_balance()
        new_balance = current_balance + pnl

        # 5. Append the ledger row without committing.
        balance_row = BalanceRecord(
            event_type="trade_fill",
            amount=pnl,
            balance_after=new_balance,
            note=(
                f"closed_by={closed_by}; close {live.side} {live.symbol} "
                f"position {live.id} @ {exit_price} "
                f"(entry {entry}, qty {amt}, fee {fee})"
            ),
            recorded_at=_utcnow_naive(),
        )
        session.add(balance_row)

        # 6. Single terminal commit — both writes live or die together.
        await session.commit()
        await session.refresh(live)
        await session.refresh(balance_row)

        logger.info(
            "[PortfolioService] closed %s position %d by=%s: pnl=%s new_balance=%s",
            live.symbol, live.id, closed_by, pnl, balance_row.balance_after,
        )
        return live, balance_row


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
