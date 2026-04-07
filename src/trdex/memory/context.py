"""MemoryContext aggregator — single entry point across the 6-tier stack.

Given an agent name and a target symbol, builds a structured snapshot pulling
from every persistent memory tier:

    Tier 1 — KB blocks (HARD/PARAM/HEUR/PROMPT) for the agent
    Tier 2 — operational memories from trdex_agent_memory for the agent
    Tier 5 — currently active facts about the symbol from the entity graph
    Tier 6 — narrative recap of the last N agent_runs for the symbol

Tier 3 (nominations) is write-only. Tier 4 (Qdrant trade narratives) is not
yet implemented and is left out — it can be added without breaking callers.

Design notes:
- All tier reads are independent: a failure or missing dependency in one tier
  must not prevent the others from being returned. Errors are logged and the
  field is left empty.
- The aggregator never writes. It is safe to call on any cycle.
- ``to_prompt_text()`` produces an LLM-ready string. Empty tiers are skipped
  so the prompt stays compact.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from trdex.memory.kb_loader import KBBlock, KBLoader
from trdex.memory.predicates import SUBJECT_SYMBOL
from trdex.memory.trade_narratives import TradeNarrativeHit, TradeNarrativeService
from trdex.storage.agent_memory_repo import AgentMemoryRepository
from trdex.storage.agent_run_repo import AgentRunRepository, RunNarrative
from trdex.storage.entity_graph_repo import EntityGraphRepository

logger = logging.getLogger(__name__)


@dataclass
class MemoryContext:
    """Snapshot of everything the persistent memory stack knows right now."""

    agent: str
    symbol: str
    kb_blocks: list[KBBlock] = field(default_factory=list)
    operational: dict[str, Any] = field(default_factory=dict)
    # operational[kind] -> list of {"key": ..., "value": ..., "updated_at": ...}
    entity_facts: dict[str, Any] = field(default_factory=dict)
    # predicate -> object_value (from entity graph bundle)
    narrative: RunNarrative | None = None
    similar_trades: list[TradeNarrativeHit] = field(default_factory=list)
    # Tier 4 — semantically similar past closed trades

    def is_empty(self) -> bool:
        return (
            not self.kb_blocks
            and not self.operational
            and not self.entity_facts
            and (self.narrative is None or self.narrative.count == 0)
            and not self.similar_trades
        )

    def to_prompt_text(self, *, max_kb_blocks: int = 8) -> str:
        """Render a compact, LLM-ready textual representation.

        Sections that are empty are skipped entirely. KB blocks are truncated
        to ``max_kb_blocks`` to keep the prompt bounded.
        """
        sections: list[str] = []
        sections.append(f"### Memory snapshot — agent={self.agent} symbol={self.symbol}")

        if self.kb_blocks:
            shown = self.kb_blocks[:max_kb_blocks]
            lines = ["", "**Knowledge base (Tier 1):**"]
            for b in shown:
                title = f" — {b.title}" if b.title else ""
                lines.append(f"- `{b.id}` [{b.type}]{title}")
            extra = len(self.kb_blocks) - len(shown)
            if extra > 0:
                lines.append(f"- (+{extra} more blocks)")
            sections.append("\n".join(lines))

        if self.operational:
            lines = ["", "**Operational memory (Tier 2):**"]
            for kind, rows in self.operational.items():
                lines.append(f"- {kind}: {len(rows)} entries")
            sections.append("\n".join(lines))

        if self.entity_facts:
            lines = ["", f"**Entity facts (Tier 5) for {self.symbol}:**"]
            for predicate, value in self.entity_facts.items():
                lines.append(f"- {predicate}: {value}")
            sections.append("\n".join(lines))

        if self.narrative is not None and self.narrative.count > 0:
            sections.append("\n**Recent runs (Tier 6):**\n" + self.narrative.text)

        if self.similar_trades:
            lines = ["", "**Similar past trades (Tier 4):**"]
            for h in self.similar_trades:
                pnl = (
                    f"{'+' if (h.pnl_pct or 0) >= 0 else ''}{h.pnl_pct:.2f}%"
                    if h.pnl_pct is not None
                    else "n/a"
                )
                lines.append(
                    f"- score={h.score:.2f} {h.signal} {h.outcome} pnl={pnl} — {h.text}"
                )
            sections.append("\n".join(lines))

        return "\n".join(sections)


class MemoryContextLoader:
    """Builds ``MemoryContext`` snapshots by querying every available tier.

    The loader holds the (cheap) KBLoader once and creates short-lived
    repositories on each call using the provided async session factory. This
    matches the existing pattern in `agents/analyst.py` and friends.

    Usage:
        loader = MemoryContextLoader(kb_loader, session_factory)
        ctx = await loader.build("analyst", "BTC/USDT")
        prompt = ctx.to_prompt_text()
    """

    def __init__(
        self,
        kb_loader: KBLoader | None,
        session_factory: Any | None,
        trade_narrative_service: TradeNarrativeService | None = None,
    ) -> None:
        self._kb = kb_loader
        self._session_factory = session_factory
        self._narratives = trade_narrative_service

    async def build(
        self,
        agent: str,
        symbol: str,
        *,
        run_history_limit: int = 10,
        operational_kinds: list[str] | None = None,
        similarity_query: str | None = None,
        similar_trades_limit: int = 5,
    ) -> MemoryContext:
        """Aggregate every tier into a single MemoryContext.

        Each tier is wrapped in its own try/except so a failure in one tier
        cannot kill the whole snapshot.
        """
        ctx = MemoryContext(agent=agent, symbol=symbol)

        # Tier 1 — static knowledge base
        if self._kb is not None:
            try:
                ctx.kb_blocks = self._kb.for_agent(agent)
            except Exception:
                logger.exception("[memory_context] tier1 KB lookup failed for %s", agent)

        # Tier 2/5/6 require a DB session — bail out gracefully if absent
        if self._session_factory is None:
            return ctx

        # Tier 2 — operational memory
        try:
            async with self._session_factory() as session:
                repo = AgentMemoryRepository(session)
                if operational_kinds:
                    for kind in operational_kinds:
                        rows = await repo.list_by_kind(agent, kind)
                        if rows:
                            ctx.operational[kind] = [
                                {
                                    "key": r.key,
                                    "value": r.value,
                                    "updated_at": r.updated_at,
                                }
                                for r in rows
                            ]
                else:
                    rows = await repo.list_for_agent(agent)
                    grouped: dict[str, list[dict]] = {}
                    for r in rows:
                        grouped.setdefault(r.kind, []).append(
                            {"key": r.key, "value": r.value, "updated_at": r.updated_at}
                        )
                    ctx.operational = grouped
        except Exception:
            logger.exception("[memory_context] tier2 agent_memory lookup failed")

        # Tier 5 — entity graph bundle
        try:
            async with self._session_factory() as session:
                repo = EntityGraphRepository(session)
                ctx.entity_facts = await repo.bundle(SUBJECT_SYMBOL, symbol)
        except Exception:
            logger.exception("[memory_context] tier5 entity graph lookup failed")

        # Tier 6 — recent runs narrative
        try:
            async with self._session_factory() as session:
                repo = AgentRunRepository(session)
                ctx.narrative = await repo.narrative_context(symbol, limit=run_history_limit)
        except Exception:
            logger.exception("[memory_context] tier6 agent_runs lookup failed")

        # Tier 4 — semantically similar past trades (best-effort, optional service)
        if self._narratives is not None:
            query = similarity_query or self._default_similarity_query(ctx)
            if query:
                try:
                    ctx.similar_trades = await self._narratives.search(
                        query, symbol=symbol, limit=similar_trades_limit
                    )
                except Exception:
                    logger.exception("[memory_context] tier4 narrative search failed")

        return ctx

    @staticmethod
    def _default_similarity_query(ctx: MemoryContext) -> str:
        """Construct a fallback similarity query from the rest of the snapshot.

        Used when the caller doesn't pass an explicit ``similarity_query``.
        Combines symbol, current entity facts (e.g. volatility regime), and
        the most recent run summary if any.
        """
        bits: list[str] = [ctx.symbol]
        for predicate, value in ctx.entity_facts.items():
            if isinstance(value, dict):
                vstr = " ".join(f"{k}={v}" for k, v in value.items())
            else:
                vstr = str(value)
            bits.append(f"{predicate} {vstr}")
        if ctx.narrative is not None and ctx.narrative.count > 0:
            sigs = " ".join(f"{k}:{v}" for k, v in ctx.narrative.signals.items())
            bits.append(f"recent {sigs}")
        return " ".join(bits)
