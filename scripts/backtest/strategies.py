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


class LiveRuleEngine:
    """The strategy that actually runs in the agent pipeline, replayed bar by bar.

    - Signal: ``trdex.agents.analyst._rule_based_signal`` (RSI14 + SMA9/21),
      imported from production code so the two cannot drift apart.
    - Risk gate 2: confidence below ``trdex.agents.risk.MIN_CONFIDENCE`` → HOLD.
    - Intent translation as in ``signal_to_intent``: long-only, BUY opens
      when flat, SELL closes an open long, never opens a short.
    - Exits as in ``StopLossMonitor``: ``effective_thresholds`` from
      production code, i.e. config base (EngineParams) widened by the
      volatility floor max(base, k x CV of the last 20 closes).
    - Sizing as in the Risk node: risk_per_trade_pct / stop, capped at
      EngineParams.position_size_pct (``risk_position_fraction``).
    - Regime gate as in Risk Gate 4c: entries outside ``regime`` bounds
      are skipped (closes are never blocked). Off by default, like an
      unset Runtime Config in simulation.

    Approximations vs live (state them when reading results):
    - no sentiment input (no point-in-time news history), so the ±0.2
      sentiment nudge is off;
    - one decision per closed 1h bar (live re-evaluates every scheduler
      tick on the forming candle) and exits checked on bar high/low
      (live checks the ticker every 30s);
    - the adaptive floor is frozen at entry (live recomputes CV each check);
    - the portfolio drawdown gate and per-symbol overrides are not modelled.
    """
    name = "LiveRuleEngine"
    timeframe = "1h"

    def __init__(self, regime=None, risk_per_trade_pct: float | None = 0.001):
        """``regime``: ``trdex.risk.sizing.RegimeBounds`` (default: no bounds).
        ``risk_per_trade_pct``: live default of thresholds.risk_per_trade_pct
        (src/trdex/config.py); ``None`` = fixed notional sizing.
        """
        from trdex.risk.sizing import RegimeBounds

        self.regime = regime if regime is not None else RegimeBounds()
        self.risk_per_trade_pct_override = risk_per_trade_pct

    def generate_signal(self, bar_index, candles, indicators, position_state):
        from trdex.agents.analyst import _rule_based_signal
        from trdex.agents.risk import MIN_CONFIDENCE

        j = bar_index - 1
        signal, confidence, _ = _rule_based_signal(
            indicators["rsi14"][j],
            indicators["sma9"][j],
            indicators["sma21"][j],
            indicators["closes"][j],
            None,  # sentiment: not available historically
        )
        if signal == "HOLD" or confidence < MIN_CONFIDENCE:
            return "HOLD"
        if signal == "BUY":
            if position_state != "flat":
                return "HOLD"
            from trdex.risk.sizing import check_regime

            if check_regime(self._cv(bar_index, indicators), self.regime) is not None:
                return "HOLD"
            return "BUY"
        # SELL: close an open long; long-only, so never open a short.
        return "CLOSE_LONG" if position_state == "long" else "HOLD"

    @staticmethod
    def _cv(bar_index, indicators):
        """CV of the closes the live Analyst would see at this decision."""
        from trdex.risk.sizing import VOL_WINDOW, recent_cv

        return recent_cv(indicators["closes"][max(0, bar_index - VOL_WINDOW):bar_index])

    def exit_pcts(self, bar_index, indicators, params):
        from trdex.risk.stop_loss import effective_thresholds

        cv = self._cv(bar_index, indicators)
        return effective_thresholds(
            None,
            None,
            cv if cv is not None else 0.0,
            base_sl=params.sl_pct,
            base_tp=params.tp_pct,
            base_trail=params.trail_pct,
        )


class BaselineLive:
    """RSI(14) >= 50 long / < 50 short, always in the market.

    NOT the live strategy despite the name (kept for CSV continuity): the
    live pipeline also uses SMA9/21, is long-only and uses adaptive exits.
    See ``LiveRuleEngine`` for the faithful replay.
    """
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


from datetime import datetime, timezone


