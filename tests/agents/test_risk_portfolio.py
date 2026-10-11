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
from trdex.risk.open_risk import OpenRisk, load_open_risk_in


@asynccontextmanager
async def _factory():
    yield MagicMock()


def _open(monkeypatch, risk_cash=0.0, symbols=()):
    async def fake(*a, **k):
        return OpenRisk(risk_cash, tuple(symbols))

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
    assert result.risk.reason.startswith("Portfolio gate: correlation limit: 2 positions")
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


@pytest.mark.asyncio
async def test_open_risk_uses_the_stop_the_monitor_applies(monkeypatch):
    positions = [
        SimpleNamespace(
            symbol="BTC/USDT", budget=500, stop_loss_pct=None, take_profit_pct=None, source="agent"
        ),
        SimpleNamespace(
            symbol="WILD/USDT",
            budget=500,
            stop_loss_pct=0.05,
            take_profit_pct=None,
            source="agent",
        ),
        SimpleNamespace(
            symbol="TG/USDT",
            budget=100,
            stop_loss_pct=0.03,
            take_profit_pct=None,
            source="telegram",
        ),
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
    with pytest.raises(ValueError):
        risk.fraction(0)
