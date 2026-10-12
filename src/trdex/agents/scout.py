"""Scout Agent — news and sentiment monitoring via Qdrant RAG.

Two execution paths:

1. **LLM path** (when ``state.llm_caller`` is injected and scout config has
   ``llm_enabled=True``): retrieves RAG documents from Qdrant, calls the LLM
   to produce a structured ``ScoutOutput`` with summary + sentiment score.
   Includes sentiment calibration check (Rev 1 — S9).

2. **Fallback path** (LLM disabled or fails): concatenates RAG hits as before
   (``[source] text[:120]``). No LLM interpretation.
"""

from __future__ import annotations

import logging
import statistics

from trdex.agents.memory_helpers import attach_memory_snapshot
from trdex.agents.state import AgentState, SentimentContext
from trdex.context.ingestion import ContextIngestionPipeline

logger = logging.getLogger(__name__)

# Sentiment divergence threshold for calibration check (Rev 1 — S9).
# If LLM score and naive average diverge by more than this, use the naive average.
_SENTIMENT_DIVERGENCE_THRESHOLD = 0.5


def _naive_sentiment_avg(hits: list[dict]) -> float | None:
    """Compute the naive average of sentiment scores from RAG hits."""
    sentiments = [
        h["sentiment"]
        for h in hits
        if isinstance(h.get("sentiment"), float | int)
    ]
    return statistics.mean(sentiments) if sentiments else None


async def _llm_scout_summarize(
    state: AgentState,
    all_hits: list[dict],
) -> tuple[str, float | None, list[str]] | None:
    """Call the LLM to summarize RAG hits.

    Returns ``(summary, sentiment_score, key_events)`` or ``None`` on failure.
    """
    if state.llm_caller is None:
        return None

    from trdex.agents.prompt_builder import build_scout_messages
    from trdex.agents.structured_output import ScoutOutput
    from trdex.config import get_settings

    settings = get_settings()
    config = state.llm_caller.configs.get("scout")
    system_prompt = config.system_prompt if config else ""

    messages = build_scout_messages(
        state,
        system_prompt=system_prompt,
        rag_hits=all_hits,
        max_prompt_tokens=settings.llm_max_prompt_tokens,
    )

    result = await state.llm_caller.invoke("scout", messages, ScoutOutput)
    if result is None:
        return None

    return (result.summary, result.sentiment_score, result.key_events)


async def scout_node(state: AgentState) -> AgentState:
    """Retrieve recent news and sentiment context for the target symbol.

    Queries Qdrant for the top-5 most relevant documents + top-3 macro.
    Then tries the LLM path for summarization; falls back to string concat.
    """
    logger.info("[Scout] querying context for %s", state.symbol)

    # Attach the 6-tier memory snapshot for the scout agent (best-effort).
    await attach_memory_snapshot(state, "scout")

    all_hits: list[dict] = []
    try:
        pipeline = ContextIngestionPipeline()
        hits = await pipeline.query(
            text=f"market news sentiment {state.symbol}",
            symbol=state.symbol,
            limit=5,
        )
        global_hits = await pipeline.query(
            text="crypto market macro sentiment",
            symbol=None,
            limit=3,
        )
        all_hits = hits + global_hits
        logger.info("[Scout] retrieved %d context documents", len(all_hits))
    except Exception as exc:
        logger.warning("[Scout] context retrieval failed: %s — proceeding without context", exc)

    # ── Try LLM path ────────────────────────────────────────────────────
    llm_result = await _llm_scout_summarize(state, all_hits)

    if llm_result is not None:
        summary, llm_sentiment, key_events = llm_result

        # Sentiment calibration (Rev 1 — S9): compare LLM score with naive avg
        naive_avg = _naive_sentiment_avg(all_hits)
        final_sentiment = llm_sentiment
        if llm_sentiment is not None and naive_avg is not None:
            divergence = abs(llm_sentiment - naive_avg)
            if divergence > _SENTIMENT_DIVERGENCE_THRESHOLD:
                logger.warning(
                    "[Scout] sentiment_divergence: LLM=%.2f naive=%.2f (delta=%.2f > %.2f) — using naive",
                    llm_sentiment, naive_avg, divergence, _SENTIMENT_DIVERGENCE_THRESHOLD,
                )
                final_sentiment = naive_avg

        state.sentiment = SentimentContext(
            items=all_hits,
            summary=summary,
            sentiment_score=final_sentiment,
            key_events=key_events,
        )
        logger.info("[Scout] LLM summary (sentiment=%.2f, %d events)",
                     final_sentiment or 0.0, len(key_events))
    else:
        # ── Fallback: naive string concatenation ────────────────────────
        summary_parts = [
            f"[{h['source']}] {h['text'][:120]}" for h in all_hits if h.get("text")
        ]
        summary = "\n".join(summary_parts) if summary_parts else "No context available."

        state.sentiment = SentimentContext(
            items=all_hits,
            summary=summary,
            sentiment_score=_naive_sentiment_avg(all_hits),
        )
        logger.info("[Scout] fallback concat summary (%d docs)", len(all_hits))

    return state
