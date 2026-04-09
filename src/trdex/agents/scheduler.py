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

logger = logging.getLogger(__name__)


async def agent_scheduler_loop(
    session_factory,
    feed_manager,
    symbols: Iterable[str],
    interval: int,
    *,
    gateway=None,
    memory_loader=None,
    max_iterations: int | None = None,
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

    symbols_list = list(symbols)
    iterations = 0

    while max_iterations is None or iterations < max_iterations:
        try:
            if get_kill_switch().active:
                logger.warning(
                    "[AgentScheduler] kill switch active - skipping cycle"
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
