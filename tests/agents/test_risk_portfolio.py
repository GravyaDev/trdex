"""Risk node: portfolio risk budget (REDUCE), correlated clusters, reward/risk."""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from tests.agents.test_risk_sizing_gate import FLAT, _Cfg, _run, _state
from trdex.agents.intent import Intent
from trdex.agents.state import AnalysisResult
from trdex.risk.open_risk import (
    Exposure,
    OpenRisk,
    fetch_prices,
    load_open_risk_in,
    unrealized_pnl,
)


@asynccontextmanager
async def _factory():
    yield MagicMock()


def _open(monkeypatch, risk_cash=0.0, symbols=(), side="BUY"):
    exposures = tuple(Exposure(s, side, 100.0, 1.0) for s in symbols)

    async def fake(*a, **k):
        return OpenRisk(risk_cash, tuple(symbols), exposures)

    monkeypatch.setattr("trdex.risk.open_risk.load_open_risk", fake)


@pytest.fixture(autouse=True)
def _no_symbol_override(monkeypatch):
    repo = MagicMock()

    async def get(symbol):
        return None

    repo.get = get
    monkeypatch.setattr(
        "trdex.storage.symbol_config_repo.SymbolConfigRepository", MagicMock(return_value=repo)
    )


@pytest.mark.asyncio
async def test_entry_is_reduced_to_fit_the_portfolio_budget(monkeypatch):
    _open(monkeypatch, risk_cash=45.0, symbols=["BTC/USDT"])  # 0.45% of 10k equity
    result = await _run(_state(FLAT, session_factory=_factory))
    assert result.risk.approved is True
    assert result.risk.position_size == pytest.approx(0.025)  # 0.05% room / 2% stop
    assert "REDUCED to 2.50% of equity" in result.risk.reason


@pytest.mark.asyncio
async def test_full_budget_rejects_new_entries_but_never_exits(monkeypatch):
    _open(monkeypatch, risk_cash=50.0, symbols=["BTC/USDT"])
    result = await _run(_state(FLAT, session_factory=_factory))
    assert result.risk.approved is False
    assert result.risk.reason.startswith("Portfolio gate: portfolio risk budget exhausted")
    close = await _run(
        _state(FLAT, Intent.CLOSE_LONG, session_factory=_factory, positions=["ENJ/USDT"])
    )
    assert close.risk.approved is True


@pytest.mark.asyncio
async def test_correlated_cluster_cap_blocks_the_entry(monkeypatch):
    _open(monkeypatch, symbols=["BTC/USDT", "ETH/USDT"])
    clusters = json.dumps([["BTC/USDT", "ETH/USDT", "ENJ/USDT"]])
    cfg = _Cfg(correlation_clusters=clusters, max_positions_per_cluster=2)
    result = await _run(_state(FLAT, session_factory=_factory), cfg=cfg)
    assert result.risk.approved is False
    assert result.risk.reason.startswith("Portfolio gate: correlation limit: 2 longs")
    roomier = _Cfg(correlation_clusters=clusters, max_positions_per_cluster=3)
    assert (await _run(_state(FLAT, session_factory=_factory), cfg=roomier)).risk.approved


@pytest.mark.asyncio
async def test_llm_stop_wider_than_the_target_allows_is_rejected():
    state = _state(FLAT)
    state.analysis = AnalysisResult(
        intent=Intent.OPEN_LONG, confidence=0.8, suggested_stop_loss=0.08
    )
    result = await _run(state)
    assert result.risk.approved is False
    assert result.risk.reason.startswith("Reward/risk gate: reward/risk 0.50 < 1.50")
    state.analysis = AnalysisResult(
        intent=Intent.OPEN_LONG,
        confidence=0.8,
        suggested_stop_loss=0.04,
        suggested_take_profit=0.09,
    )
    assert (await _run(state)).risk.approved is True


