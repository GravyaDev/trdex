"""Telegram entries go through the same volatility-regime gate as agent entries.

Risk Gate 4c blocks agent entries outside the CV range the strategy was
backtested on; before this, Telegram signals bypassed it entirely.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.execution.test_telegram_executor import (
    FakeFeed,
    FakeGateway,
    _make_executor,
    make_signal,
)
from trdex.execution.telegram_gates import GateConfig, gate_regime, regime_gate_settings
from trdex.risk.sizing import RegimeBounds, recent_cv

CALM = [90000.0 + (i % 2) * 450 for i in range(20)]  # CV ~0.25%
WILD = [90000.0, 117000.0] * 10  # CV ~13%
BOUNDS = RegimeBounds(cv_min=0.001, cv_max=0.04)
NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


class ClosesFeed(FakeFeed):
    def __init__(self, closes, *, raises=None):
        super().__init__(price=90000.0)
        self._closes = closes
        self._raises = raises
        self.calls: list[tuple[str, int]] = []

    async def get_recent_closes(self, symbol, limit):
        self.calls.append((symbol, limit))
        if self._raises:
            raise self._raises
        return self._closes[-limit:]


# ── gate_regime (pure) ────────────────────────────────────────────────────


def test_unconfigured_bounds_pass():
    assert gate_regime(make_signal(), cv=None, config=GateConfig()).passed


def test_inside_range_passes_outside_blocks():
    cfg = GateConfig(regime=BOUNDS)
    assert gate_regime(make_signal(), cv=0.01, config=cfg).passed
    above = gate_regime(make_signal(), cv=0.13, config=cfg)
    below = gate_regime(make_signal(), cv=0.0001, config=cfg)
    assert not above.passed and "above tested range" in above.reason
    assert not below.passed and "below tested range" in below.reason


def test_unknown_cv_blocks_when_bounds_apply():
    result = gate_regime(make_signal(), cv=None, config=GateConfig(regime=BOUNDS))
    assert not result.passed
    assert "volatility unknown" in result.reason


def test_blocker_blocks_regardless_of_cv():
    cfg = GateConfig(regime=BOUNDS, regime_blocker="regime bounds stale")
    result = gate_regime(make_signal(), cv=0.01, config=cfg)
    assert not result.passed
    assert result.reason == "volatility regime gate: regime bounds stale"


# ── executor ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_calm_market_executes_with_one_closes_fetch():
    feed, gw = ClosesFeed(CALM), FakeGateway()
    ex = _make_executor(feed=feed, gateway=gw, config=GateConfig(regime=BOUNDS))
    outcome = await ex.execute(make_signal(), outcome_id=1)
    assert outcome.status == "executed"
    assert feed.calls == [("BTC/USDT", 20)]
    assert recent_cv(CALM) < BOUNDS.cv_max


@pytest.mark.asyncio
async def test_wild_market_is_skipped_before_any_order():
    feed, gw = ClosesFeed(WILD), FakeGateway()
    ex = _make_executor(feed=feed, gateway=gw, config=GateConfig(regime=BOUNDS))
    outcome = await ex.execute(make_signal(), outcome_id=2)
    assert outcome.status == "skipped"
    assert "above tested range" in outcome.reason
    assert gw.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "feed",
    [
        FakeFeed(price=90000.0),
        ClosesFeed(CALM, raises=RuntimeError("feed down")),
        ClosesFeed([90000.0]),
    ],
    ids=["no-closes-api", "fetch-error", "too-few-closes"],
)
async def test_unknown_volatility_fails_closed(feed):
    gw = FakeGateway()
    ex = _make_executor(feed=feed, gateway=gw, config=GateConfig(regime=BOUNDS))
    outcome = await ex.execute(make_signal(), outcome_id=3)
    assert outcome.status == "skipped"
    assert "volatility unknown" in outcome.reason
    assert gw.calls == []


@pytest.mark.asyncio
async def test_no_closes_fetch_when_the_gate_is_off_or_an_earlier_gate_fails():
    off = ClosesFeed(WILD)
    assert (
        await _make_executor(feed=off).execute(make_signal(), outcome_id=4)
    ).status == "executed"
    assert off.calls == []

    drift = ClosesFeed(CALM)
    ex = _make_executor(feed=drift, config=GateConfig(regime=BOUNDS))
    outcome = await ex.execute(make_signal(entry=80000.0), outcome_id=5)  # 12% drift
    assert "entry drift" in outcome.reason
    assert drift.calls == []


@pytest.mark.asyncio
async def test_blocker_skips_without_fetching_closes():
    feed, gw = ClosesFeed(CALM), FakeGateway()
    cfg = GateConfig(regime=BOUNDS, regime_blocker="Regime bounds: not set")
    outcome = await _make_executor(feed=feed, gateway=gw, config=cfg).execute(
        make_signal(), outcome_id=6
    )
    assert outcome.status == "skipped"
    assert "Regime bounds: not set" in outcome.reason
    assert feed.calls == [] and gw.calls == []


# ── regime_gate_settings (Runtime Config -> GateConfig) ───────────────────


class _Cfg:
    def __init__(self, **t):
        self._t = {k: str(v) for k, v in t.items()}

    def get(self, category, key, default=""):
        return self._t.get(key, default) if category == "thresholds" else default

    def get_typed(self, category, key, default=None):
        return int(self._t[key]) if key in self._t else default


FRESH = {
    "regime_cv_min": 0.001,
    "regime_cv_max": 0.04,
    "regime_data_end": (NOW - timedelta(days=10)).date().isoformat(),
    "regime_set_at": (NOW - timedelta(days=60)).isoformat(),
}


@pytest.mark.parametrize("live", [False, True])
def test_fresh_bounds_apply_in_both_modes(live):
    bounds, blocker = regime_gate_settings(_Cfg(**FRESH), live=live, now=NOW)
    assert bounds == BOUNDS
    assert blocker is None


def test_simulation_unset_bounds_turn_the_gate_off():
    assert regime_gate_settings(_Cfg(), live=False, now=NOW) == (RegimeBounds(), None)


def test_live_unset_bounds_block_like_risk_gate_4c():
    _, blocker = regime_gate_settings(_Cfg(), live=True, now=NOW)
    assert blocker is not None and "not set" in blocker


def test_live_stale_bounds_block_like_readiness():
    stale = {**FRESH, "regime_data_end": (NOW - timedelta(days=120)).date().isoformat()}
    _, blocker = regime_gate_settings(_Cfg(**stale), live=True, now=NOW)
    assert blocker is not None and "120 days ago > 90" in blocker
    # simulation does not enforce freshness (the agent path does not either)
    assert regime_gate_settings(_Cfg(**stale), live=False, now=NOW)[1] is None


@pytest.mark.parametrize("live", [False, True])
@pytest.mark.parametrize(
    "bad",
    [{"regime_cv_min": "abc"}, {"regime_cv_min": 0.05, "regime_cv_max": 0.01}],
    ids=["non-numeric", "inverted"],
)
def test_invalid_bounds_block_in_both_modes(live, bad):
    _, blocker = regime_gate_settings(_Cfg(**{**FRESH, **bad}), live=live, now=NOW)
    assert blocker is not None and "invalid regime bounds" in blocker


def test_missing_runtime_config_blocks():
    assert regime_gate_settings(None, live=False, now=NOW)[1] is not None
