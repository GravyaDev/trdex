"""Risk management API routes — stop-loss monitor and kill switch."""

from __future__ import annotations

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
