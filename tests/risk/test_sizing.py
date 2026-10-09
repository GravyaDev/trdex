"""Pure sizing / regime functions shared by the Risk node and the backtest."""

from __future__ import annotations

import statistics

import pytest

from trdex.risk.sizing import (
    VOL_WINDOW,
    RegimeBounds,
    check_regime,
    recent_cv,
    risk_position_fraction,
)


def test_recent_cv_uses_the_last_window_closes_with_sample_stdev():
    closes = [float(x) for x in range(1, 41)]
    tail = closes[-VOL_WINDOW:]
    assert recent_cv(closes) == pytest.approx(statistics.stdev(tail) / statistics.mean(tail))


def test_recent_cv_is_none_with_too_few_closes_or_zero_mean():
    assert recent_cv([100.0, 101.0]) is None
    assert recent_cv([0.0, 0.0, 0.0]) is None


def test_recent_cv_zero_for_flat_prices():
    assert recent_cv([100.0] * 30) == 0.0


def test_fraction_is_risk_over_stop():
    assert risk_position_fraction(
        risk_per_trade=0.001, stop_pct=0.325, max_fraction=0.05
    ) == pytest.approx(0.001 / 0.325)


def test_fraction_is_capped_for_tight_stops():
    assert risk_position_fraction(risk_per_trade=0.01, stop_pct=0.02, max_fraction=0.05) == 0.05


def test_equal_risk_across_stops_below_the_cap():
    for stop in (0.02, 0.05, 0.10, 0.325):
        f = risk_position_fraction(risk_per_trade=0.001, stop_pct=stop, max_fraction=0.05)
        assert f * stop == pytest.approx(0.001)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"risk_per_trade": 0.001, "stop_pct": 0.0, "max_fraction": 0.05},
        {"risk_per_trade": 0.0, "stop_pct": 0.02, "max_fraction": 0.05},
        {"risk_per_trade": 0.001, "stop_pct": 0.02, "max_fraction": 0.0},
        {"risk_per_trade": 0.001, "stop_pct": -0.02, "max_fraction": 0.05},
    ],
)
def test_fraction_rejects_non_positive_inputs(kwargs):
    with pytest.raises(ValueError):
        risk_position_fraction(**kwargs)


def test_bounds_from_config_treat_non_positive_as_unset():
    # Runtime Config coerces "" to 0.0: that must not mean "max CV 0".
    b = RegimeBounds.from_config(0.0, 0.0)
    assert not b.configured
    assert check_regime(0.5, b) is None


def test_bounds_reject_min_above_max():
    with pytest.raises(ValueError):
        RegimeBounds.from_config(0.05, 0.01)


def test_regime_inside_range_passes():
    assert check_regime(0.02, RegimeBounds(cv_min=0.001, cv_max=0.04)) is None


def test_regime_outside_range_is_blocked_with_reason():
    b = RegimeBounds(cv_min=0.001, cv_max=0.04)
    assert "above tested range" in (check_regime(0.13, b) or "")
    assert "below tested range" in (check_regime(0.0005, b) or "")


def test_regime_unknown_volatility_is_blocked_when_bounds_are_set():
    assert "unknown" in (check_regime(None, RegimeBounds(cv_max=0.04)) or "")
