"""Vectorised SMA crossover for the backtest engine.

NOT to be confused with ``src/trdex/strategy/examples/sma_cross.py``, which
is the async, single-signal version used by the live agent runner. The two
classes share a name and a concept but expose different interfaces and
cannot replace each other.

What it does
------------
Computes two simple moving averages on the close column of a polars
DataFrame and emits a signal **only on the bar where a crossing actually
happens**:

    BUY  (1)  → "golden cross": prev_short ≤ prev_long AND short > long
    SELL (-1) → "death cross":  prev_short ≥ prev_long AND short < long
    HOLD (0)  → otherwise

The crossing test uses ``shift(1)`` so the comparison runs between the
previous bar's SMA and the current bar's SMA — emitting a signal **once**,
not on every bar where ``short > long``. This matters because the backtest
engine ignores ``BUY`` while ``in_position=True``: a continuous signal would
hide a strategy that never actually exits.

Why SMA(9, 21)
--------------
These are the same periods the live Analyst agent uses
(see ``src/trdex/agents/analyst.py:127-128``). Using the same numbers in
the backtest gives a coherent baseline: the metrics produced here are a
reasonable proxy of "what the live agent would have done if it traded
purely on its SMA rule, without RSI/sentiment overlays".

Why a separate class from examples/sma_cross.py
-----------------------------------------------
The async version receives ``list[OHLCV]`` and returns a single ``Signal``
per call. Adapting it to the backtest engine would mean either:

  - looping bar-by-bar and converting each candle to OHLCV (≈10× slower
    than the polars vectorised path), or
  - rewriting it to also implement the polars Protocol (one class, two
    incompatible interfaces, two bugs).

A separate, focused class is simpler to read, test, and maintain. The
duplication is intentional and lives in different paths to make the choice
visible to anyone touching the code.

Limitations
-----------
- **No stop-loss / take-profit.** The backtest engine does not support
  intra-bar exits. Trades close only on the opposite cross signal.
- **Long-only, single position.** The engine tracks a single
  ``in_position`` boolean — no shorting, no pyramiding.
- **No look-ahead.** The signal at bar ``i`` uses only data up to and
  including bar ``i``; the engine then executes it at the close of bar
  ``i+1`` (``sigs[i-1]`` lookup), so even if a future change made the
  engine execute at bar ``i``, the strategy would still be safe because
  the cross detection compares ``i-1`` against ``i``.
- **Warm-up period.** The first ``long_period`` bars produce ``0``
  because ``rolling_mean`` returns ``null`` until the window is full and
  ``shift(1)`` adds one more null bar. The engine treats ``null`` and
  ``0`` identically (no trade).
"""

from __future__ import annotations

from dataclasses import dataclass

import polars as pl


@dataclass(frozen=True)
class BacktestSMACrossConfig:
    """Tunable parameters for ``BacktestSMACross``."""

    short_period: int = 9
    long_period: int = 21

    def __post_init__(self) -> None:
        if self.short_period <= 0 or self.long_period <= 0:
            raise ValueError("SMA periods must be positive")
        if self.short_period >= self.long_period:
            raise ValueError("short_period must be strictly less than long_period")


class BacktestSMACross:
    """Vectorised SMA crossover strategy for the backtest engine.

    Implements ``trdex.backtest.engine.Strategy`` Protocol.
    """

    def __init__(self, config: BacktestSMACrossConfig | None = None) -> None:
        self.config = config or BacktestSMACrossConfig()

    @property
    def name(self) -> str:
        return f"sma_cross({self.config.short_period},{self.config.long_period})"

    def generate_signals(self, df: pl.DataFrame) -> pl.Series:
        """Return a Series named 'signal' with one value per row in ``df``.

        Values are ``int8`` in ``{-1, 0, 1}``. The first ``long_period`` rows
        are ``0`` (warm-up).
        """
        if "close" not in df.columns:
            raise ValueError("DataFrame must have a 'close' column")

        cfg = self.config
        close = df["close"]
        sma_short = close.rolling_mean(window_size=cfg.short_period)
        sma_long = close.rolling_mean(window_size=cfg.long_period)

        prev_short = sma_short.shift(1)
        prev_long = sma_long.shift(1)

        # Detect the *bar of the cross* — emits 1 / -1 exactly once, not
        # while the relationship persists.
        golden_cross = (prev_short <= prev_long) & (sma_short > sma_long)
        death_cross = (prev_short >= prev_long) & (sma_short < sma_long)

        signal = (
            pl.when(golden_cross)
            .then(1)
            .when(death_cross)
            .then(-1)
            .otherwise(0)
            .cast(pl.Int8)
        )

        # ``pl.when(...).otherwise(0)`` against a Series with leading nulls
        # propagates nulls into the output: bars in the warm-up period
        # become null, which the engine reads as 0 (no trade). For
        # downstream simplicity we fill those nulls with 0 explicitly.
        result = pl.select(signal).to_series(0).fill_null(0)
        return result.alias("signal")
