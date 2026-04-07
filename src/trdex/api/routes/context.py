"""Context/ingestion API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from trdex.api.app import verify_api_key
from trdex.api.validators import SymbolParam

router = APIRouter(prefix="/v1/context", tags=["context"])

# Injected at startup by app.py
_scheduler = None


def set_scheduler(scheduler) -> None:  # type: ignore[no-untyped-def]
    global _scheduler
    _scheduler = scheduler


class RunOnceResponse(BaseModel):
    docs_ingested: int


@router.get("/status")
async def context_status(_key: str = Depends(verify_api_key)) -> dict:
    """Return ingestion scheduler status."""
    if _scheduler is None:
        return {"running": False, "sources": [], "symbols": [], "last_run": None}
    return _scheduler.status


@router.post("/run")
async def run_ingestion_now(_key: str = Depends(verify_api_key)) -> RunOnceResponse:
    """Trigger an immediate ingestion cycle (bypasses the interval timer)."""
    if _scheduler is None or not _scheduler._sources:
        raise HTTPException(status_code=503, detail="No news sources configured.")
    total = await _scheduler.run_once()
    return RunOnceResponse(docs_ingested=total)


@router.post("/symbols")
async def add_symbol(symbol: SymbolParam, _key: str = Depends(verify_api_key)) -> dict:
    """Add a symbol to the ingestion watchlist."""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not running.")
    symbols = list(_scheduler._symbols)
    if symbol not in symbols:
        symbols.append(symbol)
        _scheduler.set_symbols(symbols)
    return {"symbols": _scheduler._symbols}


@router.delete("/symbols/{symbol:path}")
async def remove_symbol(symbol: str, _key: str = Depends(verify_api_key)) -> dict:
    """Remove a symbol from the ingestion watchlist."""
    if _scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not running.")
    symbols = [s for s in _scheduler._symbols if s != symbol]
    _scheduler.set_symbols(symbols)
    return {"symbols": _scheduler._symbols}
