"""Risk node: risk-based sizing and volatility-regime gate.

Sizing must use the stop the StopLossMonitor will actually apply
(per-symbol override, else max(base, 2.5 x CV)) so that every entry
risks ``risk_per_trade_pct`` of equity at its stop.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trdex.agents.intent import Intent
from trdex.agents.risk import risk_node
from trdex.agents.state import AgentState, AnalysisResult, MarketSnapshot, PortfolioContext
from trdex.config import TrdexMode, get_settings
from trdex.risk.sizing import recent_cv

FLAT = [100.0] * 30  # CV 0     -> stop = base 2%
WILD = [100.0, 130.0] * 15  # CV ~13%  -> stop = 2.5 x CV ~ 33%


def _state(closes, intent=Intent.OPEN_LONG, *, session_factory=None, positions=None) -> AgentState:
    candles = [(i, c, c, c, c, 1.0) for i, c in enumerate(closes)]
    return AgentState(
        symbol="ENJ/USDT",
        run_id="r-sizing",
        market=MarketSnapshot(symbol="ENJ/USDT", price=closes[-1], candles=candles),
        analysis=AnalysisResult(intent=intent, confidence=0.8),
        portfolio=PortfolioContext(
            equity=10_000.0,
            open_position_symbols=positions or [],
            open_position_symbols_by_agent=positions or [],
        ),
        session_factory=session_factory,
    )


class _Cfg:
    """Minimal RuntimeConfigService stand-in: only ``thresholds`` values."""

    def __init__(self, **values):
        self._v = values

    def get_typed(self, category, key, default=None):
        if category != "thresholds" or key not in self._v:
            return default
        return self._v[key]


async def _run(state, *, cfg=None, mode="simulation"):
    ks = AsyncMock()
    ks.active = False
    settings = get_settings().model_copy(update={"mode": TrdexMode(mode)})
    with (
        patch("trdex.risk.stop_loss.get_kill_switch", return_value=ks),
        patch("trdex.services.runtime_config.get_config_service", return_value=cfg),
        patch("trdex.agents.risk.get_settings", return_value=settings),
    ):
        return await risk_node(state)


# ── sizing ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_low_volatility_entry_keeps_the_previous_5pct_size():
    result = await _run(_state(FLAT))
    assert result.risk.approved is True
    assert result.risk.position_size == pytest.approx(0.05)  # 0.1% / 2%, at the cap
    assert "risk 0.100%" in result.risk.reason


@pytest.mark.asyncio
async def test_high_volatility_entry_is_sized_down_to_the_same_risk():
    result = await _run(_state(WILD))
    stop = 2.5 * recent_cv(WILD)
    assert result.risk.approved is True
    assert result.risk.position_size == pytest.approx(0.001 / stop)
    assert result.risk.position_size * stop == pytest.approx(0.001)  # was 5% x 33% = 1.7%


@pytest.mark.asyncio
async def test_sizing_reads_risk_and_cap_from_runtime_config():
    result = await _run(_state(WILD), cfg=_Cfg(risk_per_trade_pct=0.002, max_position_pct=0.03))
    stop = 2.5 * recent_cv(WILD)
    assert result.risk.position_size == pytest.approx(0.002 / stop)
    capped = await _run(_state(FLAT), cfg=_Cfg(risk_per_trade_pct=0.002, max_position_pct=0.03))
    assert capped.risk.position_size == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_sizing_uses_the_per_symbol_override_like_the_monitor(monkeypatch):
    session = MagicMock()

    @asynccontextmanager
    async def factory():
        yield session

    repo = MagicMock()
    repo.get = AsyncMock(return_value=SimpleNamespace(sl_pct=0.08, tp_pct=None, trailing_pct=None))
    monkeypatch.setattr(
        "trdex.storage.symbol_config_repo.SymbolConfigRepository", MagicMock(return_value=repo)
    )
    result = await _run(_state(WILD, session_factory=factory))
    assert result.risk.position_size == pytest.approx(0.001 / 0.08)


@pytest.mark.asyncio
async def test_unreadable_override_blocks_the_entry(monkeypatch):
    @asynccontextmanager
    async def factory():
        yield MagicMock()

    repo = MagicMock()
    repo.get = AsyncMock(side_effect=RuntimeError("db down"))
    monkeypatch.setattr(
        "trdex.storage.symbol_config_repo.SymbolConfigRepository", MagicMock(return_value=repo)
    )
    result = await _run(_state(WILD, session_factory=factory))
    assert result.risk.approved is False
    assert "sizing failed" in result.risk.reason.lower()


@pytest.mark.asyncio
async def test_invalid_risk_value_blocks_the_entry():
    result = await _run(_state(FLAT), cfg=_Cfg(risk_per_trade_pct=0.0))
    assert result.risk.approved is False
    assert "sizing failed" in result.risk.reason.lower()


@pytest.mark.asyncio
async def test_close_is_never_blocked_by_sizing_inputs():
    result = await _run(
        _state(FLAT, Intent.CLOSE_LONG, positions=["ENJ/USDT"]), cfg=_Cfg(risk_per_trade_pct=0.0)
    )
    assert result.risk.approved is True


# ── regime gate ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_regime_gate_blocks_entries_outside_the_tested_range():
    result = await _run(_state(WILD), cfg=_Cfg(regime_cv_min=0.001, regime_cv_max=0.04))
    assert result.risk.approved is False
    assert "above tested range" in result.risk.reason


@pytest.mark.asyncio
async def test_regime_gate_lets_entries_inside_the_range_through():
    calm = [100.0 + (i % 2) for i in range(30)]  # CV ~0.5%
    result = await _run(_state(calm), cfg=_Cfg(regime_cv_min=0.001, regime_cv_max=0.04))
    assert result.risk.approved is True


@pytest.mark.asyncio
async def test_regime_gate_never_blocks_a_close():
    result = await _run(
        _state(WILD, Intent.CLOSE_LONG, positions=["ENJ/USDT"]),
        cfg=_Cfg(regime_cv_min=0.001, regime_cv_max=0.04),
    )
    assert result.risk.approved is True


@pytest.mark.asyncio
async def test_unset_bounds_are_off_in_simulation():
    assert (await _run(_state(WILD))).risk.approved is True


@pytest.mark.asyncio
async def test_unset_bounds_fail_closed_in_live():
    result = await _run(_state(FLAT), mode="live")
    assert result.risk.approved is False
    assert "regime bounds not configured" in result.risk.reason


@pytest.mark.asyncio
async def test_empty_bounds_from_the_dashboard_do_not_block_everything():
    # Runtime Config coerces "" to 0.0 for floats.
    result = await _run(_state(FLAT), cfg=_Cfg(regime_cv_min=0.0, regime_cv_max=0.0))
    assert result.risk.approved is True


@pytest.mark.asyncio
async def test_inverted_bounds_fail_closed():
    result = await _run(_state(FLAT), cfg=_Cfg(regime_cv_min=0.05, regime_cv_max=0.01))
    assert result.risk.approved is False
    assert "invalid regime bounds" in result.risk.reason


# ── parity with the Analyst (the monitor reads the Analyst's CV) ──────────


@pytest.mark.asyncio
async def test_sizing_cv_equals_the_cv_the_analyst_writes_for_the_monitor(monkeypatch):
    from trdex.agents.analyst import analyst_node

    written: dict = {}

    class FakeEntityGraph:
        def __init__(self, session):
            pass

        async def upsert(self, **kw):
            if kw.get("predicate") == "volatility_regime":
                written.update(kw["object_value"])

    @asynccontextmanager
    async def factory():
        yield MagicMock()

    monkeypatch.setattr("trdex.storage.entity_graph_repo.EntityGraphRepository", FakeEntityGraph)
    closes = [100.0 + ((i * 7) % 11) for i in range(60)]
    state = _state(closes, session_factory=factory)
    await analyst_node(state)
    assert written["cv"] == pytest.approx(recent_cv(closes))
