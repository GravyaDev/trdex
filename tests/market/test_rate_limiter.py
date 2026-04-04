"""Tests for rate limiter and feed manager."""

import pytest

from trdex.market.manager import ConfigurationError, PriceFeedManager
from trdex.market.rate_limiter import CircuitState, RateLimiter


@pytest.fixture
def limiter() -> RateLimiter:
    return RateLimiter(name="test", default_rpm=60)


async def test_acquire_no_delay(limiter: RateLimiter) -> None:
    """First acquire should not block."""
    await limiter.acquire()
    assert limiter.circuit_state == CircuitState.CLOSED


async def test_report_success_resets_429_count(limiter: RateLimiter) -> None:
    limiter.report_rate_limit()
    limiter.report_rate_limit()
    limiter.report_success()
    # Should not trip after success reset
    limiter.report_rate_limit()
    assert limiter.circuit_state == CircuitState.CLOSED


async def test_circuit_trips_after_3_rate_limits(limiter: RateLimiter) -> None:
    limiter.report_rate_limit()
    limiter.report_rate_limit()
    limiter.report_rate_limit()
    assert limiter.circuit_state == CircuitState.OPEN


async def test_utilization_update(limiter: RateLimiter) -> None:
    limiter.update_utilization(used=600, limit=1200)
    assert limiter.utilization == pytest.approx(0.5)


async def test_high_utilization_increases_delay(limiter: RateLimiter) -> None:
    limiter.update_utilization(used=0, limit=100)
    low_delay = limiter._compute_delay()

    limiter.update_utilization(used=90, limit=100)
    high_delay = limiter._compute_delay()

    assert high_delay > low_delay


# --- PriceFeedManager tests ---


async def test_manager_empty_raises_configuration_error() -> None:
    manager = PriceFeedManager()
    with pytest.raises(ConfigurationError, match="No feeds registered"):
        await manager.get_ticker("BTC/USDT")


async def test_manager_empty_ohlcv_raises_configuration_error() -> None:
    manager = PriceFeedManager()
    with pytest.raises(ConfigurationError, match="No feeds registered"):
        await manager.get_ohlcv("BTC/USDT")