def _utc_hour(ts_ms: int) -> int:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).hour


class TimeFilterLive:
    name = "TimeFilterLive"
    timeframe = "1h"

    def generate_signal(self, bar_index, candles, indicators, position_state):
        rsi = indicators["rsi14"][bar_index - 1]
        if rsi is None:
            return "HOLD"
        hour = _utc_hour(candles[bar_index - 1][0])
        in_window = 13 <= hour < 22
        if not in_window:
            return "HOLD"
        want_long = rsi >= 50
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


class PullbackInUptrend:
    """Long-only: BUY when SMA50 rising over 24 bars AND RSI < 40."""
    name = "PullbackInUptrend"
    timeframe = "1h"
    trail_pct_override = 0.03

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if bar_index < 25:
            return "HOLD"
        sma50 = indicators["sma50"]
        rsi = indicators["rsi14"][bar_index - 1]
        s_now = sma50[bar_index - 1]
        s_then = sma50[bar_index - 25]
        if rsi is None or s_now is None or s_then is None:
            return "HOLD"
        rising = s_now > s_then
        if rising and rsi < 40 and position_state == "flat":
            return "BUY"
        return "HOLD"


class ZanniLikeScalp:
    """Long-only scalp: 13–22 UTC AND 3 rising closes AND 45 <= RSI <= 65."""
    name = "ZanniLikeScalp"
    timeframe = "1h"
    tp_pct_override = 0.008
    trail_pct_override = 0.0  # no trail

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if bar_index < 4:
            return "HOLD"
        rsi = indicators["rsi14"][bar_index - 1]
        if rsi is None:
            return "HOLD"
        hour = _utc_hour(candles[bar_index - 1][0])
        in_window = 13 <= hour < 22
        if not in_window:
            return "HOLD"
        # 3 rising closes: c[i-1] > c[i-2] > c[i-3] > c[i-4]
        c = [candles[bar_index - k][4] for k in (1, 2, 3, 4)]
        rising = c[0] > c[1] > c[2] > c[3]
        if rising and 45.0 <= rsi <= 65.0 and position_state == "flat":
            return "BUY"
        return "HOLD"


class SwingDailyTrend:
    """Daily timeframe: SMA20/SMA50 cross + RSI confirm.

    Exit params expressed via class attributes so the runner applies them
    via EngineParams override. Bounds: SL 5%, TP 15%, trail 7%.
    """
    name = "SwingDailyTrend"
    timeframe = "1d"
    sl_pct_override = 0.05
    tp_pct_override = 0.15
    trail_pct_override = 0.07

    def generate_signal(self, bar_index, candles, indicators, position_state):
        if bar_index < 2:
            return "HOLD"
        rsi = indicators["rsi14"][bar_index - 1]
        # Use sma9 as SMA20-equivalent? No — engine precomputes sma9/sma21 on the
        # aggregated 1d closes, so 'sma9' and 'sma21' are actually SMA on daily.
        # For this strategy the runner/engine passes indicators computed over
        # the daily bars since timeframe="1d".
        # But we need SMA20 and SMA50 on daily — add them to precompute.
        sma20 = indicators.get("sma20_1d") or indicators.get("sma21")
        sma50 = indicators["sma50"]
        if rsi is None or sma20 is None or sma50 is None:
            return "HOLD"
        s20_prev = sma20[bar_index - 2]
        s20_now = sma20[bar_index - 1]
        s50_prev = sma50[bar_index - 2]
        s50_now = sma50[bar_index - 1]
        if None in (s20_prev, s20_now, s50_prev, s50_now):
            return "HOLD"
        cross_up = s20_prev <= s50_prev and s20_now > s50_now
        cross_down = s20_prev >= s50_prev and s20_now < s50_now
        if cross_up and rsi > 55:
            if position_state == "flat":
                return "BUY"
            if position_state == "short":
                return "BUY"
            return "HOLD"
        if cross_down and rsi < 45:
            if position_state == "flat":
                return "SELL"
            if position_state == "long":
                return "SELL"
            return "HOLD"
        return "HOLD"
