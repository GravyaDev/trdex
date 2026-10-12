"""Background loop that runs the agent cycle on a fixed schedule.

Extracted from ``trdex.api.app`` so the loop can be:
    - imported and started by the FastAPI lifespan (production path)
    - imported and run for N iterations by smoke_level4 (test path)
    - eventually unit-tested without spinning up FastAPI / Telegram /
      Qdrant / news ingestion that the lifespan also bootstraps

The loop is self-contained: it builds a fresh ``AgentRunner`` per cycle
using the injected ``session_factory`` so it doesn't share session state
across symbols, and it honours the global kill switch on every iteration.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterable
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _parse_active_hours(spec: str) -> tuple[int, int] | None:
    """Parse an 'HH:MM-HH:MM' spec into (start_hour, end_hour).

    Returns None if the spec is empty or unparseable (= always active).
    Examples:
        '08:00-22:00' → (8, 22)
        '00:00-24:00' → (0, 24)  (= always active, same as empty)
        ''            → None     (= always active)
    """
    if not spec or not spec.strip():
        return None
    try:
        start_s, end_s = spec.strip().split("-")
        start_h = int(start_s.split(":")[0])
        end_h = int(end_s.split(":")[0])
        if start_h == 0 and end_h == 24:
            return None  # equivalent to always active
        return (start_h, end_h)
    except (ValueError, IndexError):
        logger.warning("[AgentScheduler] invalid active_hours spec %r — running H24", spec)
        return None


def _is_active_now(window: tuple[int, int] | None) -> bool:
    """Check if the current UTC hour falls within the active window."""
    if window is None:
        return True
    start, end = window
    hour = datetime.now(tz=timezone.utc).hour
    if start <= end:
        return start <= hour < end
    # Wrap-around (e.g. 22:00-06:00)
    return hour >= start or hour < end


# ── Runtime-mutable symbol list ────────────────────────────────────────────
# The scheduler reads this at every tick. The API endpoint updates it.
# Not persisted — on restart, re-read from env var (Coolify UI).

_runtime_symbols: list[str] | None = None


def set_runtime_symbols(symbols: list[str]) -> None:
    """Replace the scheduler's symbol list at runtime (no restart needed)."""
    global _runtime_symbols
    _runtime_symbols = list(symbols)
    logger.info("[AgentScheduler] symbols updated at runtime: %s", _runtime_symbols)


def get_runtime_symbols() -> list[str] | None:
    """Return the runtime symbol list, or None if not overridden."""
    return _runtime_symbols


async def agent_scheduler_loop(
    session_factory,
    feed_manager,
    symbols: Iterable[str],
    interval: int,
    *,
    gateway=None,
    memory_loader=None,
    llm_caller=None,
    max_iterations: int | None = None,
    active_hours: str = "",
) -> int:
    """Run the Scout->Analyst->Risk->Executor cycle on a schedule.

    Args:
        session_factory: async sqlalchemy sessionmaker.
        feed_manager: configured ``PriceFeedManager`` (must have at least
            one feed registered, e.g. BinanceFeed).
        symbols: iterable of trading pairs to cycle through every tick.
        interval: seconds to sleep between cycles. Lower bound is set
            by the caller — this function does not sanity-check it.
        gateway: optional execution gateway to inject into AgentRunner.
            Defaults to None, in which case the runner builds its own
            DefaultExecutionGateway.create() lazily.
        memory_loader: optional ``MemoryContextLoader`` to inject into
            AgentRunner so the agents see the 6-tier memory snapshot.
        max_iterations: when set, the loop runs at most this many ticks
            and then returns. ``None`` means run forever (production
            mode). The smoke test passes a small integer.

    Returns:
        The number of ticks actually completed (always equal to
        ``max_iterations`` on a clean run; smaller if cancelled).

    The function never raises out: per-symbol cycle errors are logged
    and swallowed so a single bad symbol cannot kill the whole loop.
    Cancellation via ``asyncio.CancelledError`` is honoured cleanly at
    the cycle boundary AND inside the sleep — the production path
    relies on this.
    """
    # Local imports keep the module cheap to import for tests.
    from trdex.agents.runner import AgentRunner
    from trdex.risk.stop_loss import get_kill_switch

    initial_symbols = list(symbols)
    # Seed the runtime list so get_runtime_symbols() is never None
    # after the first call. API updates override this.
    if _runtime_symbols is None:
        set_runtime_symbols(initial_symbols)
    hours_window = _parse_active_hours(active_hours)
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        # Re-read symbols every tick so runtime updates take effect
        symbols_list = get_runtime_symbols() or initial_symbols
        try:
            if get_kill_switch().active:
                logger.warning(
                    "[AgentScheduler] kill switch active - skipping cycle"
                )
            elif not _is_active_now(hours_window):
                logger.debug(
                    "[AgentScheduler] outside active hours %s — skipping cycle",
                    active_hours,
                )
            else:
                for sym in symbols_list:
                    try:
                        async with session_factory() as session:
                            runner = AgentRunner(
                                session,
                                feed_manager,
                                session_factory=session_factory,
                                gateway=gateway,
                                memory_loader=memory_loader,
                                llm_caller=llm_caller,
                            )
                            state = await runner.run(sym)
                            logger.info(
                                "[AgentScheduler] %s -> intent=%s order=%s",
                                sym,
                                state.analysis.intent.value,
                                state.order.status,
                            )
                    except Exception:
                        logger.exception(
                            "[AgentScheduler] cycle failed for %s", sym
                        )
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("[AgentScheduler] unexpected error")

        iterations += 1
        if max_iterations is not None and iterations >= max_iterations:
            break

        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break

    return iterations
