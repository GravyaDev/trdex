"""Tests for persistent stop-loss event log.

Before migration 013 the StopLossMonitor kept events in a Python
list that was wiped on every restart. These tests cover the new
persistence path: write-through on check_now(), cache hydration
on start(), and counter semantics in /v1/risk/status.

Uses a fake session factory with an in-memory row store — no real
DB needed, and no coupling to the specific ORM table layout.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from trdex.risk.stop_loss import StopLossEvent, StopLossMonitor, StopReason


# ── Fake repo / session wiring ──────────────────────────────────────────────


class _FakeRow:
    """Mimics StopLossEventRecord just enough for the monitor's hydrate path."""

    def __init__(
        self,
        *,
        reason: str,
        symbol: str | None,
        position_id: int | None,
        trigger_price,
        entry_price,
        loss_pct: float | None,
        message: str,
        fired_at: datetime,
    ) -> None:
        self.reason = reason
        self.symbol = symbol
        self.position_id = position_id
        self.trigger_price = trigger_price
        self.entry_price = entry_price
        self.loss_pct = loss_pct
        self.message = message
        self.fired_at = fired_at


class _FakeRepo:
    def __init__(self) -> None:
        self.rows: list[_FakeRow] = []
        self.save_fail: bool = False

    async def save(
        self,
        *,
        reason: str,
        symbol: str | None,
        position_id: int | None,
        trigger_price: float | None,
        entry_price: float | None,
        loss_pct: float | None,
        message: str,
        fired_at: datetime | None = None,
    ):
        if self.save_fail:
            raise RuntimeError("simulated DB write failure")
        row = _FakeRow(
            reason=reason,
            symbol=symbol,
            position_id=position_id,
            trigger_price=trigger_price,
            entry_price=entry_price,
            loss_pct=loss_pct,
            message=message,
            fired_at=fired_at or datetime.now(tz=timezone.utc),
        )
        self.rows.append(row)
        return row

    async def recent(self, limit: int = 50) -> list[_FakeRow]:
        # Newest first, matching the real repo contract
        return sorted(self.rows, key=lambda r: r.fired_at, reverse=True)[:limit]

    async def count(self) -> int:
        return len(self.rows)


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return None


def _install_fake_repo(monkeypatch, repo: _FakeRepo):
    """Replace StopLossEventRepository on its source module so every
    `from trdex.storage.stop_loss_event_repo import StopLossEventRepository`
    inside the monitor resolves to a stub delegating to `repo`.
    Returns a session_factory that yields dummy sessions.
    """

    class _StubRepo:
        def __init__(self, _session):
            pass

        async def save(self, **kwargs):
            return await repo.save(**kwargs)

        async def recent(self, limit: int = 50):
            return await repo.recent(limit=limit)

        async def count(self):
            return await repo.count()

    import trdex.storage.stop_loss_event_repo as repo_mod

    monkeypatch.setattr(
        repo_mod, "StopLossEventRepository", _StubRepo, raising=True,
    )

    def factory():
        return _FakeSession()

    return factory


def _make_monitor(session_factory) -> StopLossMonitor:
    """Build a StopLossMonitor with no-op feed manager — we only
    exercise the persistence paths, not the price-check logic.
    """
    class _NullFeeds:
        feeds: dict = {}

    return StopLossMonitor(
        session_factory=session_factory,
        feed_manager=_NullFeeds(),
    )


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_persist_event_writes_to_repo(monkeypatch) -> None:
    repo = _FakeRepo()
    sf = _install_fake_repo(monkeypatch, repo)
    mon = _make_monitor(sf)

    event = StopLossEvent(
        reason=StopReason.POSITION_STOP_LOSS,
        symbol="BTC/USDT",
        position_id=42,
        trigger_price=57000.0,
        entry_price=60000.0,
        loss_pct=-0.05,
        message="SL hit",
    )
    await mon._persist_event(event)

    assert len(repo.rows) == 1
    row = repo.rows[0]
    assert row.reason == "position_stop_loss"
    assert row.symbol == "BTC/USDT"
    assert row.position_id == 42
    assert row.loss_pct == pytest.approx(-0.05)
    assert mon._events_fired_total == 1


