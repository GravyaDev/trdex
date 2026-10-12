"""Risk management API routes — stop-loss monitor, kill switch, per-symbol config."""

from __future__ import annotations

import logging

from pydantic import BaseModel

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from trdex.api.app import verify_api_key

_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/v1/risk", tags=["risk"])

_monitor = None


def set_monitor(monitor) -> None:  # type: ignore[no-untyped-def]
    global _monitor
    _monitor = monitor


@router.get("/status")
async def risk_status(_key: str = Depends(verify_api_key)) -> dict:
    """Return stop-loss monitor status and kill switch state."""
    if _monitor is None:
        from trdex.risk.stop_loss import get_kill_switch
        return {"running": False, "kill_switch": get_kill_switch().status}
    return _monitor.status


@router.get("/events")
async def risk_events(_key: str = Depends(verify_api_key)) -> dict:
    """Return recent stop-loss events (last 50)."""
    if _monitor is None:
        return {"events": []}
    return {"events": _monitor.recent_events}


@router.post("/check")
@_limiter.limit("10/minute")
async def run_check_now(request: Request, _key: str = Depends(verify_api_key)) -> dict:
    """Trigger an immediate stop-loss check cycle."""
    if _monitor is None:
        raise HTTPException(status_code=503, detail="Stop-loss monitor not running.")
    events = await _monitor.check_now()
    return {"events_fired": len(events), "events": _monitor.recent_events[-len(events):]}


@router.post("/kill-switch/activate")
@_limiter.limit("5/minute")
async def activate_kill_switch(
    request: Request,
    reason: str = "Manual override via API",
    _key: str = Depends(verify_api_key),
) -> dict:
    """Manually activate the kill switch — halts all future order approvals."""
    from trdex.risk.stop_loss import get_kill_switch
    await get_kill_switch().activate_async(reason)
    return get_kill_switch().status


@router.post("/kill-switch/reset")
@_limiter.limit("5/minute")
async def reset_kill_switch(request: Request, _key: str = Depends(verify_api_key)) -> dict:
    """Reset the kill switch — re-enables trading. Use with caution."""
    from trdex.risk.stop_loss import get_kill_switch
    await get_kill_switch().reset_async()
    return get_kill_switch().status


# ── Per-symbol risk config ─────────────────────────────────────────────────

_session_factory = None


def set_session_factory(sf) -> None:  # type: ignore[no-untyped-def]
    global _session_factory
    _session_factory = sf


class ThresholdsBody(BaseModel):
    position_sl_pct: float | None = None
    position_tp_pct: float | None = None
    trailing_stop_pct: float | None = None
    daily_drawdown_pct: float | None = None
    open_positions_loss_pct: float | None = None
    max_drawdown_pct: float | None = None


@router.put("/thresholds")
async def update_thresholds(
    body: ThresholdsBody,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Update global risk thresholds at runtime (no restart needed).

    Only non-null fields are updated. NULL fields keep their current value.
    Not persisted — reverts to env var on container restart.
    """
    if _monitor is None:
        raise HTTPException(status_code=503, detail="Stop-loss monitor not running.")
    if body.position_sl_pct is not None:
        if not 0.001 <= body.position_sl_pct <= 0.50:
            raise HTTPException(status_code=400, detail="position_sl_pct must be 0.1%-50%")
        _monitor._sl_pct = body.position_sl_pct
    if body.position_tp_pct is not None:
        if not 0.01 <= body.position_tp_pct <= 1.0:
            raise HTTPException(status_code=400, detail="position_tp_pct must be 1%-100%")
        _monitor._tp_pct = body.position_tp_pct
    if body.trailing_stop_pct is not None:
        if not 0.005 <= body.trailing_stop_pct <= 0.50:
            raise HTTPException(status_code=400, detail="trailing_stop_pct must be 0.5%-50%")
        _monitor._trailing_pct = body.trailing_stop_pct
    if body.daily_drawdown_pct is not None:
        if not 0.01 <= body.daily_drawdown_pct <= 0.50:
            raise HTTPException(status_code=400, detail="daily_drawdown_pct must be 1%-50%")
        _monitor._daily_dd_pct = body.daily_drawdown_pct
    if body.open_positions_loss_pct is not None:
        if not 0.01 <= body.open_positions_loss_pct <= 0.50:
            raise HTTPException(status_code=400, detail="open_positions_loss_pct must be 1%-50%")
        _monitor._open_loss_pct = body.open_positions_loss_pct
    if body.max_drawdown_pct is not None:
        if not 0.05 <= body.max_drawdown_pct <= 1.0:
            raise HTTPException(status_code=400, detail="max_drawdown_pct must be 5%-100%")
        _monitor._max_dd_pct = body.max_drawdown_pct
    logger.info("[Risk] thresholds updated at runtime: %s", _monitor.status.get("thresholds"))
    return _monitor.status


class SymbolConfigBody(BaseModel):
    sl_pct: float | None = None
    tp_pct: float | None = None
    trailing_pct: float | None = None
    notes: str = ""


@router.get("/symbol-config")
async def list_symbol_config(_key: str = Depends(verify_api_key)) -> dict:
    """Return all per-symbol risk threshold overrides."""
    if _session_factory is None:
        return {"configs": []}
    from trdex.storage.symbol_config_repo import SymbolConfigRepository
    async with _session_factory() as session:
        repo = SymbolConfigRepository(session)
        records = await repo.get_all()
    return {
        "configs": [
            {
                "symbol": r.symbol,
                "sl_pct": r.sl_pct,
                "tp_pct": r.tp_pct,
                "trailing_pct": r.trailing_pct,
                "notes": r.notes,
                "updated_at": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in records
        ]
    }


@router.put("/symbol-config/{symbol}")
async def upsert_symbol_config(
    symbol: str,
    body: SymbolConfigBody,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Create or update per-symbol risk thresholds. NULL values = use adaptive default."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not available.")
    from trdex.storage.symbol_config_repo import SymbolConfigRepository
    async with _session_factory() as session:
        repo = SymbolConfigRepository(session)
        record = await repo.upsert(
            symbol,
            sl_pct=body.sl_pct,
            tp_pct=body.tp_pct,
            trailing_pct=body.trailing_pct,
            notes=body.notes,
        )
    return {
        "symbol": record.symbol,
        "sl_pct": record.sl_pct,
        "tp_pct": record.tp_pct,
        "trailing_pct": record.trailing_pct,
        "notes": record.notes,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


@router.delete("/symbol-config/{symbol}")
async def delete_symbol_config(
    symbol: str,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Remove per-symbol override, reverting to adaptive CV-based defaults."""
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Database not available.")
    from trdex.storage.symbol_config_repo import SymbolConfigRepository
    async with _session_factory() as session:
        repo = SymbolConfigRepository(session)
        deleted = await repo.delete(symbol)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"No config for {symbol}")
    return {"deleted": symbol}
