"""Research helpers: sealed holdout, seasonality with multiple-testing
correction, and the CV range that feeds the live regime gate."""

from __future__ import annotations

import random

import pytest

from trdex.research.stats import (
    basket_returns,
    benjamini_hochberg,
    bucket_of,
    cv_series,
    data_end,
    dev_period,
    holm,
    regime_range,
    seasonality,
)
from trdex.risk.sizing import recent_cv

H = 3_600_000
T0 = 1_704_067_200_000  # 2024-01-01 00:00 UTC, a Monday


def _walk(n, *, seed, sigma=0.005, drift_at_hour=None, drift=0.0, t0=T0):
    rnd = random.Random(seed)
    bars, p = [], 100.0
    for i in range(n):
        ts = t0 + i * H
        r = rnd.gauss(0.0, sigma)
        if drift_at_hour is not None and bucket_of(ts, "hour") == drift_at_hour:
            r += drift
        o, c = p, p * (1 + r)
        bars.append([ts, o, max(o, c), min(o, c), c, 1.0])
        p = c
    return bars


# ── sealed holdout ────────────────────────────────────────────────────────


def test_dev_period_never_returns_holdout_bars():
    data = {"A": _walk(1000, seed=1), "B": _walk(800, seed=2)}
    dev, cutoff = dev_period(data, 0.3)
    end = T0 + 999 * H
    assert cutoff == T0 + int((end - T0) * 0.7)
    assert all(b[0] < cutoff for bars in dev.values() for b in bars)
    assert max(b[0] for b in dev["A"]) < cutoff <= min(b[0] for b in data["A"] if b[0] >= cutoff)


def test_data_end_is_the_latest_bar_across_symbols_holdout_included():
    data = {"A": _walk(1000, seed=1), "B": _walk(800, seed=2), "C": []}
    assert data_end(data) == T0 + 999 * H
    with pytest.raises(ValueError):
        data_end({"A": []})


@pytest.mark.parametrize("h", [0.0, 1.0, -0.1])
def test_dev_period_rejects_invalid_holdout(h):
    with pytest.raises(ValueError):
        dev_period({"A": _walk(10, seed=1)}, h)


# ── multiple-testing correction ───────────────────────────────────────────


def test_holm_matches_textbook_values():
    assert holm([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.03, 0.06, 0.06, 0.02])


def test_bh_matches_textbook_values():
    assert benjamini_hochberg([0.01, 0.04, 0.03, 0.005]) == pytest.approx([0.02, 0.04, 0.04, 0.02])


def test_prior_tests_make_the_correction_stricter():
    p = [0.01, 0.04, 0.03, 0.005]
    assert all(a >= b for a, b in zip(holm(p, m=6), holm(p), strict=True))
    assert all(
        a >= b for a, b in zip(benjamini_hochberg(p, m=6), benjamini_hochberg(p), strict=True)
    )
    with pytest.raises(ValueError):
        holm(p, m=3)


# ── seasonality ───────────────────────────────────────────────────────────


def test_net_returns_use_the_engine_cost_model():
    bars = [[T0, 100.0, 101.0, 99.0, 101.0, 1.0]]
    [(_, r)] = basket_returns({"A": bars}, fee_pct=0.001)
    assert r == pytest.approx(101.0 / 100.0 * 0.999**2 - 1)


def test_basket_averages_symbols_per_timestamp():
    a = [[T0, 100.0, 0, 0, 110.0, 1.0]]
    b = [[T0, 100.0, 0, 0, 90.0, 1.0]]
    [(_, r)] = basket_returns({"A": a, "B": b}, fee_pct=0.0)
    assert r == pytest.approx(0.0)


def test_planted_hourly_edge_is_found_and_only_there():
    n = 24 * 365 * 2
    data = {s: _walk(n, seed=s, drift_at_hour=14, drift=0.006) for s in range(3)}
    stats, m_total = seasonality(basket_returns(data), by="hour", prior_tests=1)
    assert m_total == 25
    edges = [s.bucket for s in stats if s.significant()]
    assert edges == [14]


def test_pure_noise_reports_no_edge():
    n = 24 * 365 * 2
    data = {s: _walk(n, seed=100 + s) for s in range(3)}
    stats, _ = seasonality(basket_returns(data), by="hour_of_week")
    assert not [s for s in stats if s.significant()]


def test_an_edge_smaller_than_the_fees_is_not_an_edge():
    n = 24 * 365 * 2
    data = {s: _walk(n, seed=200 + s, drift_at_hour=14, drift=0.0008) for s in range(3)}
    stats, _ = seasonality(basket_returns(data, fee_pct=0.001), by="hour")
    hour14 = next(s for s in stats if s.bucket == 14)
    assert hour14.mean < 0  # +8 bps gross, -20 bps round trip
    assert not hour14.significant()


def test_edge_must_hold_in_every_sub_period():
    n = 24 * 365 * 3
    first = {s: _walk(n // 3, seed=300 + s, drift_at_hour=14, drift=0.01) for s in range(3)}
    rest = {s: _walk(2 * n // 3, seed=400 + s, t0=first[s][-1][0] + H) for s in range(3)}
    data = {s: first[s] + rest[s] for s in range(3)}
    stats, _ = seasonality(basket_returns(data), by="hour", n_splits=3)
    hour14 = next(s for s in stats if s.bucket == 14)
    assert hour14.p_holm < 0.05  # strong in the pooled sample...
    assert not hour14.stable  # ...but only in the first third
    assert not hour14.significant()


def test_overlapping_weekday_buckets_are_refused():
    with pytest.raises(ValueError):
        seasonality([(T0, 0.0)], by="weekday", horizon=4)


# ── volatility regime range ───────────────────────────────────────────────


def test_cv_series_matches_the_live_recent_cv():
    closes = [b[4] for b in _walk(200, seed=7, sigma=0.02)]
    series = cv_series(closes)
    assert len(series) == len(closes) - 19
    for k in (0, 50, 180):
        assert series[k] == pytest.approx(recent_cv(closes[k : k + 20]), rel=1e-12)


def test_regime_range_reports_pooled_percentiles():
    calm = _walk(2000, seed=8, sigma=0.002)
    wild = _walk(2000, seed=9, sigma=0.03)
    out = regime_range({"CALM": calm, "WILD": wild}, lo_pct=1, hi_pct=99)
    assert set(out) == {"CALM", "WILD", "*"}
    assert out["CALM"][2] < out["WILD"][0]  # calm p99 below wild p1
    lo, _, hi, n = out["*"]
    assert lo == pytest.approx(out["CALM"][0], rel=0.5)
    assert hi == pytest.approx(out["WILD"][2], rel=0.5)
    assert n == 2 * (2000 - 19)
