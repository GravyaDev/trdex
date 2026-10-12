"""Leverage is chosen so the stop always comes before liquidation."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trdex.risk.leverage import (
    SPOT,
    DerivativesConfig,
    choose_leverage,
    derivatives_config,
    funding_cash,
    funding_times,
    liquidation_distance,
    liquidation_price,
)

DC = DerivativesConfig()  # usdm, 3x, mmr 0.5%, buffer 50%


@pytest.mark.parametrize(
    ("stop", "lev"),
    [(0.02, 3), (0.164, 3), (0.17, 2), (0.2475, 2), (0.25, 1), (0.4975, 1)],
)
def test_largest_leverage_that_keeps_the_stop_inside_half_the_liquidation_distance(stop, lev):
    got, note = choose_leverage(stop, DC)
    assert got == lev and f"Leverage {lev}x" in note
    assert stop <= DC.buffer * liquidation_distance(got, DC.mmr) + 1e-12


def test_stop_too_wide_for_any_leverage_is_rejected():
    lev, reason = choose_leverage(0.5, DC)
    assert lev is None and "too wide for any leverage" in reason


def test_spot_is_always_1x_and_never_liquidated():
    assert choose_leverage(0.9, SPOT) == (1, "")


def test_max_leverage_caps_even_tight_stops():
    assert choose_leverage(0.005, DerivativesConfig(max_leverage=10))[0] == 10
    assert choose_leverage(0.005, DerivativesConfig(max_leverage=2.5))[0] == 2


def test_liquidation_price_by_side():
    assert liquidation_price(100.0, "BUY", 3, 0.005) == pytest.approx(100 * (1 - 0.32833333))
    assert liquidation_price(100.0, "SELL", 3, 0.005) == pytest.approx(100 * (1 + 0.32833333))


class Cfg:
    def __init__(self, **t):
        self.t = {k: str(v) for k, v in t.items()}

    def get(self, category, key, default=""):
        return self.t.get(key, default) if category == "thresholds" else default


def test_config_defaults_overrides_and_nonsense():
    assert derivatives_config(None) == DC and derivatives_config(Cfg()) == DC
    dc = derivatives_config(Cfg(execution_venue="SPOT", max_leverage=5))
    assert dc.venue == "spot" and not dc.perps and dc.max_leverage == 5
    for bad in (
        {"execution_venue": "margin"},
        {"max_leverage": "0.5"},
        {"max_leverage": "100"},
        {"maintenance_margin_rate": "nan"},
        {"liquidation_buffer": "2"},
    ):
        with pytest.raises(ValueError):
            derivatives_config(Cfg(**bad))


def test_funding_every_8h_and_who_pays():
    t0 = datetime(2026, 10, 11, 7, 30, tzinfo=UTC)
    t1 = datetime(2026, 10, 12, 0, 0, tzinfo=UTC)
    assert [t.hour for t in funding_times(t0, t1)] == [8, 16, 0]
    assert funding_times(t1, t1) == []
    assert funding_cash("BUY", 2.0, 100.0, 0.0001) == pytest.approx(-0.02)
    assert funding_cash("SELL", 2.0, 100.0, 0.0001) == pytest.approx(0.02)
