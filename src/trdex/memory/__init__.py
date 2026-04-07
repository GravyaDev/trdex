"""trdex 6-tier persistent memory subsystem.

Tiers:
1. Static knowledge files (Riferimenti/agents/*.md) — KBLoader
2. Operational memory (trdex_agent_memory table) — AgentMemoryRepository
3. Knowledge nominations (Kloudify file) — TBD
4. Semantic memory (Qdrant trade narratives) — TBD
5. Entity graph (trdex_entity_graph) — already implemented
6. Session logs (agent_runs) — narrative_context() helper
"""

from trdex.memory.context import MemoryContext, MemoryContextLoader
from trdex.memory.kb_loader import KBBlock, KBLoader
from trdex.memory.nominations import Nomination, list_pending, nominate
from trdex.memory.trade_narratives import (
    TradeNarrative,
    TradeNarrativeHit,
    TradeNarrativeService,
    TradeNarrativeStore,
    build_narrative_text,
)

__all__ = [
    "KBBlock",
    "KBLoader",
    "MemoryContext",
    "MemoryContextLoader",
    "Nomination",
    "TradeNarrative",
    "TradeNarrativeHit",
    "TradeNarrativeService",
    "TradeNarrativeStore",
    "build_narrative_text",
    "list_pending",
    "nominate",
]
