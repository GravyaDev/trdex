"""Portfolio API routes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException

from trdex.api.app import verify_api_key
from trdex.api.validators import DaysParam
from trdex.portfolio.service import PortfolioService
from trdex.storage.portfolio_repo import PortfolioRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from trdex.market.manager import PriceFeedManager

router = APIRouter(prefix="/v1/portfolio", tags=["portfolio"])

_session_factory = None
_feed_manager = None


def set_service_factory(session_factory: "async_sessionmaker", feed_manager: "PriceFeedManager") -> None:
    global _session_factory, _feed_manager
    _session_factory = session_factory
    _feed_manager = feed_manager


@asynccontextmanager
async def _service() -> AsyncIterator[PortfolioService]:
    """Context manager that provides a PortfolioService with a properly scoped session."""
    if _session_factory is None or _feed_manager is None:
        raise HTTPException(status_code=503, detail="Portfolio service not initialised")
    async with _session_factory() as session:
        yield PortfolioService(PortfolioRepository(session), _feed_manager)


@router.get("")
async def snapshot(_key: str = Depends(verify_api_key)) -> dict:
    async with _service() as svc:
        portfolio = await svc.snapshot()
    return {
        "balance": str(portfolio.balance),
        "equity": str(portfolio.equity),
        "total_pnl": str(portfolio.total_pnl),
        "total_trades": portfolio.total_trades,
        "winning_trades": portfolio.winning_trades,
        "win_rate": portfolio.win_rate,
        "open_positions": len(portfolio.positions),
    }


@router.get("/positions")
async def open_positions(_key: str = Depends(verify_api_key)) -> dict:
    async with _service() as svc:
        positions = await svc.mark_to_market()
    return {
        "positions": [
            {
                "symbol": p.symbol,
                "side": p.side,
                "entry_price": str(p.entry_price),
                "current_price": str(p.current_price),
                "amount": str(p.amount),
                "unrealized_pnl": str(p.unrealized_pnl),
                "unrealized_pnl_pct": str(p.unrealized_pnl_pct),
                "opened_at": p.opened_at.isoformat(),
            }
            for p in positions
        ]
    }


@router.get("/pnl_by_source")
async def pnl_by_source(_key: str = Depends(verify_api_key)) -> dict:
    async with _service() as svc:
        return {"by_source": await svc._repo.pnl_by_source()}


@router.get("/pnl_history")
async def pnl_history(
    days: DaysParam = 30,
    _key: str = Depends(verify_api_key),
) -> dict:
    async with _service() as svc:
        return {"history": await svc._repo.pnl_history(days=days)}
