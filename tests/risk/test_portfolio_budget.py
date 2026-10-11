"""Portfolio rules: risk budget with REDUCE, correlated clusters, reward/risk."""

from __future__ import annotations

import json
import random

import pytest

from trdex.risk.portfolio_budget import (
    MIN_KEEP,
    PortfolioRules,
    cluster_block,
    correlation_clusters,
    fit_to_budget,
    parse_clusters,
    portfolio_rules,
    reward_risk_block,
)

# ── budget ────────────────────────────────────────────────────────────────


def test_entry_that_fits_goes_ahead_unchanged():
    fit = fit_to_budget(planned_size=0.05, stop_pct=0.02, open_risk=0.002, cap=0.005)
    assert (fit.size, fit.reduced, fit.rejected) == (0.05, False, None)
    assert "open risk 0.200% of 0.500% budget" in fit.note


def test_entry_that_does_not_fit_is_reduced_to_the_room_left():
    fit = fit_to_budget(planned_size=0.05, stop_pct=0.02, open_risk=0.0045, cap=0.005)
    assert fit.reduced and fit.rejected is None
    assert fit.size == pytest.approx(0.025)  # 0.05% room / 2% stop
    assert "REDUCED to 2.50% of equity (50% of planned)" in fit.note


def test_crumbs_and_a_full_budget_are_rejected():
    tiny = fit_to_budget(planned_size=0.05, stop_pct=0.02, open_risk=0.0049, cap=0.005)
    assert tiny.size == 0 and "only 10% of the planned size fits" in tiny.rejected
    assert MIN_KEEP == 0.25
    full = fit_to_budget(planned_size=0.05, stop_pct=0.02, open_risk=0.006, cap=0.005)
    assert "portfolio risk budget exhausted" in full.rejected


def test_budget_off_and_bad_inputs():
    assert fit_to_budget(planned_size=0.05, stop_pct=0.02, open_risk=1.0, cap=None).size == 0.05
    with pytest.raises(ValueError):
        fit_to_budget(planned_size=0.05, stop_pct=0.0, open_risk=0.0, cap=0.005)


# ── clusters ──────────────────────────────────────────────────────────────

MAJORS = frozenset({"BTC/USDT", "ETH/USDT", "SOL/USDT", "AVAX/USDT"})


def test_cluster_cap_counts_open_positions_in_the_same_cluster():
    open_syms = ["BTC/USDT", "ETH/USDT", "XAU/USD"]
    assert cluster_block("SOL/USDT", open_syms, [MAJORS], 3) is None
    reason = cluster_block("SOL/USDT", [*open_syms, "AVAX/USDT"], [MAJORS], 3)
    assert reason.startswith("correlation limit: 3 longs already open")
    assert cluster_block("DOGE/USDT", [*open_syms, "AVAX/USDT"], [MAJORS], 3) is None
    assert cluster_block("SOL/USDT", MAJORS, [MAJORS], 0) is None  # off


def test_cluster_cap_counts_only_the_same_direction():
    longs = [("BTC/USDT", "BUY"), ("ETH/USDT", "BUY"), ("AVAX/USDT", "BUY")]
    assert cluster_block("SOL/USDT", longs, [MAJORS], 3, side="BUY") is not None
    assert cluster_block("SOL/USDT", longs, [MAJORS], 3, side="SELL") is None  # a hedge
    shorts = [("BTC/USDT", "SELL"), ("ETH/USDT", "SELL")]
    reason = cluster_block("SOL/USDT", shorts, [MAJORS], 2, side="SELL")
    assert reason.startswith("correlation limit: 2 shorts already open")


def test_clusters_parse_from_json_and_garbage_raises_so_callers_fail_closed():
    assert parse_clusters(json.dumps([["A", "B"], ["C"]])) == [frozenset({"A", "B"})]
    assert parse_clusters("") == [] and parse_clusters(None) == []
    for bad in ("not json", '{"a": 1}', "[1, 2]", '[["A", 3]]'):
        with pytest.raises(ValueError):
            parse_clusters(bad)


