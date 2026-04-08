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
) -> Intent:
    """Translate rule-engine output (``BUY`` / ``SELL`` / ``HOLD``) to an Intent.

    Consults ``portfolio_ctx.open_position_symbols_by_agent`` (D21) to
    decide whether a ``SELL`` signal means "close an existing long" or
    "open a short". Today the system is long-only by policy, so
    ``BUY`` + has-position and ``SELL`` + no-position both degrade to
    ``HOLD`` rather than attempting to open a short or pyramid.

    Truth table:

        signal   has_long    intent
        ──────   ─────────   ────────────
        BUY      False       OPEN_LONG
        BUY      True        HOLD         (no pyramiding)
        SELL     True        CLOSE_LONG   ← THE FIX
        SELL     False       HOLD         (long-only, no shorting)
        HOLD     any         HOLD

    Args:
        signal: raw rule-engine output. Must be one of ``"BUY"``,
            ``"SELL"`` or ``"HOLD"``. Any other value raises
            ``ValueError`` — unknown signals are programmer errors,
            not run-time ambiguity.
        symbol: the symbol being analysed. Passed explicitly so the
            has-position check is always computed for the right symbol
            (Skeptic S4 — protects against call-site confusion when
            multiple symbols are cycled).
        portfolio_ctx: the live ``PortfolioContext`` with
            ``open_position_symbols_by_agent`` populated upstream.

    Returns:
        The resolved ``Intent``. The system is long-only today so the
        returned intent is always one of ``OPEN_LONG``, ``CLOSE_LONG``
        or ``HOLD`` — ``OPEN_SHORT`` / ``CLOSE_SHORT`` are reserved
        vocabulary for a future short-enabled iteration and pinned by
        the ``test_today_never_emits_short_intents`` test.
    """
    if signal == "HOLD":
        return Intent.HOLD

    has_long = symbol in portfolio_ctx.open_position_symbols_by_agent

    if signal == "BUY":
        if has_long:
            return Intent.HOLD  # no pyramiding
        return Intent.OPEN_LONG

    if signal == "SELL":
        if has_long:
            return Intent.CLOSE_LONG  # THE FIX
        return Intent.HOLD  # long-only, refuse to open a short

    raise ValueError(
        f"signal_to_intent: unknown signal {signal!r} "
        f"(expected BUY/SELL/HOLD)"
    )
