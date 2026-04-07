"""Scout Agent — news and sentiment monitoring via Qdrant RAG."""

from __future__ import annotations

import logging

from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, SentimentContext
from trdex.context.ingestion import ContextIngestionPipeline

logger = logging.getLogger(__name__)


async def scout_node(state: AgentState) -> AgentState:
    """Retrieve recent news and sentiment context for the target symbol.

    Queries Qdrant for the top-5 most relevant documents.
    Falls back gracefully if Qdrant is unreachable.
    """
    logger.info("[Scout] querying context for %s", state.symbol)

    # Attach the 6-tier memory snapshot for the scout agent (best-effort).
    await attach_memory_snapshot(state, "scout")

    try:
        pipeline = ContextIngestionPipeline()
        hits = await pipeline.query(
            text=f"market news sentiment {state.symbol}",
            symbol=state.symbol,
            limit=5,
        )
        # Also pull global macro context (no symbol filter)
        global_hits = await pipeline.query(
            text="crypto market macro sentiment",
            symbol=None,
            limit=3,
        )
        all_hits = hits + global_hits

        summary_parts = [
            f"[{h['source']}] {h['text'][:120]}" for h in all_hits if h.get("text")
        ]
        summary = "\n".join(summary_parts) if summary_parts else "No context available."

        state.sentiment = SentimentContext(items=all_hits, summary=summary)
        logger.info("[Scout] retrieved %d context documents", len(all_hits))

    except Exception as exc:
        logger.warning("[Scout] context retrieval failed: %s — proceeding without context", exc)
        state.sentiment = SentimentContext(summary="Context unavailable.")

    return state
