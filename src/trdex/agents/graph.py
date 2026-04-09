"""LangGraph state machine: Scout → Analyst → Risk → Executor."""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from datetime import datetime, timezone

from langgraph.graph import END, StateGraph

from trdex.agents.analyst import analyst_node
from trdex.agents.executor import executor_node
from trdex.agents.risk import risk_node
from trdex.agents.scout import scout_node
from trdex.agents.state import (
    AgentState,
    AnalysisResult,
    MarketSnapshot,
    OrderResult,
    PortfolioContext,
    RiskDecision,
    SentimentContext,
)

logger = logging.getLogger(__name__)


def _build_graph() -> StateGraph:
    graph = StateGraph(AgentState)

    graph.add_node("scout", scout_node)
    graph.add_node("analyst", analyst_node)
    graph.add_node("risk", risk_node)
    graph.add_node("executor", executor_node)

    graph.set_entry_point("scout")
    graph.add_edge("scout", "analyst")
    graph.add_edge("analyst", "risk")
    graph.add_edge("risk", "executor")
    graph.add_edge("executor", END)

    return graph


# Compiled graph — lazy init on first call, protected against concurrent coroutines
_compiled = None
_compiled_lock = asyncio.Lock()


async def _get_compiled():
    global _compiled
    if _compiled is None:
        async with _compiled_lock:
            if _compiled is None:  # double-checked after acquiring lock
                _compiled = _build_graph().compile()
    return _compiled


def _dict_to_state(d: dict) -> AgentState:
    """Reconstruct AgentState from the dict that LangGraph returns."""

    def _coerce(cls, val):
        if val is None or isinstance(val, cls):
            return val
        if isinstance(val, dict):
            return cls(**{k: v for k, v in val.items() if k in {f.name for f in dataclasses.fields(cls)}})
        return val

    return AgentState(
        symbol=d.get("symbol", ""),
        run_id=d.get("run_id", ""),
        market=_coerce(MarketSnapshot, d.get("market")),
        sentiment=_coerce(SentimentContext, d.get("sentiment")) or SentimentContext(),
        analysis=_coerce(AnalysisResult, d.get("analysis")) or AnalysisResult(),
        risk=_coerce(RiskDecision, d.get("risk")) or RiskDecision(),
        order=_coerce(OrderResult, d.get("order")) or OrderResult(),
        portfolio=_coerce(PortfolioContext, d.get("portfolio")) or PortfolioContext(),
        session_factory=d.get("session_factory"),
        gateway=d.get("gateway"),
        memory_loader=d.get("memory_loader"),
        llm_caller=d.get("llm_caller"),
        memory_snapshot_text=d.get("memory_snapshot_text", ""),
        memory_snapshots=d.get("memory_snapshots") or {},
        error=d.get("error"),
        completed_at=d.get("completed_at"),
    )


async def run_agent_cycle(
    symbol: str,
    market_snapshot: MarketSnapshot | None = None,
    portfolio_context: PortfolioContext | None = None,
    session_factory=None,
    gateway=None,
    memory_loader=None,
    llm_caller=None,
) -> AgentState:
    """Run one full Scout → Analyst → Risk → Executor cycle.

    Args:
        symbol: Trading pair, e.g. "BTC/USDT"
        market_snapshot: Pre-fetched MarketSnapshot (injected by the feed layer).
        portfolio_context: Live portfolio state for risk gate decisions.
        llm_caller: LLMCaller instance for structured LLM calls (optional).

    Returns:
        Final AgentState with all agent outputs populated.
    """
    initial_state = AgentState(
        symbol=symbol,
        run_id=str(uuid.uuid4()),
        market=market_snapshot,
        portfolio=portfolio_context or PortfolioContext(),
        session_factory=session_factory,
        gateway=gateway,
        memory_loader=memory_loader,
        llm_caller=llm_caller,
    )
    logger.info("[Graph] starting cycle run_id=%s symbol=%s", initial_state.run_id, symbol)

    raw = await (await _get_compiled()).ainvoke(initial_state)
    final_state = _dict_to_state(raw) if isinstance(raw, dict) else raw
    final_state.completed_at = datetime.now(tz=timezone.utc)

    logger.info(
        "[Graph] cycle complete run_id=%s intent=%s order=%s",
        final_state.run_id,
        final_state.analysis.intent.value,
        final_state.order.status,
    )
    return final_state
