"""Strategy implementations for the backtest suite.

Each strategy implements the `Strategy` Protocol from scripts.backtest.core:
it has `name` and `timeframe` attributes and a `generate_signal(...)` method.

Conventions:
  - indicators['rsi14'][i] may be None (warmup). Strategies must tolerate this.
  - position_state is "flat" | "long" | "short". Most strategies read it to
    decide whether to emit CLOSE_LONG / CLOSE_SHORT instead of SELL / BUY.
  - Long-only strategies never emit SELL (they emit CLOSE_LONG when exiting,
    or HOLD when flat during a bearish condition).
"""

from __future__ import annotations


class BaselineLive:
    name = "BaselineLive"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        rsi = indicators["rsi14"][bar_index - 1]
        if rsi is None:
            return "HOLD"
        want_long = rsi >= 50
        if want_long:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"  # engine flips
            return "HOLD"
        else:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"  # engine flips
            return "HOLD"


class BaselineInverse:
    name = "BaselineInverse"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        rsi = indicators["rsi14"][bar_index - 1]
        if rsi is None:
            return "HOLD"
        # Invert: RSI >= 50 → want short; RSI < 50 → want long
        want_long = rsi < 50
        if want_long:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"
            return "HOLD"
        else:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"
            return "HOLD"


class MeanReversionRSI:
    name = "MeanReversionRSI"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        rsi = indicators["rsi14"][bar_index - 1]
        if rsi is None:
            return "HOLD"
        if rsi < 30:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"
            return "HOLD"
        if rsi > 70:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"
            return "HOLD"
        return "HOLD"
