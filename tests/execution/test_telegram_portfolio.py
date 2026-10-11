"""Telegram entries follow the same portfolio rules as agent entries.

Reward/risk, the correlated-cluster cap and the portfolio risk budget
(reduce first, skip when not even a quarter of the signal budget fits).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.execution.test_telegram_executor import (
    FakeBalance,
    FakeGateway,
    FakePortfolioService,
    _make_executor,
    make_signal,
)
from trdex.execution.telegram_gates import (
    GateConfig,
    gate_cluster,
    gate_reward_risk,
    signal_exit_pcts,
    telegram_budget,
)
from trdex.telegram.parser import TelegramSignal

MAJORS = (frozenset({"BTC/USDT", "ETH/USDT", "SOL/USDT"}),)


def _signal(**over) -> TelegramSignal:
    s = make_signal()
    return TelegramSignal(**{**s.__dict__, **over}) if over else s


# ── pure gates ────────────────────────────────────────────────────────────


def test_exit_distances_come_from_the_signal_or_the_monitor_floors():
    cfg = GateConfig(default_stop_pct=0.02, default_tp_pct=0.04)
    stop, tp = signal_exit_pcts(make_signal(), current_price=91000.0, config=cfg)
    assert (stop, tp) == pytest.approx((0.03, 0.05))  # relative to the signal entry
    bare = _signal(entry=None, stop_loss=None, targets=[])
    assert signal_exit_pcts(bare, current_price=91000.0, config=cfg) == (0.02, 0.04)


def test_reward_risk_gate():
    cfg = GateConfig(min_reward_risk=1.5)
    assert gate_reward_risk(make_signal(), current_price=90000.0, config=cfg).passed  # 1.67
    tight = _signal(targets=[92700.0])  # +3% vs -3%
    result = gate_reward_risk(tight, current_price=90000.0, config=cfg)
    assert not result.passed and result.reason.startswith("reward/risk 1.00 < 1.50")
    assert gate_reward_risk(tight, current_price=90000.0, config=GateConfig()).passed  # off


def test_cluster_gate():
    full = GateConfig(clusters=MAJORS, max_per_cluster=2, open_symbols=("ETH/USDT", "SOL/USDT"))
    result = gate_cluster(make_signal(), config=full)
    assert not result.passed and "correlation limit: 2 positions" in result.reason
    room = GateConfig(clusters=MAJORS, max_per_cluster=3, open_symbols=("ETH/USDT", "SOL/USDT"))
    assert gate_cluster(make_signal(), config=room).passed


def test_budget_fits_reduces_or_skips():
    def budget(open_risk, **kw):
        cfg = GateConfig(portfolio_risk_cap=0.005, open_risk_fraction=open_risk, **kw)
        return telegram_budget(
            make_signal(), current_price=90000.0, cash=Decimal("10000"), config=cfg
        )

    assert budget(0.0) == (Decimal("100"), "")  # 1% of equity x 3% stop = 0.03%
    reduced, note = budget(0.00485)  # 0.015% room -> half the signal budget
    assert reduced == Decimal("50.00") and note.startswith("REDUCED")
    skipped, why = budget(0.00495)  # a sixth fits: skip
    assert skipped is None and "only 17% of the planned size fits" in why
    # equity includes open positions at entry: twice the equity, half the planned size
    assert budget(0.00485, portfolio_equity=Decimal("20000"))[0] == Decimal("100")
    assert budget(0.0, portfolio_equity=Decimal("0"))[0] is None


def test_budget_off_leaves_the_signal_budget_alone():
    out = telegram_budget(
        make_signal(), current_price=90000.0, cash=Decimal("0"), config=GateConfig()
    )
    assert out == (Decimal("100"), "")


# ── executor ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reduced_budget_is_what_gets_ordered_and_recorded():
    gw, svc = FakeGateway(), FakePortfolioService()
    cfg = GateConfig(portfolio_risk_cap=0.005, open_risk_fraction=0.00485)
    ex = _make_executor(gateway=gw, portfolio_service=svc, config=cfg, balance=FakeBalance())
    outcome = await ex.execute(make_signal(), outcome_id=1)
    assert outcome.status == "executed"
    assert gw.calls[0]["qty"] == pytest.approx(50 / 90000.0)
    assert svc.calls[0]["budget"] == Decimal("50.00")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("cfg", "reason"),
    [
        (
            GateConfig(portfolio_risk_cap=0.005, open_risk_fraction=0.006),
            "portfolio risk budget exhausted",
        ),
        (GateConfig(min_reward_risk=2.0), "reward/risk 1.67 < 2.00"),
        (
            GateConfig(clusters=MAJORS, max_per_cluster=1, open_symbols=("ETH/USDT",)),
            "correlation limit",
        ),
    ],
    ids=["budget", "reward-risk", "cluster"],
)
async def test_portfolio_rules_skip_before_any_order(cfg, reason):
    gw = FakeGateway()
    outcome = await _make_executor(gateway=gw, config=cfg).execute(make_signal(), outcome_id=2)
    assert outcome.status == "skipped" and reason in outcome.reason
    assert gw.calls == []
