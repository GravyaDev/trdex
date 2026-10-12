"""Intent enum and signal→intent translator.

The agent pipeline used to carry a single three-valued ``signal``
(``BUY`` / ``SELL`` / ``HOLD``) through state to express four distinct
operational intents:

    - open a long position
    - close an existing long position
    - open a short position (out of scope today)
    - close an existing short position (out of scope today)

That overloading caused the runner long-only / signal-vs-close paradox:
a ``SELL`` signal that logically meant "close the existing long" was
indistinguishable from "open a short", so Risk Gate 4 blocked it as a
pyramiding attempt and the agent could never exit a position it had
opened.

This module introduces an explicit ``Intent`` enum with all five
values (OPEN/CLOSE × LONG/SHORT plus HOLD) and a translator
``signal_to_intent`` that consults the live portfolio context to map
the rule engine's raw BUY/SELL/HOLD output to an Intent. The rule
engine stays ignorant of portfolio state (single responsibility); the
translation happens downstream in the Analyst node.

Design decisions (from brainstorm 2026-04-07):

    - D1: 5 values (not 3) — semantic honesty, type-checker exhaustiveness
    - D2: lives in its own module to avoid import cycles
    - D3: boolean helpers for concise call-site logic
    - D4 (rev): translator signature takes ``symbol`` explicitly so the
      has-position check cannot be computed for the wrong symbol
    - D5: rule engine does not know about Intent; translator wraps it
    - D21: translator only considers agent-sourced positions (ignores
      Telegram-opened positions to prevent cross-source contamination)
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.agents.state import PortfolioContext


class Intent(StrEnum):
    """Operational intent emitted by the Analyst node.

    Stored in the DB (``agent_runs.signal`` column) as the lowercase
    enum value for backwards-compat with the existing column name. The
    column is called ``signal`` for historical reasons — see D11 (rev)
    and D24 in the brainstorm decision log.
    """

    OPEN_LONG = "open_long"
    CLOSE_LONG = "close_long"
    OPEN_SHORT = "open_short"
    CLOSE_SHORT = "close_short"
    HOLD = "hold"

    @property
    def is_open(self) -> bool:
        """True for ``OPEN_LONG`` / ``OPEN_SHORT``."""
        return self in (Intent.OPEN_LONG, Intent.OPEN_SHORT)

    @property
    def is_close(self) -> bool:
        """True for ``CLOSE_LONG`` / ``CLOSE_SHORT``."""
        return self in (Intent.CLOSE_LONG, Intent.CLOSE_SHORT)

    @property
    def is_long(self) -> bool:
        """True for ``OPEN_LONG`` / ``CLOSE_LONG``."""
        return self in (Intent.OPEN_LONG, Intent.CLOSE_LONG)

    @property
    def is_short(self) -> bool:
        """True for ``OPEN_SHORT`` / ``CLOSE_SHORT``."""
        return self in (Intent.OPEN_SHORT, Intent.CLOSE_SHORT)


def signal_to_intent(
    signal: str,
    symbol: str,
    portfolio_ctx: PortfolioContext,
    *,
    shorts: bool = False,
) -> Intent:
    """Translate rule-engine / LLM output (``BUY`` / ``SELL`` / ``HOLD``) to an Intent.

    Consults the agent's own open position on ``symbol`` (D21: positions
    opened by other sources are ignored here; the Risk node guards
    against opposite sides across sources). ``shorts`` is true when the
    venue is perpetual futures (``trdex.risk.leverage``); on spot the
    system stays long-only.

    Truth table (no pyramiding, no flip within one cycle):

        signal   agent position   intent
        ──────   ──────────────   ──────────────────────────────
        BUY      none             OPEN_LONG
        BUY      long             HOLD
        BUY      short            CLOSE_SHORT
        SELL     none             OPEN_SHORT if shorts else HOLD
        SELL     long             CLOSE_LONG
        SELL     short            HOLD
        HOLD     any              HOLD

    Raises ``ValueError`` on any other signal (a programmer error).
    """
    if signal == "HOLD":
        return Intent.HOLD
    if signal not in ("BUY", "SELL"):
        raise ValueError(
            f"signal_to_intent: unknown signal {signal!r} (expected BUY/SELL/HOLD)"
        )

    side = None
    if symbol in portfolio_ctx.open_position_symbols_by_agent:
        # Positions recorded before shorts existed carry no side: long.
        side = portfolio_ctx.agent_position_sides.get(symbol, "BUY")

    if signal == "BUY":
        if side == "SELL":
            return Intent.CLOSE_SHORT
        return Intent.HOLD if side == "BUY" else Intent.OPEN_LONG

    # SELL
    if side == "BUY":
        return Intent.CLOSE_LONG
    if side == "SELL":
        return Intent.HOLD
    return Intent.OPEN_SHORT if shorts else Intent.HOLD
