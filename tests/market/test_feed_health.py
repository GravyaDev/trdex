"""Per-feed health: outcomes, latency, status and redacted errors."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from trdex.market.manager import DOWN_AFTER_FAILURES, FeedStats, PriceFeedManager


class Feed:
    def __init__(self, name, fail=None):
        self.name = name
        self.fail = fail

    def supports_symbol(self, symbol):
        return True

    async def get_ticker(self, symbol):
        if self.fail:
            raise self.fail
        return SimpleNamespace(price=Decimal("100"))

    async def close(self):
        return None


def test_status_moves_from_idle_to_ok_degraded_down_and_back():
    s = FeedStats("x")
    assert s.status == "idle"
    s.record_success(100)
    assert s.status == "ok" and s.avg_latency_ms == 100
    s.record_success(200)
    assert s.avg_latency_ms == 120  # EWMA 0.8 / 0.2
    for _ in range(DOWN_AFTER_FAILURES - 1):
        s.record_failure(RuntimeError("timeout"), rate_limited=False)
    assert s.status == "degraded"
    s.record_failure(RuntimeError("timeout"), rate_limited=False)
    assert s.status == "down"
    s.record_success(50)
    assert s.status == "ok" and s.consecutive_failures == 0


def test_a_feed_that_never_answered_is_down_at_first_failure():
    s = FeedStats("x")
    s.record_failure(RuntimeError("dns"), rate_limited=False)
    assert s.status == "down"


def test_errors_are_redacted_and_truncated():
    s = FeedStats("x")
    s.record_failure(
        RuntimeError("GET https://api/x?api_key=SECRET&fsym=BTC token=abc" + "z" * 500),
        rate_limited=True,
    )
    assert "SECRET" not in s.last_error and "abc" not in s.last_error
    assert len(s.last_error) <= 200 and s.rate_limited == 1


@pytest.mark.asyncio
async def test_manager_reports_every_registered_feed():
    fm = PriceFeedManager()
    fm.register(Feed("good"))
    fm.register(Feed("bad", fail=RuntimeError("429 Too Many Requests")))
    fm.register(Feed("unused"))
    await fm.get_ticker("BTC/USDT", source="good")
    from trdex.market.manager import FeedError

    with pytest.raises(FeedError):
        await fm.get_ticker("BTC/USDT", source="bad")
    health = {h["name"]: h for h in fm.health()}
    assert health["good"]["status"] == "ok" and health["good"]["last_latency_ms"] is not None
    assert health["bad"]["status"] == "down" and health["bad"]["rate_limited"] == 1
    assert health["unused"]["status"] == "idle"
    assert health["good"]["circuit"] == "closed"


def test_keys_in_url_paths_never_reach_the_status_page():
    import httpx

    from trdex.market.manager import FeedStats

    req = httpx.Request("GET", "https://v6.exchangerate-api.com/v6/SECRETKEY123/latest/EUR")
    exc = httpx.HTTPStatusError(
        "Client error '403 Forbidden' for url "
        "'https://v6.exchangerate-api.com/v6/SECRETKEY123/latest/EUR'",
        request=req,
        response=httpx.Response(403, request=req),
    )
    stats = FeedStats("forex")
    stats.record_failure(exc, rate_limited=False)
    assert "SECRETKEY123" not in stats.last_error
    assert "https://v6.exchangerate-api.com/..." in stats.last_error
