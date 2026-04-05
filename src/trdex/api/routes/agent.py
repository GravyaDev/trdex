"""Agent execution API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from trdex.api.app import verify_api_key

router = APIRouter(prefix="/v1/agent", tags=["agent"])

# Injected at startup by app.py
_session_factory = None
_feed_manager = None


def set_agent_factory(session_factory, feed_manager) -> None:  # type: ignore[no-untyped-def]
    global _session_factory, _feed_manager
    _session_factory = session_factory
    _feed_manager = feed_manager


class AgentRunResponse(BaseModel):
    run_id: str
    symbol: str
    signal: str
    confidence: float
    reasoning: str
    indicators: dict
    risk_approved: bool
    risk_reason: str
    order_status: str
    filled_price: float | None
    error: str | None


class AgentRunSummary(BaseModel):
    run_id: str
    symbol: str
    ran_at: str
    signal: str
    confidence: float
    risk_approved: bool
    order_status: str


@router.post("/run")
async def run_agent(
    symbol: str,
    timeframe: str = "1h",
    candle_limit: int = 100,
    _key: str = Depends(verify_api_key),
) -> AgentRunResponse:
    """Trigger a full agent cycle for the given symbol.

    Fetches OHLCV data from DB (falls back to live feed), queries Qdrant for
    news context, runs Scout→Analyst→Risk→Executor, and persists the result.
    """
    if _session_factory is None or _feed_manager is None:
        raise HTTPException(status_code=503, detail="Agent runner not initialised.")

    from trdex.agents.runner import AgentRunner

    async with _session_factory() as session:
        runner = AgentRunner(session, _feed_manager)
        state = await runner.run(symbol, timeframe=timeframe, candle_limit=candle_limit)

    return AgentRunResponse(
        run_id=state.run_id,
        symbol=state.symbol,
        signal=state.analysis.signal,
        confidence=state.analysis.confidence,
        reasoning=state.analysis.reasoning,
        indicators=state.analysis.indicators,
        risk_approved=state.risk.approved,
        risk_reason=state.risk.reason,
        order_status=state.order.status,
        filled_price=state.order.filled_price,
        error=state.error,
    )


@router.get("/history")
async def agent_history(
    symbol: str | None = None,
    limit: int = 50,
    _key: str = Depends(verify_api_key),
) -> list[AgentRunSummary]:
    """Return recent agent run history, optionally filtered by symbol."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Agent runner not initialised.")

    from trdex.storage.agent_run_models import AgentRunRecord

    async with _session_factory() as session:
        q = select(AgentRunRecord).order_by(AgentRunRecord.ran_at.desc()).limit(limit)
        if symbol:
            q = q.where(AgentRunRecord.symbol == symbol)
        result = await session.execute(q)
        records = list(result.scalars().all())

    return [
        AgentRunSummary(
            run_id=str(r.run_id),
            symbol=r.symbol,
            ran_at=r.ran_at.isoformat(),
            signal=r.signal,
            confidence=float(r.confidence),
            risk_approved=r.risk_approved,
            order_status=r.order_status,
        )
        for r in records
    ]