def _daily_bars(returns, start=1_700_000_000_000):
    p, out = 100.0, []
    for i, r in enumerate(returns):
        p *= 1 + r
        out.append([start + i * 86_400_000, p, p, p, p, 1.0])
    return out


def test_correlated_symbols_cluster_and_independent_ones_do_not():
    rnd = random.Random(7)
    base = [rnd.gauss(0, 0.03) for _ in range(120)]
    bars = {
        "BTC/USDT": _daily_bars(base),
        "ETH/USDT": _daily_bars([b + rnd.gauss(0, 0.005) for b in base]),
        "XAU/USD": _daily_bars([rnd.gauss(0, 0.01) for _ in range(120)]),
    }
    assert correlation_clusters(bars) == [["BTC/USDT", "ETH/USDT"]]
    assert correlation_clusters(bars, threshold=0.999) == []
    short = {k: v[:20] for k, v in bars.items()}
    assert correlation_clusters(short) is None  # unknown, not "uncorrelated"


def test_a_new_or_stale_symbol_is_left_out_instead_of_wiping_the_clusters():
    rnd = random.Random(7)
    base = [rnd.gauss(0, 0.03) for _ in range(200)]
    bars = {
        "BTC/USDT": _daily_bars(base),
        "ETH/USDT": _daily_bars([b + rnd.gauss(0, 0.005) for b in base]),
        "SOL/USDT": _daily_bars([b + rnd.gauss(0, 0.005) for b in base]),
        # listed 20 days ago
        "NEW/USDT": _daily_bars([rnd.gauss(0, 0.03) for _ in range(20)], start=_day(180)),
        # data stopped 150 days ago, uncorrelated anyway
        "OLD/USDT": _daily_bars([rnd.gauss(0, 0.03) for _ in range(50)]),
    }
    assert correlation_clusters(bars) == [["BTC/USDT", "ETH/USDT", "SOL/USDT"]]


def _day(n, start=1_700_000_000_000):
    return start + n * 86_400_000


# ── reward / risk ─────────────────────────────────────────────────────────


def test_reward_risk():
    assert reward_risk_block(0.02, 0.04, 1.5) is None
    assert reward_risk_block(0.08, 0.04, 1.5) == (
        "reward/risk 0.50 < 1.50 (take-profit 4.00% vs stop 8.00%)"
    )
    assert reward_risk_block(0.08, 0.04, 0.0) is None


# ── config ────────────────────────────────────────────────────────────────


class Cfg:
    def __init__(self, **t):
        self.t = {k: str(v) for k, v in t.items()}

    def get(self, category, key, default=""):
        return self.t.get(key, default) if category == "thresholds" else default


def test_rules_from_config():
    assert portfolio_rules(None) == PortfolioRules()
    r = portfolio_rules(
        Cfg(
            portfolio_risk_max_pct=0,
            max_positions_per_cluster=2,
            min_reward_risk=2,
            correlation_clusters=json.dumps([["BTC/USDT", "ETH/USDT"]]),
        )
    )
    assert r.risk_cap is None and r.max_per_cluster == 2 and r.min_reward_risk == 2
    assert r.clusters == (frozenset({"BTC/USDT", "ETH/USDT"}),)
    with pytest.raises(ValueError):
        portfolio_rules(Cfg(portfolio_risk_max_pct="lots"))
    with pytest.raises(ValueError):
        portfolio_rules(Cfg(min_reward_risk=-1))
    with pytest.raises(ValueError, match="whole number"):
        portfolio_rules(Cfg(max_positions_per_cluster="0.5"))  # would truncate to "off"
    with pytest.raises(ValueError):
        portfolio_rules(Cfg(correlation_clusters="{corrupt"))  # would mean "no clusters"
