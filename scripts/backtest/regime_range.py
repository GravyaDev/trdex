"""CV range of the development period -> bounds for the live regime gate.

The Risk node blocks entries whose CV (stdev/mean of the last 20 closes)
is outside thresholds.regime_cv_min / regime_cv_max (Risk Gate 4c). In
live mode the gate fails closed until both are set. This script measures
the CV distribution on the development period of the cached data (the
sealed holdout is excluded) and prints the values to enter in Runtime
Config (dashboard -> Risk Thresholds), including regime_data_end: the
readiness gate (sim -> live) fails until all three are set, and again
once regime_data_end is older than regime_max_age_days (default 90).

    python -m scripts.backtest.regime_range
    python -m scripts.backtest.regime_range --lo 1 --hi 99 --holdout 0.3

Re-run it whenever the strategy is re-validated on a new data window,
and at least every regime_max_age_days after refreshing the cache: the
bounds describe what the backtest covered, nothing more. Set them at the
start of the simulation that will be judged, not at the end (the
readiness report warns when they changed within gate_min_days).

Prereq: scripts/backtest/fetch_ohlcv.py (5y 1h cache, refresh it first).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from scripts.backtest.research import data_end, dev_period, regime_range
from scripts.backtest.seasonality import _load_available

from trdex.risk.readiness import REGIME_MAX_AGE_DAYS


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--holdout", type=float, default=0.3, help="sealed most-recent fraction")
    ap.add_argument("--lo", type=float, default=0.5, help="lower percentile")
    ap.add_argument("--hi", type=float, default=99.5, help="upper percentile")
    args = ap.parse_args()

    data = _load_available()
    if not data:
        raise SystemExit("no OHLCV cache found — run scripts/backtest/fetch_ohlcv.py first")
    dev, cutoff = dev_period(data, args.holdout)
    ranges = regime_range(dev, lo_pct=args.lo, hi_pct=args.hi)

    cut = datetime.fromtimestamp(cutoff / 1000, tz=UTC).date()
    print(f"\nCV of the last 20 closes, dev period < {cut} (last {args.holdout:.0%} sealed)")
    print(f"{'symbol':>10} {'n':>7} {f'p{args.lo:g}':>9} {'median':>9} {f'p{args.hi:g}':>9}")
    for sym, (lo, med, hi, n) in ranges.items():
        label = "ALL" if sym == "*" else sym
        print(f"{label:>10} {n:>7} {lo:>9.5f} {med:>9.5f} {hi:>9.5f}")
    if "*" in ranges:
        lo, _, hi, _ = ranges["*"]
        end = datetime.fromtimestamp(data_end(data) / 1000, tz=UTC).date()
        age = (datetime.now(tz=UTC).date() - end).days
        print("\nRuntime Config (dashboard -> Risk Thresholds):")
        print(f"  regime_cv_min   = {lo:.5f}")
        print(f"  regime_cv_max   = {hi:.5f}")
        print(f"  regime_data_end = {end.isoformat()}")
        print(
            f"\nData ends {age} days ago; readiness rejects bounds older than "
            f"regime_max_age_days (default {REGIME_MAX_AGE_DAYS})."
        )
        if age > REGIME_MAX_AGE_DAYS:
            print(
                "WARNING: older than the default limit, readiness will fail with these "
                "values. Refresh the cache (scripts/backtest/fetch_ohlcv.py) and re-run."
            )


if __name__ == "__main__":
    main()
