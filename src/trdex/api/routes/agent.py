"""Agent execution API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import Integer, select

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


# ── Agent LLM config CRUD ───────────────────────────────────────────────


class AgentConfigResponse(BaseModel):
    agent_name: str
    provider: str
    model_id: str
    temperature: float
    max_tokens: int
    top_p: float
    system_prompt: str
    llm_enabled: bool


class AgentConfigUpdateBody(BaseModel):
    provider: str | None = None
    model_id: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    top_p: float | None = None
    system_prompt: str | None = None
    llm_enabled: bool | None = None


@router.get("/config")
async def get_all_agent_configs(
    _key: str = Depends(verify_api_key),
) -> list[AgentConfigResponse]:
    """Return LLM configuration for all agents."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Not initialised.")

    from trdex.storage.agent_config_repo import AgentConfigRepository

    async with _session_factory() as session:
        repo = AgentConfigRepository(session)
        rows = await repo.get_all()

    return [
        AgentConfigResponse(
            agent_name=r.agent_name,
            provider=r.provider,
            model_id=r.model_id,
            temperature=float(r.temperature),
            max_tokens=r.max_tokens,
            top_p=float(r.top_p),
            system_prompt=r.system_prompt,
            llm_enabled=r.llm_enabled,
        )
        for r in rows
    ]


@router.get("/config/{agent_name}")
async def get_agent_config(
    agent_name: str,
    _key: str = Depends(verify_api_key),
) -> AgentConfigResponse:
    """Return LLM configuration for a single agent."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Not initialised.")

    from trdex.storage.agent_config_repo import AgentConfigRepository

    async with _session_factory() as session:
        repo = AgentConfigRepository(session)
        r = await repo.get(agent_name)
    if r is None:
        raise HTTPException(status_code=404, detail=f"No config for agent '{agent_name}'")
    return AgentConfigResponse(
        agent_name=r.agent_name,
        provider=r.provider,
        model_id=r.model_id,
        temperature=float(r.temperature),
        max_tokens=r.max_tokens,
        top_p=float(r.top_p),
        system_prompt=r.system_prompt,
        llm_enabled=r.llm_enabled,
    )


@router.put("/config/{agent_name}")
async def update_agent_config(
    agent_name: str,
    body: AgentConfigUpdateBody,
    _key: str = Depends(verify_api_key),
) -> AgentConfigResponse:
    """Update LLM configuration for an agent. Only provided fields are changed."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Not initialised.")

    # Validate prompt contains required keywords if being updated
    if body.system_prompt is not None and body.system_prompt.strip():
        prompt_lower = body.system_prompt.lower()
        if "confidence" not in prompt_lower or "hold" not in prompt_lower:
            raise HTTPException(
                status_code=400,
                detail="System prompt must contain 'confidence' and 'HOLD' keywords (safety requirement).",
            )

    from trdex.storage.agent_config_repo import AgentConfigRepository

    async with _session_factory() as session:
        repo = AgentConfigRepository(session)
        r = await repo.update_config(
            agent_name,
            provider=body.provider,
            model_id=body.model_id,
            temperature=body.temperature,
            max_tokens=body.max_tokens,
            top_p=body.top_p,
            system_prompt=body.system_prompt,
            llm_enabled=body.llm_enabled,
        )
    if r is None:
        raise HTTPException(status_code=404, detail=f"No config for agent '{agent_name}'")
    return AgentConfigResponse(
        agent_name=r.agent_name,
        provider=r.provider,
        model_id=r.model_id,
        temperature=float(r.temperature),
        max_tokens=r.max_tokens,
        top_p=float(r.top_p),
        system_prompt=r.system_prompt,
        llm_enabled=r.llm_enabled,
    )


class LLMUsageSummary(BaseModel):
    period: str
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_cost_usd: float
    fallback_count: int
    by_agent: dict[str, dict]


@router.get("/llm-usage")
async def get_llm_usage(
    period: str = "today",
    _key: str = Depends(verify_api_key),
) -> LLMUsageSummary:
    """Return LLM usage stats for today or this month."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Not initialised.")

    from datetime import datetime, timezone
    from sqlalchemy import func

    from trdex.storage.agent_config_models import AgentLLMUsageRecord

    now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
    if period == "month":
        since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        since = now.replace(hour=0, minute=0, second=0, microsecond=0)

    async with _session_factory() as session:
        q = (
            select(
                AgentLLMUsageRecord.agent_name,
                func.count().label("calls"),
                func.sum(AgentLLMUsageRecord.input_tokens).label("input_tokens"),
                func.sum(AgentLLMUsageRecord.output_tokens).label("output_tokens"),
                func.sum(AgentLLMUsageRecord.cost_usd).label("cost_usd"),
                func.sum(func.cast(AgentLLMUsageRecord.fallback_used, Integer)).label("fallbacks"),
            )
            .where(AgentLLMUsageRecord.created_at >= since)
            .group_by(AgentLLMUsageRecord.agent_name)
        )
        result = await session.execute(q)
        rows = result.all()

    by_agent: dict[str, dict] = {}
    total_calls = 0
    total_in = 0
    total_out = 0
    total_cost = 0.0
    total_fb = 0
    for r in rows:
        by_agent[r.agent_name] = {
            "calls": r.calls,
            "input_tokens": int(r.input_tokens or 0),
            "output_tokens": int(r.output_tokens or 0),
            "cost_usd": float(r.cost_usd or 0),
            "fallbacks": int(r.fallbacks or 0),
        }
        total_calls += r.calls
        total_in += int(r.input_tokens or 0)
        total_out += int(r.output_tokens or 0)
        total_cost += float(r.cost_usd or 0)
        total_fb += int(r.fallbacks or 0)

    return LLMUsageSummary(
        period=period,
        total_calls=total_calls,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        total_cost_usd=total_cost,
        fallback_count=total_fb,
        by_agent=by_agent,
    )
