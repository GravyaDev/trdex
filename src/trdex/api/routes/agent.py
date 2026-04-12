"""Agent execution API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import select

from trdex.api.app import verify_api_key
from trdex.api.validators import (
    CandleLimitParam,
    LimitParam,
    SymbolParam,
    SymbolParamOptional,
    TimeframeParam,
)

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/v1/agent", tags=["agent"])

# Injected at startup by app.py
_session_factory = None
_feed_manager = None
_gateway = None


def set_agent_factory(session_factory, feed_manager, gateway=None) -> None:  # type: ignore[no-untyped-def]
    global _session_factory, _feed_manager, _gateway
    _session_factory = session_factory
    _feed_manager = feed_manager
    _gateway = gateway


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
    risk_reason: str
    order_status: str


@router.post("/run")
@_limiter.limit("10/minute")
async def run_agent(
    request: Request,
    symbol: SymbolParam,
    timeframe: TimeframeParam = "1h",
    candle_limit: CandleLimitParam = 100,
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
        runner = AgentRunner(session, _feed_manager, session_factory=_session_factory)
        state = await runner.run(symbol, timeframe=timeframe, candle_limit=candle_limit)

    return AgentRunResponse(
        run_id=state.run_id,
        symbol=state.symbol,
        signal=state.analysis.intent.value,  # historical API field name, now Intent
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
    symbol: SymbolParamOptional = None,
    limit: LimitParam = 50,
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
            risk_reason=r.risk_reason or "",
            order_status=r.order_status,
        )
        for r in records
    ]


# ── Scheduler symbols management ──────────────────────────────────────────


class SchedulerSymbolsBody(BaseModel):
    symbols: list[str]


@router.get("/scheduler/symbols")
async def get_scheduler_symbols(_key: str = Depends(verify_api_key)) -> dict:
    """Return the current scheduler symbol list."""
    from trdex.agents.scheduler import get_runtime_symbols
    symbols = get_runtime_symbols() or []
    # Rate limit budget estimate (Binance 120 rpm)
    rpm_agent = len(symbols) * 2 / 5  # 2 calls per symbol per 5-min tick
    rpm_stoploss = len(symbols) * 2 * 2  # 2 calls per symbol per 30s tick (worst case all positions open)
    rpm_total = rpm_agent + rpm_stoploss
    return {
        "symbols": symbols,
        "count": len(symbols),
        "rate_limit_estimate": {
            "agent_rpm": round(rpm_agent, 1),
            "stoploss_rpm_max": round(rpm_stoploss, 1),
            "total_rpm_max": round(rpm_total, 1),
            "binance_budget_rpm": 120,
            "utilization_pct": round(rpm_total / 120 * 100, 1),
        },
    }


@router.put("/scheduler/symbols")
async def update_scheduler_symbols(
    body: SchedulerSymbolsBody,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Update the scheduler symbol list at runtime (no restart needed).

    Not persisted — reverts to env var on container restart.
    For permanent changes, update TRDEX_AGENT_SCHEDULER_SYMBOLS in Coolify.
    """
    from trdex.agents.scheduler import set_runtime_symbols
    cleaned = [s.strip().upper() for s in body.symbols if s.strip()]
    if not cleaned:
        raise HTTPException(status_code=400, detail="At least one symbol required")
    if len(cleaned) > 30:
        raise HTTPException(status_code=400, detail="Max 30 symbols (rate limit safety)")
    set_runtime_symbols(cleaned)
    # Re-fetch to return the rate limit estimate
    return await get_scheduler_symbols(_key)


# ── Price feed selection for aggregation ───────────────────────────────


class FeedSelectionBody(BaseModel):
    feeds: list[str]


@router.get("/feeds")
async def get_feed_selection(_key: str = Depends(verify_api_key)) -> dict:
    """Return available feeds and which are selected for price aggregation."""
    from trdex.market.manager import get_selected_feeds
    if _feed_manager is None:
        return {"available": [], "selected": []}
    available = list(_feed_manager.feeds.keys())
    selected = get_selected_feeds() or available
    return {"available": available, "selected": selected}


@router.put("/feeds")
async def update_feed_selection(
    body: FeedSelectionBody,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Update which feeds are used for aggregated price queries.

    Only selected feeds are queried in parallel when the agent fetches
    the current price. If 1 feed selected → single price. If 2+ →
    median with outlier filtering. Not persisted — reverts on restart.
    """
    from trdex.market.manager import set_selected_feeds
    if _feed_manager is None:
        raise HTTPException(status_code=503, detail="Feed manager not available.")
    available = set(_feed_manager.feeds.keys())
    valid = [f for f in body.feeds if f in available]
    if not valid:
        raise HTTPException(status_code=400, detail=f"No valid feeds. Available: {sorted(available)}")
    set_selected_feeds(valid)
    return await get_feed_selection(_key)