@pytest.mark.asyncio
async def test_unreadable_open_positions_fail_closed(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("trdex.risk.open_risk.load_open_risk", boom)
    result = await _run(_state(FLAT, session_factory=_factory))
    assert result.risk.approved is False
    assert "portfolio risk check failed (fail-closed): db down" in result.risk.reason


def _pos(symbol, budget, sl, source, side="BUY", entry=100.0):
    return SimpleNamespace(
        symbol=symbol,
        budget=budget,
        stop_loss_pct=sl,
        take_profit_pct=None,
        source=source,
        side=side,
        entry_price=entry,
        amount=budget / entry,
    )


@pytest.mark.asyncio
async def test_open_risk_uses_the_stop_the_monitor_applies(monkeypatch):
    positions = [
        _pos("BTC/USDT", 500, None, "agent"),
        _pos("WILD/USDT", 500, 0.05, "agent"),
        _pos("TG/USDT", 100, 0.03, "telegram"),
    ]

    class Repo:
        def __init__(self, session):
            pass

        async def get_open_positions(self):
            return positions

        async def get_value(self, kind, sym, pred):
            return {"cv": 0.04} if sym == "WILD/USDT" else None

        async def get_map(self):
            return {}

    monkeypatch.setattr("trdex.storage.portfolio_repo.PortfolioRepository", Repo)
    monkeypatch.setattr("trdex.storage.entity_graph_repo.EntityGraphRepository", Repo)
    monkeypatch.setattr("trdex.storage.symbol_config_repo.SymbolConfigRepository", Repo)
    settings = SimpleNamespace(
        sl_position_pct=0.02, sl_take_profit_pct=0.04, sl_trailing_stop_pct=0.015
    )
    risk = await load_open_risk_in(object(), None, settings)
    # BTC: base 2% -> 10; WILD: max(2.5 x 4%, 5%) = 10% -> 50; TG keeps its 3% -> 3
    assert risk.risk_cash == pytest.approx(63.0)
    assert risk.symbols == ("BTC/USDT", "TG/USDT", "WILD/USDT")
    assert risk.fraction(10_000) == pytest.approx(0.0063)
    assert len(risk.exposures) == 3
    with pytest.raises(ValueError):
        risk.fraction(0)


# ── equity: ledger (realised) + unrealised at current prices ──────────────


@pytest.mark.asyncio
async def test_equity_marks_open_positions_to_market_and_tolerates_a_missing_price():
    exposures = [
        Exposure("BTC/USDT", "BUY", 100.0, 5.0),
        Exposure("ETH/USDT", "SELL", 50.0, 2.0),
        Exposure("DOWN/USDT", "BUY", 10.0, 1.0),
    ]

    async def price_of(sym):
        if sym == "DOWN/USDT":
            raise RuntimeError("feed down")
        return {"BTC/USDT": 90.0, "ETH/USDT": 40.0}[sym]

    prices = await fetch_prices([e.symbol for e in exposures], price_of)
    assert prices == {"BTC/USDT": 90.0, "ETH/USDT": 40.0}
    # BTC long -50, ETH short +20, DOWN at entry 0
    assert unrealized_pnl(exposures, prices) == pytest.approx(-30.0)


@pytest.mark.asyncio
async def test_agent_equity_no_longer_books_open_positions_as_losses(monkeypatch):
    """Before: exit_price None -> unrealised = -cost, so two 5% positions read
    as a 10% drawdown and shrank equity for sizing."""
    from trdex.agents import runner as runner_mod

    class PosRepo:
        def __init__(self, session):
            pass

        async def get_open_positions(self):
            return [
                SimpleNamespace(
                    symbol="BTC/USDT",
                    source="agent",
                    side="BUY",
                    entry_price=100.0,
                    amount=5.0,
                    exit_price=None,
                ),
                SimpleNamespace(
                    symbol="ETH/USDT",
                    source="telegram",
                    side="BUY",
                    entry_price=50.0,
                    amount=10.0,
                    exit_price=None,
                ),
            ]

    class BalRepo:
        def __init__(self, session):
            pass

        async def current_balance(self):
            return 10_000

        async def peak_balance(self):
            return 10_000

    class Feeds:
        async def get_ticker(self, sym):
            return SimpleNamespace(price={"BTC/USDT": 110.0, "ETH/USDT": 50.0}[sym])

    monkeypatch.setattr(runner_mod, "PortfolioRepository", PosRepo)
    monkeypatch.setattr(runner_mod, "BalanceRepository", BalRepo)
    ctx = await runner_mod.AgentRunner(MagicMock(), Feeds())._load_portfolio_context()
    assert ctx.equity == pytest.approx(10_050.0)  # +50 unrealised on BTC
    assert ctx.drawdown_pct == 0.0
    assert ctx.open_position_symbols_by_agent == ["BTC/USDT"]


# ── shorts and leverage ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_short_is_approved_with_leverage_on_perps():
    result = await _run(_state(FLAT, Intent.OPEN_SHORT))
    assert result.risk.approved is True and result.risk.leverage == 3
    assert result.risk.position_size == pytest.approx(0.05)  # same risk-based size
    assert "Leverage 3x" in result.risk.reason


@pytest.mark.asyncio
async def test_short_on_spot_is_blocked_but_closing_one_is_not():
    spot = _Cfg(execution_venue="spot")
    result = await _run(_state(FLAT, Intent.OPEN_SHORT), cfg=spot)
    assert result.risk.approved is False
    assert "shorts need the perpetual futures venue" in result.risk.reason
    long_on_spot = await _run(_state(FLAT), cfg=spot)
    assert long_on_spot.risk.approved is True and long_on_spot.risk.leverage == 1
    close = await _run(_state(FLAT, Intent.CLOSE_SHORT, positions=["ENJ/USDT"]), cfg=spot)
    assert close.risk.approved is True


@pytest.mark.asyncio
async def test_opposite_side_on_the_same_symbol_is_blocked_whatever_the_source(monkeypatch):
    _open(monkeypatch, symbols=["ENJ/USDT"], side="BUY")  # e.g. a Telegram long
    result = await _run(_state(FLAT, Intent.OPEN_SHORT, session_factory=_factory))
    assert result.risk.approved is False
    assert "a long is already open on ENJ/USDT" in result.risk.reason


@pytest.mark.asyncio
async def test_stop_too_wide_for_any_leverage_is_rejected():
    wild = [100.0, 300.0] * 15  # CV ~ 50%: adaptive stop far beyond liquidation at 1x
    result = await _run(_state(wild, Intent.OPEN_SHORT))
    assert result.risk.approved is False
    assert result.risk.reason.startswith("Leverage gate:")


@pytest.mark.asyncio
async def test_wide_stop_gets_lower_leverage():
    wild = [100.0, 130.0] * 15  # CV ~13%: stop ~33% -> 1x
    result = await _run(_state(wild, Intent.OPEN_LONG))
    assert result.risk.approved is True and result.risk.leverage == 1