@pytest.mark.asyncio
async def test_persist_event_swallows_db_failure(monkeypatch, caplog) -> None:
    repo = _FakeRepo()
    repo.save_fail = True
    sf = _install_fake_repo(monkeypatch, repo)
    mon = _make_monitor(sf)

    event = StopLossEvent(
        reason=StopReason.KILL_SWITCH,
        symbol=None,
        position_id=None,
        trigger_price=None,
        entry_price=None,
        loss_pct=None,
        message="Kill switch triggered",
    )
    # Must not raise — persistence failure cannot interrupt the
    # risk monitor's protective path.
    await mon._persist_event(event)
    assert mon._events_fired_total == 0
    assert len(repo.rows) == 0


@pytest.mark.asyncio
async def test_hydrate_events_from_db_loads_cache(monkeypatch) -> None:
    repo = _FakeRepo()
    base = datetime(2026, 4, 11, 12, 0, tzinfo=timezone.utc)
    for i in range(3):
        await repo.save(
            reason="position_stop_loss",
            symbol=f"SYM{i}/USDT",
            position_id=i,
            trigger_price=float(100 - i),
            entry_price=100.0,
            loss_pct=-0.01 * (i + 1),
            message=f"event {i}",
            fired_at=base + timedelta(minutes=i),
        )
    sf = _install_fake_repo(monkeypatch, repo)
    mon = _make_monitor(sf)

    await mon._hydrate_events_from_db()

    assert mon._events_fired_total == 3
    assert len(mon._events) == 3
    # Cache is oldest-first to match the historical `_events[-50:]` slice
    assert mon._events[0].symbol == "SYM0/USDT"
    assert mon._events[-1].symbol == "SYM2/USDT"
    # recent_events property returns the formatted view
    recent = mon.recent_events
    assert [r["symbol"] for r in recent] == ["SYM0/USDT", "SYM1/USDT", "SYM2/USDT"]


@pytest.mark.asyncio
async def test_hydrate_swallows_db_error(monkeypatch) -> None:
    """Transient DB failures at hydrate time leave the monitor
    functional with an empty cache — must never crash startup.
    """
    import trdex.storage.stop_loss_event_repo as repo_mod

    class _BrokenRepo:
        def __init__(self, _session):
            pass

        async def recent(self, limit: int = 50):
            raise RuntimeError("DB down")

        async def count(self):
            raise RuntimeError("DB down")

    monkeypatch.setattr(repo_mod, "StopLossEventRepository", _BrokenRepo, raising=True)

    def factory():
        return _FakeSession()

    mon = _make_monitor(factory)
    await mon._hydrate_events_from_db()

    assert mon._events == []
    assert mon._events_fired_total == 0


@pytest.mark.asyncio
async def test_events_fired_status_uses_persistent_counter(monkeypatch) -> None:
    """/v1/risk/status must report the cumulative persistent count,
    not the current in-memory cache length. Before the fix this
    showed 0 on every restart even if thousands of events had fired
    historically.
    """
    repo = _FakeRepo()
    sf = _install_fake_repo(monkeypatch, repo)
    mon = _make_monitor(sf)

    # Simulate prior history
    for i in range(5):
        await repo.save(
            reason="position_take_profit",
            symbol="ETH/USDT",
            position_id=i,
            trigger_price=3500.0,
            entry_price=3000.0,
            loss_pct=0.166,
            message="TP",
            fired_at=datetime.now(tz=timezone.utc),
        )

    await mon._hydrate_events_from_db()
    assert mon.status["events_fired"] == 5

    # A new event persists and bumps the counter
    await mon._persist_event(
        StopLossEvent(
            reason=StopReason.TRAILING_STOP,
            symbol="BTC/USDT",
            position_id=99,
            trigger_price=58000.0,
            entry_price=60000.0,
            loss_pct=-0.033,
            message="trail",
        )
    )
    assert mon.status["events_fired"] == 6
