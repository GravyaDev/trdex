"""Portfolio API routes."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from trdex.api.app import verify_api_key
from trdex.api.validators import DaysParam
from trdex.portfolio.service import PortfolioService
from trdex.risk.leverage import liquidation_price
from trdex.storage.portfolio_repo import PortfolioRepository

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker
    from trdex.execution.gateway import ExecutionGateway
    from trdex.market.manager import PriceFeedManager

router = APIRouter(prefix="/v1/portfolio", tags=["portfolio"])

_session_factory = None
_feed_manager = None
_gateway = None


def set_service_factory(
    session_factory: "async_sessionmaker",
    feed_manager: "PriceFeedManager",
    gateway: "ExecutionGateway | None" = None,
) -> None:
    global _session_factory, _feed_manager, _gateway
    _session_factory = session_factory
    _feed_manager = feed_manager
    _gateway = gateway


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
    # Load raw records too so we can surface position_id alongside the
    # mark-to-market view. The two queries are issued against the same
    # session and the open-positions set is stable enough within a dashboard
    # refresh that a join by (symbol, side, opened_at) is safe.
    if _session_factory is None:
        raise HTTPException(status_code=503, detail="Portfolio service not initialised")
    async with _service() as svc:
        positions = await svc.mark_to_market()
        raw_records = await svc._repo.get_open_positions()
    # Join by (symbol, side, opened_at). Carry both `id` and `source` so
    # the dashboard can render the provenance chip ("telegram", "agent",
    # "manual"). Source lives on PositionRecord; mark_to_market drops it
    # because Position (pydantic) does not model it — but the tuple key
    # is stable enough for a cheap lookup.
    meta_by_key = {
        (r.symbol, r.side, r.opened_at): (r.id, r.source) for r in raw_records
    }
    rec_by_id = {r.id: r for r in raw_records}
    mmr = _maintenance_margin_rate()

    def _perp_fields(pos_id: int | None) -> dict[str, Any]:
        r = rec_by_id.get(pos_id) if pos_id is not None else None
        lev = float(getattr(r, "leverage", 1) or 1) if r is not None else 1.0
        if r is None:
            return {"leverage": None, "margin": None, "liquidation_price": None}
        liq = (
            liquidation_price(float(r.entry_price), str(r.side), lev, mmr)
            if lev > 1 and mmr is not None
            else None
        )
        return {
            "leverage": lev,
            "margin": str(Decimal(str(r.budget)) / Decimal(str(lev))),
            "liquidation_price": None if liq is None else f"{liq:.8g}",
        }

    return {
        "positions": [
            {
                "id": meta_by_key.get(
                    (p.symbol, "BUY" if p.side == "long" else "SELL", p.opened_at), (None, "")
                )[0],
                "source": meta_by_key.get(
                    (p.symbol, "BUY" if p.side == "long" else "SELL", p.opened_at), (None, "")
                )[1],
                "symbol": p.symbol,
                "side": p.side,
                "entry_price": str(p.entry_price),
                "current_price": str(p.current_price),
                "amount": str(p.amount),
                "unrealized_pnl": str(p.unrealized_pnl),
                "unrealized_pnl_pct": str(p.unrealized_pnl_pct),
                "opened_at": p.opened_at.isoformat(),
                **_perp_fields(
                    meta_by_key.get(
                        (p.symbol, "BUY" if p.side == "long" else "SELL", p.opened_at), (None, "")
                    )[0]
                ),
            }
            for p in positions
        ]
    }


def _maintenance_margin_rate() -> float | None:
    from trdex.risk.leverage import derivatives_config
    from trdex.services.runtime_config import get_config_service

    try:
        return derivatives_config(get_config_service()).mmr
    except Exception:
        return None


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


class ManualOpenRequest(BaseModel):
    symbol: str = Field(..., min_length=3, max_length=20)
    side: str = Field(..., pattern="^(BUY|SELL)$")
    amount: Decimal = Field(..., gt=0, description="Quote amount in USDT (e.g. 500 = $500)")
    leverage: int = Field(1, ge=1, description="Isolated leverage (perps venue only)")


@router.post("/open")
async def manual_open(
    req: ManualOpenRequest,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Manually open a position via the execution gateway.

    The amount is in quote currency (USDT). We fetch the live ticker and
    compute qty = amount / price, then route through the gateway so fees,
    slippage, lot-size truncation, and the kill-switch all apply.
    """
    if _gateway is None or _feed_manager is None or _session_factory is None:
        raise HTTPException(503, "Portfolio service not initialised")

    # 0. Venue rules, before any order: shorts and leverage only on perps,
    # never the opposite side of an open position on the same symbol.
    from trdex.risk.leverage import derivatives_config
    from trdex.services.runtime_config import get_config_service

    try:
        venue = derivatives_config(get_config_service())
    except ValueError as exc:
        raise HTTPException(503, f"Invalid venue settings: {exc}") from exc
    if not venue.perps and (req.side == "SELL" or req.leverage > 1):
        raise HTTPException(
            422, "Shorts and leverage need the perpetual futures venue (execution_venue=usdm)"
        )
    if req.leverage > venue.max_leverage:
        raise HTTPException(422, f"Leverage {req.leverage}x above max_leverage {venue.max_leverage}")
    async with _session_factory() as session:
        open_now = await PortfolioRepository(session).get_open_positions()
    if any(p.symbol == req.symbol and str(p.side) != req.side for p in open_now):
        raise HTTPException(409, f"The opposite side is already open on {req.symbol}")

    # 1. Fetch current price
    try:
        ticker = await _feed_manager.get_ticker(req.symbol, source="binance")
        price = Decimal(str(ticker.price))
    except Exception as exc:
        raise HTTPException(502, f"Price fetch failed for {req.symbol}: {exc}") from exc

    if price <= 0:
        raise HTTPException(502, f"Invalid price for {req.symbol}: {price}")

    qty = req.amount / price

    # 2. Route order via gateway (applies fees, slippage, kill-switch)
    result = await _gateway.place(
        symbol=req.symbol,
        direction=req.side,  # type: ignore[arg-type]
        qty=float(qty),
        price=float(price),
        idempotency_key=None,
        leverage=req.leverage,
    )
    if result.status != "filled":
        raise HTTPException(422, f"Order rejected: {result.message}")

    fill_price = Decimal(str(result.filled_price)) if result.filled_price else price
    fill_qty = Decimal(str(result.filled_qty)) if result.filled_qty else qty
    fee = Decimal(str(result.fee)) if result.fee else Decimal("0")

    # 3. Persist the open via PortfolioService
    async with _service() as svc:
        record = await svc.record_open_fill(
            symbol=req.symbol,
            side=req.side,
            amount=fill_qty,
            entry_price=fill_price,
            budget=req.amount,
            fee=fee,
            source="manual",
            signal_id=None,
            leverage=req.leverage,
        )
    if record is None:
        raise HTTPException(422, "Open rejected by portfolio service (unknown side)")

    return {
        "position_id": record.id,
        "symbol": record.symbol,
        "side": record.side,
        "amount": str(record.amount),
        "entry_price": str(record.entry_price),
        "fee": str(fee),
        "message": result.message,
    }


