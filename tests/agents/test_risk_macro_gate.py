"""Risk Gate 4d: no new entries around high-impact macro events."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.agents.test_risk_sizing_gate import FLAT, _Cfg, _run, _state
from trdex.agents.intent import Intent
from trdex.market.macro_calendar import MacroCalendar, MacroEvent


def _calendar(monkeypatch, *, event_in_minutes=None, fresh=True):
    cal = MacroCalendar()
    now = datetime.now(tz=UTC)
    cal.last_success = now if fresh else now - timedelta(days=3)
    if event_in_minutes is not None:
        cal.events = [
            MacroEvent("USD", "FOMC Statement", now + timedelta(minutes=event_in_minutes), "High")
        ]
    monkeypatch.setattr("trdex.market.macro_calendar._calendar", cal)


@pytest.mark.asyncio
async def test_entry_waits_around_a_high_impact_event(monkeypatch):
    _calendar(monkeypatch, event_in_minutes=10)
    result = await _run(_state(FLAT))
    assert result.risk.approved is False
    assert result.risk.reason.startswith("Macro event gate: USD FOMC Statement")


@pytest.mark.asyncio
async def test_close_is_never_blocked_by_the_macro_gate(monkeypatch):
    _calendar(monkeypatch, event_in_minutes=10)
    result = await _run(_state(FLAT, Intent.CLOSE_LONG, positions=["ENJ/USDT"]))
    assert result.risk.approved is True


@pytest.mark.asyncio
async def test_far_events_and_disabled_gate_let_entries_through(monkeypatch):
    _calendar(monkeypatch, event_in_minutes=120)
    assert (await _run(_state(FLAT))).risk.approved is True
    _calendar(monkeypatch, event_in_minutes=10)
    off = _Cfg(macro_gate_enabled="false")
    assert (await _run(_state(FLAT), cfg=off)).risk.approved is True


@pytest.mark.asyncio
async def test_stale_calendar_is_off_in_simulation_and_blocks_live(monkeypatch):
    _calendar(monkeypatch, fresh=False)
    assert (await _run(_state(FLAT))).risk.approved is True
    calm = [100.0 + (i % 2) for i in range(30)]
    live = await _run(_state(calm), cfg=_Cfg(regime_cv_min=0.001, regime_cv_max=0.04), mode="live")
    assert live.risk.approved is False
    assert "economic calendar unavailable" in live.risk.reason


@pytest.mark.asyncio
async def test_invalid_settings_fail_closed(monkeypatch):
    _calendar(monkeypatch)
    result = await _run(_state(FLAT), cfg=_Cfg(macro_gate_impacts="Apocalyptic"))
    assert result.risk.approved is False
    assert "macro gate error (fail-closed)" in result.risk.reason
