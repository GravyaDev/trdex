"""Economic calendar and the macro entry gate (Risk Gate 4d, Telegram)."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from trdex.market import macro_calendar as mc
from trdex.market.macro_calendar import (
    MacroCalendar,
    MacroEvent,
    MacroGateConfig,
    macro_block_reason,
    macro_gate_config,
    parse_ff,
)

NOW = datetime(2026, 10, 14, 12, 0, tzinfo=UTC)
CPI = MacroEvent("USD", "CPI m/m", NOW + timedelta(minutes=20), "High", "0.3%", "0.2%")


def _ff(title, country, iso, impact="High"):
    return {
        "title": title,
        "country": country,
        "date": iso,
        "impact": impact,
        "forecast": "0.3%",
        "previous": "",
    }


# ── parsing ───────────────────────────────────────────────────────────────


def test_parse_converts_to_utc_sorts_and_keeps_fields():
    events = parse_ff(
        [
            _ff("Non-Farm Employment Change", "USD", "2026-10-16T08:30:00-04:00"),
            _ff("CPI m/m", "usd", "2026-10-14T08:30:00-04:00"),
        ]
    )
    assert [e.title for e in events] == ["CPI m/m", "Non-Farm Employment Change"]
    assert events[0].time == datetime(2026, 10, 14, 12, 30, tzinfo=UTC)
    assert events[0].currency == "USD" and events[0].forecast == "0.3%"
    assert events[0].previous is None


def test_parse_skips_rows_it_cannot_place_safely():
    events = parse_ff(
        [
            _ff("ok", "USD", "2026-10-14T08:30:00-04:00"),
            _ff("no zone", "USD", "2026-10-14T08:30:00"),
            _ff("bad impact", "USD", "2026-10-14T08:30:00-04:00", impact="Huge"),
            {"title": "missing date", "country": "USD", "impact": "High"},
            "not a dict",
        ]
    )
    assert [e.title for e in events] == ["ok"]


def test_parse_rejects_garbage_payloads():
    with pytest.raises(ValueError):
        parse_ff({"error": "rate limited"})
    with pytest.raises(ValueError):
        parse_ff([{"nope": 1}])
    assert parse_ff([]) == []


# ── config ────────────────────────────────────────────────────────────────


class Cfg:
    def __init__(self, **t):
        self.t = {k: str(v) for k, v in t.items()}

    def get(self, category, key, default=""):
        return self.t.get(key, default) if category == "thresholds" else default


def test_config_defaults_and_overrides():
    assert macro_gate_config(None) == MacroGateConfig()
    assert macro_gate_config(Cfg()) == MacroGateConfig()
    cfg = macro_gate_config(
        Cfg(
            macro_gate_before_min=15,
            macro_gate_after_min="90",
            macro_gate_impacts="High,Medium",
            macro_gate_currencies="usd, eur",
            macro_gate_enabled="false",
        )
    )
    assert cfg.before == timedelta(minutes=15) and cfg.after == timedelta(minutes=90)
    assert cfg.impacts == {"High", "Medium"} and cfg.currencies == {"USD", "EUR"}
    assert cfg.enabled is False
    assert macro_gate_config(Cfg(macro_gate_currencies="ALL")).currencies is None


@pytest.mark.parametrize(
    "bad",
    [
        {"macro_gate_impacts": "Critical"},
        {"macro_gate_before_min": "-5"},
        {"macro_gate_after_min": "soon"},
    ],
)
def test_config_nonsense_raises_so_callers_fail_closed(bad):
    with pytest.raises(ValueError):
        macro_gate_config(Cfg(**bad))


# ── gate ──────────────────────────────────────────────────────────────────

GATE = MacroGateConfig()


def _reason(now, events=(CPI,), cfg=GATE, *, last_success=NOW, live=True):
    return macro_block_reason(events, now, cfg, last_success=last_success, live=live)


def test_entries_wait_from_30_min_before_to_60_min_after():
    t = CPI.time
    assert _reason(t - timedelta(minutes=31)) is None
    assert "CPI m/m" in _reason(t - timedelta(minutes=30))
    assert _reason(t + timedelta(minutes=60)) is not None
    assert _reason(t + timedelta(minutes=61)) is None


def test_only_configured_impacts_and_currencies_count():
    eur = MacroEvent("EUR", "ECB rate", NOW, "High")
    medium = MacroEvent("USD", "Retail Sales", NOW, "Medium")
    assert _reason(NOW, (eur, medium)) is None
    assert _reason(NOW, (eur,), MacroGateConfig(currencies=None)) is not None
    assert (
        _reason(NOW, (medium,), MacroGateConfig(impacts=frozenset({"High", "Medium"}))) is not None
    )


def test_stale_calendar_blocks_live_and_switches_off_in_simulation():
    old = NOW - timedelta(hours=25)
    assert "unavailable" in _reason(NOW, (), last_success=old, live=True)
    assert "never" in _reason(NOW, (), last_success=None, live=True)
    assert _reason(NOW, (CPI,), last_success=old, live=False) is None


def test_disabled_gate_never_blocks():
    assert _reason(NOW, cfg=MacroGateConfig(enabled=False), last_success=None) is None


# ── calendar service ──────────────────────────────────────────────────────


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def _payload(*rows):
    return list(rows)


@pytest.mark.asyncio
async def test_refresh_paces_requests_and_backs_off_after_errors():
    calls = []
    responses = iter(
        [
            RuntimeError("HTTP 429"),
            _payload(_ff("CPI m/m", "USD", "2026-10-14T08:30:00-04:00")),
            _payload(_ff("CPI m/m", "USD", "2026-10-14T08:30:00-04:00")),
        ]
    )

    async def fetch():
        calls.append(clock.t)
        r = next(responses)
        if isinstance(r, Exception):
            raise r
        return r

    clock = Clock(NOW)
    cal = MacroCalendar(fetch=fetch, clock=clock)
    assert await cal.refresh() is False and cal.last_error == "RuntimeError: HTTP 429"
    clock.t = NOW + timedelta(minutes=30)
    assert await cal.refresh() is False and len(calls) == 1  # backing off
    clock.t = NOW + timedelta(hours=1)
    assert await cal.refresh() is True and cal.last_error is None
    assert [e.title for e in cal.events] == ["CPI m/m"]
    clock.t = NOW + timedelta(hours=6, minutes=59)
    assert await cal.refresh() is False  # fresh enough
    clock.t = NOW + timedelta(hours=7)
    assert await cal.refresh() is True and len(calls) == 3


@pytest.mark.asyncio
async def test_new_week_keeps_the_last_two_days_of_the_previous_one():
    week1 = _payload(
        _ff("Old", "USD", "2026-10-09T08:30:00-04:00"),
        _ff("Friday", "USD", "2026-10-16T08:30:00-04:00"),
    )
    week2 = _payload(_ff("Monday", "USD", "2026-10-19T08:30:00-04:00"))
    payloads = iter([week1, week2])

    async def fetch():
        return next(payloads)

    clock = Clock(datetime(2026, 10, 17, 12, tzinfo=UTC))
    cal = MacroCalendar(fetch=fetch, clock=clock)
    await cal.refresh()
    clock.t = datetime(2026, 10, 18, 0, tzinfo=UTC)
    await cal.refresh(force=True)
    assert [e.title for e in cal.events] == ["Friday", "Monday"]


@pytest.mark.asyncio
async def test_loop_notifies_while_stale_at_most_daily(monkeypatch):
    sent = []

    async def notify(event, subject, body):
        sent.append(event)

    async def fail():
        raise RuntimeError("down")

    clock = Clock(NOW)
    cal = MacroCalendar(fetch=fail, clock=clock)
    ticks = iter(range(4))

    async def fake_sleep(_):
        clock.t += timedelta(hours=1)
        if next(ticks) == 3:
            raise asyncio.CancelledError

    monkeypatch.setattr(mc.asyncio, "sleep", fake_sleep)
    with pytest.raises(asyncio.CancelledError):
        await mc.macro_calendar_loop(cal, notify=notify, cfg_provider=lambda: None)
    from trdex.notify.events import Event

    assert sent == [Event.MACRO_CALENDAR_STALE]


@pytest.mark.asyncio
async def test_repository_replaces_only_the_fetched_window():
    from trdex.storage.macro_events_repo import MacroEventsRepository

    class Session:
        def __init__(self):
            self.calls = []

        async def execute(self, stmt, params=None):
            self.calls.append((str(stmt), params))

        async def commit(self):
            self.calls.append(("COMMIT", None))

    s = Session()
    events = [CPI, MacroEvent("USD", "NFP", NOW + timedelta(days=2), "High")]
    assert await MacroEventsRepository(s).replace_window("forexfactory", events, NOW) == 2
    delete, insert, commit = s.calls
    assert delete[0].startswith("DELETE FROM macro_events")
    assert delete[1]["start"] < CPI.time and delete[1]["end"] > events[1].time
    assert insert[0].startswith("INSERT INTO macro_events") and len(insert[1]) == 2
    assert commit[0] == "COMMIT"
