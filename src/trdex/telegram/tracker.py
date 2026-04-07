"""SignalTracker: tracks P&L and reliability per Telegram signal source."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class SignalOutcome:
    """Result of a single executed signal."""

    source: str
    symbol: str
    direction: str
    entry_price: Decimal
    exit_price: Decimal
    budget: Decimal           # fixed budget allocated to this signal
    executed_at: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    closed_at: datetime | None = None

    @property
    def pnl(self) -> Decimal:
        """Absolute P&L in quote currency."""
        qty = self.budget / self.entry_price
        if self.direction == "BUY":
            return (self.exit_price - self.entry_price) * qty
        return (self.entry_price - self.exit_price) * qty

    @property
    def pnl_pct(self) -> Decimal:
        """P&L as percentage of budget."""
        if self.entry_price == 0:
            return Decimal("0")
        return self.pnl / self.budget * 100


@dataclass
class SourceStats:
    """Aggregated performance statistics for a single signal source."""

    source: str
    total_signals: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: Decimal = Decimal("0")
    budget_allocated: Decimal = Decimal("0")

    @property
    def win_rate(self) -> float:
        if self.total_signals == 0:
            return 0.0
        return self.wins / self.total_signals

    @property
    def roi_pct(self) -> Decimal:
        if self.budget_allocated == 0:
            return Decimal("0")
        return self.total_pnl / self.budget_allocated * 100


class SignalTracker:
    """Tracks signal outcomes and computes per-source reliability metrics.

    In-memory store backed by DB persistence.
    Call `load_from_db(session_factory)` at startup to restore history.
    Call `record_and_persist(outcome, session_factory)` to record + save atomically.

    Usage:
        tracker = SignalTracker(default_budget=Decimal("100"))
        await tracker.load_from_db(session_factory)
        await tracker.record_and_persist(outcome, session_factory)
        report = tracker.report()
    """

    def __init__(self, default_budget: Decimal = Decimal("100")) -> None:
        self.default_budget = default_budget
        self._outcomes: list[SignalOutcome] = []

    def record(self, outcome: SignalOutcome) -> None:
        """Record in memory only (no DB write)."""
        self._outcomes.append(outcome)

    async def record_and_persist(self, outcome: SignalOutcome, session_factory) -> None:
        """Record in memory and persist to DB atomically."""
        self._outcomes.append(outcome)
        try:
            from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
            async with session_factory() as session:
                repo = SignalOutcomeRepository(session)
                await repo.save(
                    source=outcome.source,
                    symbol=outcome.symbol,
                    direction=outcome.direction,
                    entry_price=outcome.entry_price,
                    exit_price=outcome.exit_price,
                    budget=outcome.budget,
                    executed_at=outcome.executed_at,
                    closed_at=outcome.closed_at,
                )
        except Exception:
            logger.exception("[SignalTracker] failed to persist outcome for %s", outcome.source)

    async def load_from_db(self, session_factory) -> None:
        """Reload all historical outcomes from DB into memory (call once at startup)."""
        try:
            from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
            async with session_factory() as session:
                repo = SignalOutcomeRepository(session)
                records = await repo.all()
            self._outcomes = [
                SignalOutcome(
                    source=r.source,
                    symbol=r.symbol,
                    direction=r.direction,
                    entry_price=r.entry_price,
                    exit_price=r.exit_price,
                    budget=r.budget,
                    executed_at=r.executed_at.replace(tzinfo=timezone.utc) if r.executed_at else datetime.now(tz=timezone.utc),
                    closed_at=r.closed_at.replace(tzinfo=timezone.utc) if r.closed_at else None,
                )
                for r in records
            ]
            logger.info("[SignalTracker] loaded %d outcomes from DB", len(self._outcomes))
        except Exception:
            logger.exception("[SignalTracker] failed to load from DB — starting with empty history")

    def stats(self, source: str) -> SourceStats:
        """Compute stats for a specific signal source."""
        relevant = [o for o in self._outcomes if o.source == source]
        s = SourceStats(source=source)
        for o in relevant:
            s.total_signals += 1
            s.budget_allocated += o.budget
            s.total_pnl += o.pnl
            if o.pnl >= 0:
                s.wins += 1
            else:
                s.losses += 1
        return s

    def report(self) -> list[SourceStats]:
        """Return stats for all known sources, sorted by ROI descending."""
        sources = {o.source for o in self._outcomes}
        all_stats = [self.stats(src) for src in sources]
        return sorted(all_stats, key=lambda s: s.roi_pct, reverse=True)
