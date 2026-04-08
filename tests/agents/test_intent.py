"""Unit tests for Intent enum (D1, D3)."""

from __future__ import annotations

from trdex.agents.intent import Intent


def test_intent_has_5_values() -> None:
    """D1: enum carries all five operational intents."""
    assert set(Intent) == {
        Intent.OPEN_LONG,
        Intent.CLOSE_LONG,
        Intent.OPEN_SHORT,
        Intent.CLOSE_SHORT,
        Intent.HOLD,
    }


def test_is_open_helpers() -> None:
    """D3: boolean helpers partition the enum correctly."""
    assert Intent.OPEN_LONG.is_open
    assert Intent.OPEN_SHORT.is_open
    assert not Intent.CLOSE_LONG.is_open
    assert not Intent.CLOSE_SHORT.is_open
    assert not Intent.HOLD.is_open

    assert Intent.CLOSE_LONG.is_close
    assert Intent.CLOSE_SHORT.is_close
    assert not Intent.OPEN_LONG.is_close
    assert not Intent.OPEN_SHORT.is_close
    assert not Intent.HOLD.is_close

    assert Intent.OPEN_LONG.is_long
    assert Intent.CLOSE_LONG.is_long
    assert not Intent.OPEN_SHORT.is_long
    assert not Intent.CLOSE_SHORT.is_long
    assert not Intent.HOLD.is_long

    assert Intent.OPEN_SHORT.is_short
    assert Intent.CLOSE_SHORT.is_short
    assert not Intent.OPEN_LONG.is_short
    assert not Intent.CLOSE_LONG.is_short
    assert not Intent.HOLD.is_short


def test_intent_is_strenum_for_db_persistence() -> None:
    """StrEnum: values are equal to their string form (agent_runs.signal column)."""
    assert Intent.OPEN_LONG == "open_long"
    assert Intent.CLOSE_LONG == "close_long"
    assert Intent.OPEN_SHORT == "open_short"
    assert Intent.CLOSE_SHORT == "close_short"
    assert Intent.HOLD == "hold"
