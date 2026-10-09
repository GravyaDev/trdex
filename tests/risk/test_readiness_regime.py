"""Readiness gate: volatility-regime bounds are a live prerequisite.

The Risk node blocks live entries without regime bounds (Gate 4c); the
readiness gate must say so before the operator switches to live, reject
bounds derived from stale data, and warn when the simulation it judges
did not run with the current bounds.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from trdex.risk.readiness import REGIME_MAX_AGE_DAYS, evaluate_readiness, regime_criteria

NOW = datetime(2026, 10, 9, 12, 0, 0)
FRESH = {
    "cv_min": "0.002",
    "cv_max": "0.045",
    "data_end": "2026-10-01",
    "set_at": "2026-08-01T09:00:00+00:00",
    "max_age_days": 90,
}


def _check(**over):
    return regime_criteria(**{**FRESH, **over}, min_days=30, now=NOW)


# ── pure rules ────────────────────────────────────────────────────────────


def test_fresh_coherent_bounds_set_before_the_gate_window_pass_cleanly():
    assert _check() == ([], [])


@pytest.mark.parametrize("cv_min,cv_max", [("", ""), ("0.002", ""), ("", "0.04"), ("0", "0")])
def test_unset_bounds_fail_and_say_how_to_fix(cv_min, cv_max):
    failures, _ = _check(cv_min=cv_min, cv_max=cv_max)
    assert len(failures) == 1
    assert "not set" in failures[0]
    assert "scripts.backtest.regime_range" in failures[0]


def test_non_numeric_bound_fails():
    failures, _ = _check(cv_min="abc")
    assert failures == ["Regime bounds: regime_cv_min 'abc' is not a number"]


def test_inverted_bounds_fail():
    failures, _ = _check(cv_min="0.05", cv_max="0.01")
    assert any("regime_cv_min 0.05 >= regime_cv_max 0.01" in f for f in failures)


def test_missing_data_end_fails():
    failures, _ = _check(data_end="")
    assert any("regime_data_end not set" in f for f in failures)


def test_malformed_data_end_fails():
    failures, _ = _check(data_end="01/10/2026")
    assert any("not a YYYY-MM-DD date" in f for f in failures)


def test_future_data_end_fails_but_one_day_of_slack_is_allowed():
    assert any("in the future" in f for f in _check(data_end="2026-10-12")[0])
    assert _check(data_end="2026-10-10")[0] == []


def test_stale_data_end_fails_past_max_age():
    on_limit = (NOW - timedelta(days=90)).date().isoformat()
    past = (NOW - timedelta(days=91)).date().isoformat()
    assert _check(data_end=on_limit)[0] == []
    failures, _ = _check(data_end=past)
    assert len(failures) == 1
    assert "91 days ago > 90" in failures[0]
    assert "re-run" in failures[0]


def test_max_age_is_configurable_and_non_positive_falls_back_to_default():
    end = (NOW - timedelta(days=40)).date().isoformat()
    assert _check(data_end=end, max_age_days=30)[0] != []
    assert _check(data_end=end, max_age_days=0)[0] == []  # 0 -> default 90
    assert REGIME_MAX_AGE_DAYS == 90


def test_bounds_changed_inside_the_gate_window_warn_without_failing():
    failures, warnings = _check(set_at=(NOW - timedelta(days=5)).isoformat())
    assert failures == []
    assert len(warnings) == 1
    assert "changed 5 days ago (< 30 gate days)" in warnings[0]


def test_unknown_change_date_warns():
    failures, warnings = _check(set_at="")
    assert failures == []
    assert any("change date unknown" in w for w in warnings)


# ── evaluate_readiness integration ────────────────────────────────────────


class _Cfg:
    def __init__(self, **thresholds):
        self._t = {k: str(v) for k, v in thresholds.items()}

    def get(self, category, key, default=""):
        return self._t.get(key, default) if category == "thresholds" else default

    def get_typed(self, category, key, default=None):
        if category != "thresholds" or key not in self._t:
            return default
        raw = self._t[key]
        return int(raw) if key in ("gate_min_days", "regime_max_age_days") else raw


def _settings():
    return SimpleNamespace(
        gate_min_days=30, gate_min_sharpe=1.0, gate_max_drawdown=0.2, gate_min_win_rate=0.4
    )


def _no_runs_session():
    result = MagicMock()
    result.scalar.return_value = None
    session = AsyncMock()
    session.execute.return_value = result
    return session


@pytest.mark.asyncio
async def test_regime_failure_is_reported_even_before_any_simulation(monkeypatch):
    monkeypatch.setattr(
        "trdex.services.runtime_config.get_config_service", lambda: _Cfg(gate_min_days=30)
    )
    report = await evaluate_readiness(_no_runs_session(), _settings())
    assert report.ready is False
    assert report.failures[0] == "No simulation data."
    assert any("Regime bounds: not set" in f for f in report.failures)


@pytest.mark.asyncio
async def test_missing_config_service_fails_closed(monkeypatch):
    monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda: None)
    report = await evaluate_readiness(_no_runs_session(), _settings())
    assert any("Runtime Config unavailable" in f for f in report.failures)


@pytest.mark.asyncio
async def test_report_exposes_regime_criteria_and_warnings(monkeypatch):
    today = datetime.now(tz=UTC)
    cfg = _Cfg(
        regime_cv_min=0.002,
        regime_cv_max=0.045,
        regime_data_end=today.date().isoformat(),
        regime_set_at=(today - timedelta(days=2)).isoformat(),
        regime_max_age_days=60,
    )
    monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda: cfg)
    report = await evaluate_readiness(_no_runs_session(), _settings())
    assert report.failures == ["No simulation data."]
    assert len(report.warnings) == 1 and "changed 2 days ago" in report.warnings[0]
    assert report.criteria["regime_cv_min"] == "0.002"
    assert report.criteria["regime_max_age_days"] == 60


@pytest.mark.asyncio
async def test_explicit_config_wins_over_the_process_service(monkeypatch):
    monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda: None)
    report = await evaluate_readiness(_no_runs_session(), _settings(), _Cfg(gate_min_days=30))
    assert not any("Runtime Config unavailable" in f for f in report.failures)
    assert any("Regime bounds: not set" in f for f in report.failures)
