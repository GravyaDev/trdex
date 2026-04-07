"""Shared helpers for wiring the 6-tier MemoryContext into agent nodes.

Each agent node calls :func:`attach_memory_snapshot` once. The helper:

- bails out cleanly if no memory loader is injected (tests / minimal setup)
- builds the snapshot via the loader, swallowing any failure
- stores the rendered prompt text under ``state.memory_snapshots[agent_name]``
- keeps ``state.memory_snapshot_text`` in sync the *first* time it is set
  (backward compatibility for callers reading the legacy field)
- returns the rendered text (empty string on failure) so callers can log it

This is intentionally a *read* operation only. Agent decision logic must
NEVER branch on the snapshot — it is observability/prompt material, not
business state. Hard rules stay rule-based.
"""

from __future__ import annotations

import logging

from trdex.agents.state import AgentState

logger = logging.getLogger(__name__)


async def attach_memory_snapshot(
    state: AgentState,
    agent_name: str,
    *,
    similarity_query: str | None = None,
) -> str:
    """Build the memory snapshot for ``agent_name`` and attach it to ``state``.

    Returns the rendered prompt text, or an empty string if no loader is
    available or the build failed.
    """
    if state.memory_loader is None:
        return ""
    try:
        ctx = await state.memory_loader.build(
            agent_name,
            state.symbol,
            similarity_query=similarity_query,
        )
    except Exception:
        logger.exception("[memory] snapshot build failed for agent=%s", agent_name)
        return ""

    if ctx.is_empty():
        return ""

    text = ctx.to_prompt_text()
    state.memory_snapshots[agent_name] = text

    # Keep legacy field populated by the first node that writes (Analyst,
    # in normal flow). Don't overwrite if already set by an earlier node.
    if not state.memory_snapshot_text:
        state.memory_snapshot_text = text

    logger.debug(
        "[memory] snapshot attached agent=%s kb=%d ops=%d facts=%d runs=%d sims=%d",
        agent_name,
        len(ctx.kb_blocks),
        sum(len(v) for v in ctx.operational.values()),
        len(ctx.entity_facts),
        ctx.narrative.count if ctx.narrative else 0,
        len(ctx.similar_trades),
    )
    return text