@router.post("/close/{position_id}")
async def manual_close(
    position_id: int,
    _key: str = Depends(verify_api_key),
) -> dict:
    """Manually close an open position by id."""
    if _gateway is None or _feed_manager is None or _session_factory is None:
        raise HTTPException(503, "Portfolio service not initialised")

    # 1. Load the position
    async with _session_factory() as session:
        repo = PortfolioRepository(session)
        positions = await repo.get_open_positions()
        pos = next((p for p in positions if p.id == position_id), None)
    if pos is None:
        raise HTTPException(404, f"No open position with id={position_id}")

    # 2. Fetch current Binance price (source of truth — avoid cross-feed mismatch)
    try:
        ticker = await _feed_manager.get_ticker(pos.symbol, source="binance")
        price = Decimal(str(ticker.price))
    except Exception as exc:
        raise HTTPException(502, f"Price fetch failed for {pos.symbol}: {exc}") from exc

    # 3. Route close order via gateway — opposite side
    close_side = "SELL" if pos.side == "BUY" else "BUY"
    result = await _gateway.place(
        symbol=pos.symbol,
        direction=close_side,  # type: ignore[arg-type]
        qty=float(pos.amount),
        price=float(price),
        idempotency_key=f"manual_close:{pos.id}",
        reduce_only=True,  # closing must stay possible with the kill switch active
    )
    if result.status != "filled":
        raise HTTPException(422, f"Close order rejected: {result.message}")

    fill_price = Decimal(str(result.filled_price)) if result.filled_price else price
    fee = Decimal(str(result.fee)) if result.fee else Decimal("0")

    # 4. Persist the close — use fresh session/service for atomic record_close_fill
    async with _service() as svc:
        updated, balance_row = await svc.record_close_fill(
            position=pos,
            exit_price=fill_price,
            fee=fee,
            closed_by="manual",
        )

    return {
        "position_id": updated.id,
        "symbol": updated.symbol,
        "exit_price": str(fill_price),
        "fee": str(fee),
        "status": updated.status,
        "new_balance": str(balance_row.balance_after),
        "pnl": str(balance_row.amount),
        "message": result.message,
    }
