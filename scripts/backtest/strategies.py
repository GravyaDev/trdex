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


class MultiTimeframeConfirm:
    name = "MultiTimeframeConfirm"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        rsi = indicators["rsi14"][bar_index - 1]
        sma_4h = indicators["sma20_4h"]
        if rsi is None:
            return "HOLD"

        # 4h trend: is sma20_4h rising over last 24 1h bars?
        if bar_index - 24 < 0:
            return "HOLD"
        s_now = sma_4h[bar_index - 1]
        s_then = sma_4h[bar_index - 24]
        if s_now is None or s_then is None:
            return "HOLD"
        rising = s_now > s_then
        falling = s_now < s_then

        live_bullish = rsi >= 50
        if live_bullish and rising:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"
            return "HOLD"
        if (not live_bullish) and falling:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"
            return "HOLD"
        return "HOLD"


class BreakoutVolume:
    name = "BreakoutVolume"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if bar_index < 25:
            return "HOLD"
        closes = indicators["closes"]
        volumes = indicators["volumes"]
        vol_ma = indicators["vol_ma24"][bar_index - 1]
        if vol_ma is None:
            return "HOLD"

        # Last 24 bars before current bar (indexes bar_index-25 .. bar_index-2)
        prev_window = closes[bar_index - 25:bar_index - 1]
        if not prev_window:
            return "HOLD"
        prev_max = max(prev_window)
        prev_min = min(prev_window)
        cur_close = closes[bar_index - 1]
        cur_vol = volumes[bar_index - 1]

        volume_ok = cur_vol > 1.5 * vol_ma
        if not volume_ok:
            return "HOLD"

        if cur_close > prev_max:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"
            return "HOLD"
        if cur_close < prev_min:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"
            return "HOLD"
        return "HOLD"


class BollingerSqueezeBreakout:
    name = "BollingerSqueezeBreakout"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        squeeze = indicators["squeeze"]
        closes = indicators["closes"]
        bb_upper = indicators["bb_upper"]
        bb_lower = indicators["bb_lower"]
        if bar_index < 2:
            return "HOLD"

        prev_squeeze = squeeze[bar_index - 2]
        cur_squeeze = squeeze[bar_index - 1]
        released = prev_squeeze and not cur_squeeze
        if not released:
            return "HOLD"

        cur_close = closes[bar_index - 1]
        bu = bb_upper[bar_index - 1]
        bl = bb_lower[bar_index - 1]
        if bu is None or bl is None:
            return "HOLD"

        if cur_close > bu:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"
            return "HOLD"
        if cur_close < bl:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"
            return "HOLD"
        return "HOLD"
