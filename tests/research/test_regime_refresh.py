"""Regime refresher: data sync, revalidation, bounds, watchdog notifications.

The point of the job is that nobody has to remember anything: bounds are
renewed only when the live rules still pass, otherwise they expire and
the operator is told — before and after.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, ClassVar

import pytest

from trdex.market.models import OHLCV
from trdex.notify.events import Event
from trdex.research import regime_refresh as rr
from trdex.research.engine import BacktestResult, EngineParams
from trdex.research.regime_refresh import (
    RefreshConfig,
    RefreshOutcome,
    RegimeWatchdog,
    ValidationCriteria,
    build_refresh_config,
    evaluate,
    load_symbol,
    sync_symbol,
    validation_failures,
)
from trdex.services.runtime_config import RuntimeConfigService

H = 3_600_000
NOW = datetime(2026, 10, 9, 12, 30, tzinfo=UTC)
NOW_MS = int(NOW.timestamp() * 1000)
FORMING = (NOW_MS // H) * H  # open time of the bar still forming at NOW


def _result(**kw) -> BacktestResult:
    base = dict(
        strategy_name="LiveRuleEngine",
        final_equity=11_000.0,
        total_pnl=1_000.0,
        return_pct=10.0,
        trades_count=200,
        wins=100,
        win_rate=0.5,
        sharpe=1.5,
        max_drawdown_pct=8.0,
        exit_reasons={},
        trades=[],
        per_symbol={},
        per_quarter={},
    )
    return BacktestResult(**{**base, **kw})


# ── validation ────────────────────────────────────────────────────────────


def test_a_good_backtest_passes():
    assert validation_failures(_result(), ValidationCriteria(), dev_days=1200) == []


@pytest.mark.parametrize(
    "kw,dev_days,needle",
    [
        ({}, 200, "history 200 days < 365 required"),
        ({"trades_count": 5}, 1200, "trades 5 < 20"),
        ({"return_pct": -0.5}, 1200, "net return -0.50% <= 0"),
        ({"return_pct": 0.0}, 1200, "net return +0.00% <= 0"),
        ({"win_rate": 0.3}, 1200, "win rate 30.0% < 40.0%"),
        ({"max_drawdown_pct": 25.0}, 1200, "max drawdown 25.0% > 20%"),
        ({"sharpe": 0.4}, 1200, "Sharpe 0.40 < 1.00"),
    ],
)
def test_each_criterion_can_fail_the_revalidation(kw, dev_days, needle):
    failures = validation_failures(_result(**kw), ValidationCriteria(), dev_days=dev_days)
    assert failures == [needle]


# ── evaluate ──────────────────────────────────────────────────────────────


def _bars(n, *, start_ms, wild_from=None):
    out, p = [], 100.0
    for i in range(n):
        amp = 0.15 if wild_from is not None and i >= wild_from else 0.004
        c = p * (1 + (amp if i % 2 else -amp))
        out.append([start_ms + i * H, p, max(p, c), min(p, c), c, 1.0])
        p = c
    return out


CFG = RefreshConfig(symbols=("A/USDT",), engine=EngineParams(), risk_per_trade_pct=0.001)


def test_bounds_and_backtest_see_only_the_development_period(monkeypatch):
    start = NOW_MS - 2000 * 24 * H
    data = {"A/USDT": _bars(48_000, start_ms=start, wild_from=40_000)}  # holdout is wild
    seen = {}

    def fake_backtest(strategy, dev, params):
        seen["last_ts"] = max(b[-1][0] for b in dev.values())
        seen["risk"] = strategy.risk_per_trade_pct_override
        return _result()

    monkeypatch.setattr(rr, "run_backtest", fake_backtest)
    out = evaluate(data, CFG)
    cutoff_ms = start + int((data["A/USDT"][-1][0] - start) * 0.7)
    assert seen["last_ts"] < cutoff_ms
    assert seen["risk"] == 0.001
    assert out.status == "refreshed"
    assert out.cv_max < 0.02  # the 15% swings of the holdout are not in the range
    assert out.data_end == datetime.fromtimestamp(data["A/USDT"][-1][0] / 1000, tz=UTC).date()
    assert "refreshed: CV" in out.summary()


def test_failed_revalidation_produces_no_bounds(monkeypatch):
    monkeypatch.setattr(rr, "run_backtest", lambda *a: _result(return_pct=-3.0))
    out = evaluate({"A/USDT": _bars(20_000, start_ms=NOW_MS - 900 * 24 * H)}, CFG)
    assert out.status == "validation_failed"
    assert out.cv_min is None and out.cv_max is None
    assert "net return -3.00% <= 0" in out.summary()


def test_no_data_is_an_error_not_a_validation_result():
    with pytest.raises(ValueError):
        evaluate({"A/USDT": []}, CFG)


# ── OHLCV sync ────────────────────────────────────────────────────────────


class FakeStore:
    rows: ClassVar[dict[str, dict[int, Any]]] = {}

    def __init__(self, session):
        pass

    async def time_range(self, symbol, timeframe):
        ts = sorted(FakeStore.rows.get(symbol, {}))
        if not ts:
            return None, None
        f = lambda ms: datetime.fromtimestamp(ms / 1000, tz=UTC).replace(tzinfo=None)  # noqa: E731
        return f(ts[0]), f(ts[-1])

    async def upsert(self, symbol, timeframe, candles, source="binance"):
        store = FakeStore.rows.setdefault(symbol, {})
        new = 0
        for c in candles:
            ms = int(c.timestamp.timestamp() * 1000)
            if ms not in store:
                store[ms] = c
                new += 1
        return new

    async def fetch(self, symbol, timeframe, since=None, limit=500):
        since_ms = int(since.replace(tzinfo=UTC).timestamp() * 1000) if since else 0
        out = []
        for ms in sorted(FakeStore.rows.get(symbol, {})):
            if ms >= since_ms:
                c = FakeStore.rows[symbol][ms]
                out.append(
                    SimpleNamespace(
                        timestamp=c.timestamp.replace(tzinfo=None),
                        open=c.open,
                        high=c.high,
                        low=c.low,
                        close=c.close,
                        volume=c.volume,
                    )
                )
        return out[:limit]


@pytest.fixture
def store(monkeypatch):
    FakeStore.rows = {}
    monkeypatch.setattr("trdex.storage.ohlcv_repo.OHLCVRepository", FakeStore)

    @asynccontextmanager
    async def factory():
        yield object()

    return factory


def _exchange(listed_ms, clock=None):
    """Fake 1h feed: bars from ``listed_ms`` up to and including the forming one.

    ``clock[0]`` is the exchange's current forming bar (default: at NOW).
    """
    calls = []
    clock = clock if clock is not None else [FORMING]

    async def fetch_page(symbol, since_ms):
        calls.append(since_ms)
        first = max(since_ms, listed_ms)
        first = -(-first // H) * H
        return [
            OHLCV(
                timestamp=datetime.fromtimestamp(ms / 1000, tz=UTC),
                open=Decimal(100),
                high=Decimal(101),
                low=Decimal(99),
                close=Decimal(100),
                volume=Decimal(1),
            )
            for ms in range(first, min(first + 1000 * H, clock[0] + H), H)
        ]

    return fetch_page, calls


@pytest.mark.asyncio
async def test_first_sync_backfills_the_lookback_without_the_forming_bar(store):
    fetch, calls = _exchange(listed_ms=0)
    await sync_symbol(store, fetch, "A/USDT", lookback_days=100, now=NOW)
    stored = sorted(FakeStore.rows["A/USDT"])
    assert stored[0] == FORMING - 100 * 24 * H
    assert stored[-1] == FORMING - H  # forming bar excluded
    assert len(stored) == 100 * 24
    assert len(calls) == 3  # 2400 bars / 1000 per page


@pytest.mark.asyncio
async def test_next_sync_only_forward_fills(store):
    clock = [FORMING]
    fetch, calls = _exchange(listed_ms=0, clock=clock)
    await sync_symbol(store, fetch, "A/USDT", lookback_days=100, now=NOW)
    calls.clear()
    later = NOW + timedelta(days=7)
    clock[0] = FORMING + 7 * 24 * H
    await sync_symbol(store, fetch, "A/USDT", lookback_days=100, now=later)
    assert calls == [FORMING]  # one page, resuming after the last stored bar
    assert max(FakeStore.rows["A/USDT"]) == clock[0] - H


@pytest.mark.asyncio
async def test_recently_listed_coin_costs_one_request_for_the_missing_past(store):
    listed = FORMING - 30 * 24 * H
    fetch, calls = _exchange(listed_ms=listed)
    await sync_symbol(store, fetch, "NEW/USDT", lookback_days=100, now=NOW)
    calls.clear()
    await sync_symbol(store, fetch, "NEW/USDT", lookback_days=100, now=NOW)
    assert calls == [FORMING - 100 * 24 * H]  # a single probe for the missing past
    assert min(FakeStore.rows["NEW/USDT"]) == listed


@pytest.mark.asyncio
async def test_load_returns_closed_bars_as_lists(store):
    fetch, _ = _exchange(listed_ms=0)
    await sync_symbol(store, fetch, "A/USDT", lookback_days=10, now=NOW)
    bars = await load_symbol(store, "A/USDT", lookback_days=10, now=NOW)
    assert len(bars) == 240
    assert bars[0][0] < bars[-1][0] < FORMING
    assert bars[-1][1:5] == [100.0, 101.0, 99.0, 100.0]


# ── config ────────────────────────────────────────────────────────────────


class _Repo:
    def __init__(self, session):
        pass

    async def put(self, *a):
        return None

    async def put_many(self, *a):
        return None


@pytest.fixture
def cfg(monkeypatch):
    monkeypatch.setattr("trdex.storage.runtime_config_repo.RuntimeConfigRepository", _Repo)

    @asynccontextmanager
    async def factory():
        yield object()

    svc = RuntimeConfigService(factory)
    svc._cache = {"symbols": {"agent_scheduler_symbols": "BTC/USDT, ETH/USDT"}, "thresholds": {}}
    return svc


SETTINGS = SimpleNamespace(
    agent_scheduler_symbols="",
    max_position_pct=0.05,
    sl_position_pct=0.02,
    sl_take_profit_pct=0.04,
    sl_trailing_stop_pct=0.015,
    risk_per_trade_pct=0.001,
    gate_min_win_rate=0.4,
    gate_max_drawdown=0.2,
    gate_min_sharpe=1.0,
    mode=SimpleNamespace(value="simulation"),
)


def test_refresh_config_follows_runtime_config_like_the_risk_node(cfg):
    cfg._cache["thresholds"] = {"sl_position_pct": "0.03", "risk_per_trade_pct": "0.002"}
    rc = build_refresh_config(cfg, SETTINGS)
    assert rc.symbols == ("BTC/USDT", "ETH/USDT")
    assert rc.engine.sl_pct == 0.03 and rc.engine.tp_pct == 0.04
    assert rc.risk_per_trade_pct == 0.002
    assert rc.criteria.min_trades == 20 and rc.criteria.max_drawdown == 0.2


def test_refresh_config_without_symbols_is_an_error(cfg):
    cfg._cache["symbols"] = {}
    with pytest.raises(ValueError, match="no agent symbols"):
        build_refresh_config(cfg, SETTINGS)


# ── watchdog ──────────────────────────────────────────────────────────────

GOOD = RefreshOutcome(
    "refreshed",
    data_end=date(2026, 10, 9),
    dev_cutoff=date(2025, 3, 1),
    cv_min=0.002,
    cv_max=0.045,
    metrics={
        "trades": 300,
        "return_pct": 12.0,
        "win_rate": 0.5,
        "max_drawdown_pct": 9.0,
        "sharpe": 1.4,
    },
)
BAD = replace(
    GOOD, status="validation_failed", cv_min=None, cv_max=None, failures=["Sharpe 0.20 < 1.00"]
)


class Harness:
    def __init__(self, cfg, monkeypatch, outcome=GOOD, ready=False):
        self.cfg = cfg
        self.sent: list[tuple[Event, str]] = []
        self.cpu_runs = 0
        self.outcome = outcome
        self.ready = ready
        self.now = NOW

        async def fake_sync(*a, **k):
            return 0

        async def fake_load(*a, **k):
            return [[0, 1, 1, 1, 1, 1]]

        async def fake_readiness(session, settings, config):
            return SimpleNamespace(
                ready=self.ready, failures=[] if self.ready else ["Sharpe: 0.5 < 1.0"], warnings=[]
            )

        monkeypatch.setattr(rr, "sync_symbol", fake_sync)
        monkeypatch.setattr(rr, "load_symbol", fake_load)
        monkeypatch.setattr("trdex.risk.readiness.evaluate_readiness", fake_readiness)

        @asynccontextmanager
        async def factory():
            yield object()

        async def run_cpu(fn, *args):
            self.cpu_runs += 1
            if isinstance(self.outcome, Exception):
                raise self.outcome
            return self.outcome

        async def notify(event, subject, body):
            self.sent.append((event, subject + " | " + body))

        self.wd = RegimeWatchdog(
            session_factory=factory,
            fetch_page=None,
            cfg_provider=lambda: cfg,
            settings_provider=lambda: SETTINGS,
            notify=notify,
            clock=lambda: self.now,
            run_cpu=run_cpu,
        )

    def events(self):
        return [e for e, _ in self.sent]


@pytest.mark.asyncio
async def test_first_tick_refreshes_writes_bounds_and_tells_the_operator(cfg, monkeypatch):
    h = Harness(cfg, monkeypatch)
    await h.wd.tick()
    th = cfg.get_category("thresholds")
    assert th["regime_cv_min"] == "0.002000" and th["regime_cv_max"] == "0.045000"
    assert th["regime_data_end"] == "2026-10-09"
    assert th["regime_set_at"]  # the gate just turned on
    assert th["regime_last_refresh_status"].startswith("refreshed")
    assert h.events() == [Event.REGIME_REFRESHED, Event.READINESS_CHANGED]


@pytest.mark.asyncio
async def test_no_rerun_before_the_interval(cfg, monkeypatch):
    h = Harness(cfg, monkeypatch)
    await h.wd.tick()
    h.now = NOW + timedelta(days=6)
    await h.wd.tick()
    assert h.cpu_runs == 1
    h.now = NOW + timedelta(days=7)
    await h.wd.tick()
    assert h.cpu_runs == 2


@pytest.mark.asyncio
async def test_failed_revalidation_keeps_old_bounds_and_waits_for_next_interval(cfg, monkeypatch):
    cfg._cache["thresholds"] = {"regime_cv_min": "0.001", "regime_cv_max": "0.03"}
    h = Harness(cfg, monkeypatch, outcome=BAD)
    await h.wd.tick()
    th = cfg.get_category("thresholds")
    assert (th["regime_cv_min"], th["regime_cv_max"]) == ("0.001", "0.03")
    assert th["regime_last_refresh_status"].startswith("validation failed (Sharpe 0.20 < 1.00)")
    assert Event.REGIME_VALIDATION_FAILED in h.events()
    h.now = NOW + timedelta(hours=8)
    await h.wd.tick()
    assert h.cpu_runs == 1


@pytest.mark.asyncio
async def test_errors_retry_after_6h_and_notify_at_most_daily(cfg, monkeypatch):
    h = Harness(cfg, monkeypatch, outcome=RuntimeError("binance down"))
    await h.wd.tick()
    assert h.events().count(Event.REGIME_REFRESH_ERROR) == 1
    assert "binance down" in h.sent[0][1]
    h.now = NOW + timedelta(hours=3)
    await h.wd.tick()
    assert h.cpu_runs == 1  # too early to retry
    h.now = NOW + timedelta(hours=7)
    await h.wd.tick()
    assert h.cpu_runs == 2
    assert h.events().count(Event.REGIME_REFRESH_ERROR) == 1  # second failure, same day
    h.outcome = GOOD
    h.now = NOW + timedelta(hours=14)
    await h.wd.tick()
    assert cfg.get("thresholds", "regime_cv_max") == "0.045000"
    assert cfg.get("watchdog", "last_error_at") == ""


@pytest.mark.asyncio
async def test_disabled_refresher_does_nothing_but_still_watches(cfg, monkeypatch):
    cfg._cache["scheduler"] = {"regime_refresh_enabled": "false"}
    h = Harness(cfg, monkeypatch)
    await h.wd.tick()
    assert h.cpu_runs == 0
    assert h.events() == [Event.READINESS_CHANGED]


@pytest.mark.asyncio
async def test_expiry_warns_in_the_last_two_weeks_once_a_day(cfg, monkeypatch):
    cfg._cache["scheduler"] = {"regime_refresh_enabled": "false"}
    cfg._cache["thresholds"] = {"regime_data_end": (NOW - timedelta(days=80)).date().isoformat()}
    h = Harness(cfg, monkeypatch)
    await h.wd.tick()
    assert next(s for e, s in h.sent if e == Event.REGIME_EXPIRING).startswith(
        "Regime bounds expire in 10 days"
    )
    h.now = NOW + timedelta(hours=5)
    await h.wd.tick()
    assert h.events().count(Event.REGIME_EXPIRING) == 1
    h.now = NOW + timedelta(days=12)
    await h.wd.tick()
    assert h.sent[-1][1].startswith("Regime bounds EXPIRED — live entries blocked")


@pytest.mark.asyncio
async def test_fresh_bounds_do_not_warn(cfg, monkeypatch):
    cfg._cache["scheduler"] = {"regime_refresh_enabled": "false"}
    cfg._cache["thresholds"] = {"regime_data_end": (NOW - timedelta(days=5)).date().isoformat()}
    h = Harness(cfg, monkeypatch)
    await h.wd.tick()
    assert Event.REGIME_EXPIRING not in h.events()


@pytest.mark.asyncio
async def test_readiness_is_reported_only_when_it_flips(cfg, monkeypatch):
    cfg._cache["scheduler"] = {"regime_refresh_enabled": "false"}
    h = Harness(cfg, monkeypatch, ready=False)
    await h.wd.tick()
    await h.wd.tick()
    assert h.events() == [Event.READINESS_CHANGED]
    assert "NOT READY" in h.sent[0][1] and "Sharpe: 0.5 < 1.0" in h.sent[0][1]
    h.ready = True
    await h.wd.tick()
    assert h.events() == [Event.READINESS_CHANGED, Event.READINESS_CHANGED]
    assert h.sent[-1][1].startswith("Live readiness: READY")


@pytest.mark.asyncio
async def test_a_failing_step_does_not_stop_the_others(cfg, monkeypatch):
    h = Harness(cfg, monkeypatch)

    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("trdex.risk.readiness.evaluate_readiness", boom)
    await h.wd.tick()  # must not raise
    assert Event.REGIME_REFRESHED in h.events()


@pytest.mark.asyncio
async def test_evaluation_runs_in_a_separate_process():
    """Real backtest, real subprocess: inputs and outcome must survive pickling."""
    data = {"A/USDT": _bars(3000, start_ms=NOW_MS - 200 * 24 * H)}
    out = await rr.run_in_subprocess(evaluate, data, CFG)
    assert isinstance(out, RefreshOutcome)
    assert out.status == "validation_failed"  # 140 days of dev data < 365
    assert any("history" in f for f in out.failures)
