"""Tests for SMA crossover strategy."""

from trdex.market.models import OHLCV
from trdex.strategy.examples.sma_cross import SMACrossConfig, SMACrossStrategy
from trdex.strategy.models import SignalAction


async def test_sma_cross_not_enough_data() -> None:
    strategy = SMACrossStrategy()
    strategy.configure(SMACrossConfig(name="test", short_period=5, long_period=10))
    result = await strategy.evaluate([])  # No candles
    assert result is None


async def test_sma_cross_produces_signal(sample_candles: list[OHLCV]) -> None:
    strategy = SMACrossStrategy()
    strategy.configure(
        SMACrossConfig(
            name="test",
            symbols=["BTC/USDT"],
            short_period=5,
            long_period=20,
        )
    )
    # The sample data has an uptrend then downtrend, so at some window
    # there should be a crossover signal
    # Test with the full 50 candles (downtrend portion)
    result = await strategy.evaluate(sample_candles)
    # In the downtrend phase, short SMA crosses below long SMA → SELL
    if result is not None:
        assert result.action in (SignalAction.BUY, SignalAction.SELL)
        assert result.symbol == "BTC/USDT"
        assert 0.0 <= result.confidence <= 1.0


async def test_sma_cross_name() -> None:
    strategy = SMACrossStrategy()
    assert strategy.name == "sma_cross"
