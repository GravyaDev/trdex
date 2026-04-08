"""Unit tests for signal_to_intent translator (D4 rev, D5, D21)."""

from __future__ import annotations

import pytest

from trdex.agents.intent import Intent, signal_to_intent
from trdex.agents.state import PortfolioContext


def _ctx(agent_positions: list[str] | None = None) -> PortfolioContext:
    return PortfolioContext(open_position_symbols_by_agent=agent_positions or [])


def test_buy_no_position_emits_open_long() -> None:
    """Truth table row 1: BUY + no position → OPEN_LONG."""
    assert signal_to_intent("BUY", "BTC/USDT", _ctx()) == Intent.OPEN_LONG


def test_buy_long_position_emits_hold_no_pyramiding() -> None:
    """Truth table row 2: BUY + has long → HOLD (no pyramiding)."""
    ctx = _ctx(["BTC/USDT"])
    assert signal_to_intent("BUY", "BTC/USDT", ctx) == Intent.HOLD


def test_sell_long_position_emits_close_long_THE_FIX() -> None:
    """Truth table row 3: SELL + has long → CLOSE_LONG.

    This is the core fix. Before the refactor, this case was
    indistinguishable from "open a short" and Risk Gate 4 blocked it
    as a pyramiding attempt — so the agent could never close a long
    it had previously opened.
    """
    ctx = _ctx(["BTC/USDT"])
    assert signal_to_intent("SELL", "BTC/USDT", ctx) == Intent.CLOSE_LONG


def test_sell_no_position_emits_hold_no_shorting() -> None:
    """Truth table row 4: SELL + no position → HOLD (system is long-only)."""
    assert signal_to_intent("SELL", "BTC/USDT", _ctx()) == Intent.HOLD


def test_hold_emits_hold() -> None:
    """Truth table row 5: HOLD → HOLD regardless of portfolio state."""
    assert signal_to_intent("HOLD", "BTC/USDT", _ctx()) == Intent.HOLD
    assert signal_to_intent("HOLD", "BTC/USDT", _ctx(["BTC/USDT"])) == Intent.HOLD


def test_unknown_signal_raises() -> None:
    """Garbage input is a programmer error, not runtime ambiguity."""
    with pytest.raises(ValueError, match="unknown signal"):
        signal_to_intent("MAYBE", "BTC/USDT", _ctx())


def test_today_never_emits_short_intents() -> None:
    """Pins the long-only policy of the current iteration.

    If a future change adds short support, this test must be updated
    intentionally — it's a tripwire, not a limitation.
    """
    for signal in ("BUY", "SELL", "HOLD"):
        for ctx in (_ctx(), _ctx(["BTC/USDT"])):
            intent = signal_to_intent(signal, "BTC/USDT", ctx)
            assert intent not in (Intent.OPEN_SHORT, Intent.CLOSE_SHORT), (
                f"signal={signal} ctx={ctx} leaked short intent {intent}"
            )


def test_filters_telegram_positions_by_symbol_only() -> None:
    """D21: translator only looks at ``open_position_symbols_by_agent``.

    A position opened by the Telegram tracker lives in
    ``open_position_symbols`` but NOT in
    ``open_position_symbols_by_agent``, so the agent should never
    attempt to close it (cross-source contamination prevention).
    """
    ctx = PortfolioContext(
        open_position_symbols=["BTC/USDT"],            # Telegram-opened
        open_position_symbols_by_agent=[],             # nothing the agent owns
    )
    # SELL on a symbol the agent doesn't own → HOLD (no-shorting), NOT CLOSE_LONG
    assert signal_to_intent("SELL", "BTC/USDT", ctx) == Intent.HOLD
    # BUY on a Telegram-held symbol → agent still opens its own long,
    # because the translator doesn't consider Telegram positions for
    # pyramiding purposes either. The agent and Telegram are sources
    # that maintain independent position books.
    assert signal_to_intent("BUY", "BTC/USDT", ctx) == Intent.OPEN_LONG


def test_per_symbol_isolation() -> None:
    """Skeptic S4: has-position check is computed for the symbol arg."""
    ctx = _ctx(["BTC/USDT"])
    # SELL on ETH/USDT even though BTC/USDT is held → HOLD (we have no ETH)
    assert signal_to_intent("SELL", "ETH/USDT", ctx) == Intent.HOLD
    # BUY on ETH/USDT is unaffected by BTC/USDT holding → OPEN_LONG
    assert signal_to_intent("BUY", "ETH/USDT", ctx) == Intent.OPEN_LONG
