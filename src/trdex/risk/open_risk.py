"""Risk currently at stake in open positions (all sources).

Each open position loses ``budget x stop`` if its stop is hit, with the
stop computed exactly as the StopLossMonitor applies it
(``effective_thresholds``: per-symbol override, per-position stop, CV
floor from the entity graph). Budget is the notional committed at entry,
so the figure is the risk from the entry price (a trailed stop above
entry risks less; the budget then overstates, never understates).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OpenRisk:
    risk_cash: float  # sum over open positions of budget x effective stop
    symbols: tuple[str, ...]  # symbols with an open position, any source
    committed: float = 0.0  # notional committed at entry (sum of budgets)

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


async def load_open_risk(session_factory: Any, cfg: Any, settings: Any) -> OpenRisk:
    """Open positions' risk at stop. Raises on DB errors (callers fail closed)."""
    async with session_factory() as session:
        return await load_open_risk_in(session, cfg, settings)


async def load_open_risk_in(session: Any, cfg: Any, settings: Any) -> OpenRisk:
    """Same as ``load_open_risk`` within an existing session."""
    from trdex.risk.stop_loss import effective_thresholds
    from trdex.storage.entity_graph_repo import EntityGraphRepository
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.symbol_config_repo import SymbolConfigRepository

    positions = await PortfolioRepository(session).get_open_positions()
    if not positions:
        return OpenRisk(0.0, ())
    graph = EntityGraphRepository(session)
    cvs: dict[str, float] = {}
    for sym in {p.symbol for p in positions}:
        val = await graph.get_value("symbol", sym, "volatility_regime")
        if isinstance(val, dict) and "cv" in val:
            cvs[sym] = float(val["cv"])
    overrides = await SymbolConfigRepository(session).get_map()

    base_sl = _threshold(cfg, "sl_position_pct", settings.sl_position_pct)
    base_tp = _threshold(cfg, "sl_take_profit_pct", settings.sl_take_profit_pct)
    base_trail = _threshold(cfg, "sl_trailing_stop_pct", settings.sl_trailing_stop_pct)
    risk = committed = 0.0
    for p in positions:
        sl, _, _ = effective_thresholds(
            p,
            overrides.get(p.symbol),
            cvs.get(p.symbol, 0.0),
            base_sl=base_sl,
            base_tp=base_tp,
            base_trail=base_trail,
        )
        risk += float(p.budget) * float(sl)
        committed += float(p.budget)
    return OpenRisk(risk, tuple(sorted({p.symbol for p in positions})), committed)
