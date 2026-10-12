"""Telegram entries follow the same portfolio rules as agent entries.

Reward/risk, the correlated-cluster cap and the portfolio risk budget
(reduce first, skip when not even a quarter of the signal budget fits).
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from types import SimpleNamespace

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
from trdex.risk.leverage import DerivativesConfig
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
    full = GateConfig(clusters=MAJORS, max_per_cluster=2, open_positions=("ETH/USDT", "SOL/USDT"))
    result = gate_cluster(make_signal(), config=full)
    assert not result.passed and "correlation limit: 2 longs" in result.reason
    room = GateConfig(clusters=MAJORS, max_per_cluster=3, open_positions=("ETH/USDT", "SOL/USDT"))
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
    # the equity snapshot (ledger + unrealised) wins over the cash balance
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
            GateConfig(clusters=MAJORS, max_per_cluster=1, open_positions=("ETH/USDT",)),
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


# ── exits: what the StopLossMonitor will apply ────────────────────────────


def test_exits_follow_the_monitor_cv_floor_and_symbol_override():
    bare = _signal(entry=None, stop_loss=None, targets=[])
    wild = GateConfig(default_stop_pct=0.02, default_tp_pct=0.04, exit_cv=0.03)
    # no stop in the signal: max(2%, 2.5 x 3%) and max(4%, 5 x 3%)
    assert signal_exit_pcts(bare, current_price=90000.0, config=wild) == pytest.approx(
        (0.075, 0.15)
    )
    # the signal's own stop is kept as-is (monitor rule for Telegram positions)
    assert signal_exit_pcts(make_signal(), current_price=90000.0, config=wild)[0] == (
        pytest.approx(0.03)
    )
    override = SimpleNamespace(sl_pct=0.08, tp_pct=None, trailing_pct=None)
    cfg = GateConfig(exit_override=override)
    assert signal_exit_pcts(make_signal(), current_price=90000.0, config=cfg) == pytest.approx(
        (0.08, 0.05)
    )
    rr = gate_reward_risk(
        make_signal(), current_price=90000.0, config=replace(cfg, min_reward_risk=1.5)
    )
    assert not rr.passed and "take-profit 5.00% vs stop 8.00%" in rr.reason


def test_budget_uses_the_stop_the_monitor_will_apply():
    bare = _signal(entry=None, stop_loss=None, targets=[])
    cfg = GateConfig(portfolio_risk_cap=0.005, open_risk_fraction=0.0049, exit_cv=0.03)
    # 1% of equity x 7.5% stop = 0.075% planned; 0.01% room -> 13%: skip
    budget, why = telegram_budget(bare, current_price=90000.0, cash=Decimal("10000"), config=cfg)
    assert budget is None and "only 13% of the planned size fits" in why


# ── GateConfig wiring for a real signal ───────────────────────────────────


class _Svc:
    def get(self, category, key, default=""):
        return default

    def get_typed(self, category, key, default=None):
        return default


@pytest.mark.asyncio
async def test_gate_config_uses_ledger_plus_unrealised_as_equity(monkeypatch):
    """The ledger is realised-only: open positions must not be added on top."""
    from trdex.api.app import build_telegram_gate_config

    open_eth = SimpleNamespace(
        symbol="ETH/USDT",
        budget=2400,
        stop_loss_pct=None,
        take_profit_pct=None,
        source="agent",
        side="BUY",
        entry_price=100.0,
        amount=24.0,
    )

    class Repo:
        def __init__(self, session):
            pass

        async def get_open_positions(self):
            return [open_eth]

        async def get_value(self, kind, sym, pred):
            return {"cv": 0.004}

        async def get_map(self):
            return {}

        async def get(self, symbol):
            return None

        async def current_balance(self):
            return Decimal("10000")

    for target in (
        "trdex.storage.portfolio_repo.PortfolioRepository",
        "trdex.storage.entity_graph_repo.EntityGraphRepository",
        "trdex.storage.symbol_config_repo.SymbolConfigRepository",
        "trdex.storage.balance_repo.BalanceRepository",
    ):
        monkeypatch.setattr(target, Repo)

    class Feeds:
        price = 100.0

        async def get_ticker(self, sym):
            return SimpleNamespace(price=self.price)

    settings = SimpleNamespace(
        mode=SimpleNamespace(value="simulation"),
        telegram_signal_budget=100,
        sl_position_pct=0.02,
        sl_take_profit_pct=0.04,
        sl_trailing_stop_pct=0.015,
    )
    feeds = Feeds()
    config, cash = await build_telegram_gate_config(
        make_signal(), session=object(), svc=_Svc(), settings=settings, feed_manager=feeds
    )
    assert cash == Decimal("10000") and config.portfolio_equity == Decimal("10000.0")
    assert config.open_risk_fraction == pytest.approx(48 / 10_000)  # 2,400 x 2%
    assert config.open_positions == (("ETH/USDT", "BUY"),) and config.exit_cv == 0.004
    assert config.derivatives.perps  # default venue: usdm
    feeds.price = 90.0  # -240 unrealised
    config, _ = await build_telegram_gate_config(
        make_signal(), session=object(), svc=_Svc(), settings=settings, feed_manager=feeds
    )
    assert config.portfolio_equity == Decimal("9760.0")


# ── shorts and leverage ───────────────────────────────────────────────────

PERPS = GateConfig(derivatives=DerivativesConfig())


def _short(**over):
    base = dict(
        source="chat-1", symbol="BTC/USDT", direction="SELL", entry=90000.0,
        targets=[85500.0], stop_loss=92700.0, raw_text="SELL BTC",
    )
    return TelegramSignal(**{**base, **over})


@pytest.mark.asyncio
async def test_sell_signal_opens_a_leveraged_short_on_perps():
    gw, svc = FakeGateway(), FakePortfolioService()
    outcome = await _make_executor(gateway=gw, portfolio_service=svc, config=PERPS).execute(
        _short(), outcome_id=11
    )
    assert outcome.status == "executed"
    assert gw.calls[0]["direction"] == "SELL" and gw.calls[0]["leverage"] == 3
    assert svc.calls[0]["side"] == "SELL" and svc.calls[0]["leverage"] == 3
    assert svc.calls[0]["stop_loss_pct"] == pytest.approx(0.03)


@pytest.mark.asyncio
async def test_short_against_an_open_long_on_the_same_symbol_is_skipped():
    from tests.execution.test_telegram_executor import FakePortfolioRepo, FakePosition

    repo = FakePortfolioRepo([FakePosition(symbol="BTC/USDT", side="BUY", source="agent")])
    gw = FakeGateway()
    outcome = await _make_executor(gateway=gw, portfolio_repo=repo, config=PERPS).execute(
        _short(), outcome_id=12
    )
    assert outcome.status == "skipped" and "opposite sides" in outcome.reason
    assert gw.calls == []


@pytest.mark.asyncio
async def test_stop_beyond_liquidation_reach_is_skipped():
    cfg = replace(PERPS, max_stop_distance=0.9)
    gw = FakeGateway()
    outcome = await _make_executor(gateway=gw, config=cfg).execute(
        _short(stop_loss=140000.0), outcome_id=13  # +55% stop
    )
    assert outcome.status == "skipped" and outcome.reason.startswith("leverage gate:")
    assert gw.calls == []


def test_cluster_cap_for_telegram_counts_the_same_direction():
    cfg = replace(PERPS, clusters=MAJORS, max_per_cluster=1,
                  open_positions=(("ETH/USDT", "BUY"),))
    assert gate_cluster(_short(), config=cfg).passed  # a short against longs: a hedge
    assert not gate_cluster(make_signal(), config=cfg).passed
