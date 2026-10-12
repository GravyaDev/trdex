"""Risk currently at stake in open positions (all sources), and equity.

Each open position loses ``budget x stop`` if its stop is hit, with the
stop computed exactly as the StopLossMonitor applies it
(``effective_thresholds``: per-symbol override, per-position stop, CV
floor from the entity graph). Budget is the notional committed at entry,
so the figure is the risk from the entry price (a trailed stop above
entry risks less; the budget then overstates, never understates).

Equity is the ledger balance plus unrealised P&L at current prices. The
ledger is realised-only (opening a position does not debit it), so the
notional of open positions must not be added again.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Exposure:
    symbol: str
    side: str  # "BUY" | "SELL"
    entry_price: float
    amount: float

    def unrealized(self, price: float | None) -> float:
        """P&L at ``price``; 0 without a price (counted at entry)."""
        if price is None or price <= 0:
            return 0.0
        move = price - self.entry_price
        return (move if self.side == "BUY" else -move) * self.amount


def unrealized_pnl(exposures: Iterable[Exposure], prices: Mapping[str, float]) -> float:
    return sum(e.unrealized(prices.get(e.symbol)) for e in exposures)


async def fetch_prices(
    symbols: Iterable[str], price_of: Callable[[str], Awaitable[float]]
) -> dict[str, float]:
    """Current prices; a symbol whose price cannot be fetched is left out
    (its position then counts at entry price) and logged."""
    prices: dict[str, float] = {}
    for sym in sorted(set(symbols)):
        try:
            prices[sym] = float(await price_of(sym))
        except Exception as exc:
            logger.warning("[equity] no price for %s (%s): counted at entry", sym, exc)
    return prices


@dataclass(frozen=True)
class OpenRisk:
    risk_cash: float  # sum over open positions of budget x effective stop
    symbols: tuple[str, ...]  # symbols with an open position, any source
    exposures: tuple[Exposure, ...] = ()

    @property
    def positions(self) -> tuple[tuple[str, str], ...]:
        """(symbol, side) of every open position, for directional checks."""
        return tuple((e.symbol, e.side) for e in self.exposures)

    def opposite_side(self, symbol: str, side: str) -> str | None:
        """Side of an open position on ``symbol`` opposite to ``side``, if any."""
        for e in self.exposures:
            if e.symbol == symbol and e.side != side:
                return e.side
        return None

    def fraction(self, equity: float) -> float:
        """Equity fraction at stake; raises if equity is unknown with risk open."""
        if self.risk_cash <= 0:
            return 0.0
        if equity <= 0:
            raise ValueError("equity unknown (<= 0) while positions are open")
        return self.risk_cash / equity


def _threshold(cfg: Any, key: str, default: float) -> float:
    if cfg is None:
        return float(default)
    value = cfg.get_typed("thresholds", key, default)
    return float(default if value is None else value)


def exit_bases(cfg: Any, settings: Any) -> tuple[float, float, float]:
    """(stop, take-profit, trail) bases the StopLossMonitor is built from."""
    return (
        _threshold(cfg, "sl_position_pct", settings.sl_position_pct),
        _threshold(cfg, "sl_take_profit_pct", settings.sl_take_profit_pct),
        _threshold(cfg, "sl_trailing_stop_pct", settings.sl_trailing_stop_pct),
    )


async def monitor_cv(session: Any, symbol: str) -> float:
    """The CV the StopLossMonitor floors the exits with (entity graph), 0 if unknown."""
    from trdex.storage.entity_graph_repo import EntityGraphRepository

    val = await EntityGraphRepository(session).get_value("symbol", symbol, "volatility_regime")
    return float(val["cv"]) if isinstance(val, dict) and "cv" in val else 0.0


async def load_open_risk(session_factory: Any, cfg: Any, settings: Any) -> OpenRisk:
    """Open positions' risk at stop. Raises on DB errors (callers fail closed)."""
    async with session_factory() as session:
        return await load_open_risk_in(session, cfg, settings)


async def load_open_risk_in(session: Any, cfg: Any, settings: Any) -> OpenRisk:
    """Same as ``load_open_risk`` within an existing session."""
    from trdex.risk.stop_loss import effective_thresholds
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.symbol_config_repo import SymbolConfigRepository

    positions = await PortfolioRepository(session).get_open_positions()
    if not positions:
        return OpenRisk(0.0, ())
    cvs = {sym: await monitor_cv(session, sym) for sym in {p.symbol for p in positions}}
    overrides = await SymbolConfigRepository(session).get_map()

    base_sl, base_tp, base_trail = exit_bases(cfg, settings)
    risk = 0.0
    for p in positions:
        sl, _, _ = effective_thresholds(
            p,
            overrides.get(p.symbol),
            cvs[p.symbol],
            base_sl=base_sl,
            base_tp=base_tp,
            base_trail=base_trail,
        )
        risk += float(p.budget) * float(sl)
    exposures = tuple(
        Exposure(p.symbol, str(p.side), float(p.entry_price), float(p.amount)) for p in positions
    )
    return OpenRisk(risk, tuple(sorted({p.symbol for p in positions})), exposures)
