"""Time-of-day / day-of-week seasonality on the development period only.

Tests whether entering long at a given UTC hour (or weekday, or hour of
the week) and exiting ``--horizon`` bars later beats zero AFTER fees, on
an equal-weight basket of the cached symbols, with Holm / BH correction
and a stability check across sub-periods. The most recent ``--holdout``
fraction of the data is never read into the statistics.

    python -m scripts.backtest.seasonality --by hour
    python -m scripts.backtest.seasonality --by hour_of_week --holdout 0.3

A bucket is reported as an edge only if its Holm-adjusted p < alpha AND
its mean is positive in every sub-period. Otherwise: NO EDGE FOUND.
Any window chosen from this output (for a strategy or for
agent_scheduler_active_hours) must still pass the sealed holdout once,
and counts as a tested variant from then on (``--prior-tests``).

Prereq: scripts/backtest/fetch_ohlcv.py (5y 1h cache).
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from trdex.research.stats import (
    PRIOR_TIME_WINDOW_TESTS,
    basket_returns,
    dev_period,
    seasonality,
)
from scripts.backtest.run_suite import DATA_DIR, SYMBOLS, _load_cache


def _load_available() -> dict[str, list[list]]:
    out = {}
    for sym in SYMBOLS:
        path = DATA_DIR / f"{sym.replace('/', '_')}_1h_5y.csv"
        if path.exists():
            out[sym] = _load_cache(sym)
        else:
            print(f"  skip {sym}: no cache at {path}")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--by", choices=["hour", "weekday", "hour_of_week"], default="hour")
    ap.add_argument("--horizon", type=int, default=1, help="holding period in 1h bars")
    ap.add_argument("--holdout", type=float, default=0.3, help="sealed most-recent fraction")
    ap.add_argument("--fee", type=float, default=0.001, help="taker fee per side")
    ap.add_argument("--splits", type=int, default=3, help="sub-periods for the stability check")
    ap.add_argument("--prior-tests", type=int, default=PRIOR_TIME_WINDOW_TESTS)
    ap.add_argument("--alpha", type=float, default=0.05)
    args = ap.parse_args()

    data = _load_available()
    if not data:
        raise SystemExit("no OHLCV cache found — run scripts/backtest/fetch_ohlcv.py first")
    dev, cutoff = dev_period(data, args.holdout)
    rets = basket_returns(dev, horizon=args.horizon, fee_pct=args.fee)
    stats, m_total = seasonality(
        rets, by=args.by, horizon=args.horizon, n_splits=args.splits, prior_tests=args.prior_tests
    )

    cut = datetime.fromtimestamp(cutoff / 1000, tz=UTC).date()
    print(
        f"\n{len(data)} symbols, equal-weight basket, {len(rets)} entries, dev period < {cut} "
        f"(last {args.holdout:.0%} sealed), fee {args.fee:.2%}/side, horizon {args.horizon}h, "
        f"hypotheses m = {len(stats)} buckets + {args.prior_tests} prior = {m_total}"
    )
    print(
        f"{args.by:>12} {'n':>6} {'mean net':>9} {'p':>8} {'p_holm':>8} {'p_bh':>8}  sub-period means"
    )
    for s in stats:
        splits = " ".join(f"{m:+.4%}" for m in s.split_means)
        flag = "  <- EDGE" if s.significant(args.alpha) else ""
        print(
            f"{s.bucket:>12} {s.n:>6} {s.mean:>+9.4%} {s.p:>8.4f} {s.p_holm:>8.4f} {s.p_bh:>8.4f}  {splits}{flag}"
        )

    edges = [s for s in stats if s.significant(args.alpha)]
    if not edges:
        print(
            "\nNO EDGE FOUND (no bucket with Holm p < alpha and positive mean in every sub-period)."
        )
    else:
        print(
            f"\n{len(edges)} candidate bucket(s). Next: one test on the sealed holdout, then count it as a variant."
        )


if __name__ == "__main__":
    main()
