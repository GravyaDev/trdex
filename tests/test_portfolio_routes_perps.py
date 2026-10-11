"""Manual opens follow the venue rules before any order is sent."""

from __future__ import annotations

from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from trdex.api.routes import portfolio as routes


class _Cfg:
    def __init__(self, **t):
        self.t = t

    def get(self, category, key, default=""):
        return str(self.t.get(key, default)) if category == "thresholds" else default


@pytest.fixture
def wired(monkeypatch):
    gw = MagicMock()
    gw.place = AsyncMock(
        return_value=SimpleNamespace(
            status="filled",
            filled_price=100.0,
            filled_qty=5.0,
            fee=0.5,
            message="sim",
        )
    )
    feeds = MagicMock(get_ticker=AsyncMock(return_value=SimpleNamespace(price=100.0)))
    open_positions: list = []
    repo = MagicMock(get_open_positions=AsyncMock(side_effect=lambda: open_positions))
    monkeypatch.setattr(routes, "PortfolioRepository", MagicMock(return_value=repo))

    @asynccontextmanager
    async def factory():
        yield MagicMock()

    recorded = SimpleNamespace(
        id=1, symbol="BTC/USDT", side="SELL", amount=Decimal("5"), entry_price=Decimal("100")
    )
    svc = MagicMock(record_open_fill=AsyncMock(return_value=recorded))

    @asynccontextmanager
    async def service():
        yield svc

    monkeypatch.setattr(routes, "_service", service)
    routes.set_service_factory(factory, feeds, gw)
    yield SimpleNamespace(gw=gw, svc=svc, open=open_positions, monkeypatch=monkeypatch)
    routes.set_service_factory(None, None, None)


def _venue(w, **t):
    w.monkeypatch.setattr("trdex.services.runtime_config.get_config_service", lambda: _Cfg(**t))


@pytest.mark.asyncio
async def test_manual_short_on_perps_carries_its_leverage(wired):
    _venue(wired)
    req = routes.ManualOpenRequest(
        symbol="BTC/USDT", side="SELL", amount=Decimal("500"), leverage=2
    )
    await routes.manual_open(req, _key="k")
    assert wired.gw.place.await_args.kwargs["leverage"] == 2
    assert wired.svc.record_open_fill.await_args.kwargs["leverage"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("venue", "side", "lev", "code"),
    [("spot", "SELL", 1, 422), ("spot", "BUY", 2, 422), ("usdm", "BUY", 5, 422)],
)
async def test_manual_open_refused_before_any_order(wired, venue, side, lev, code):
    _venue(wired, execution_venue=venue)
    req = routes.ManualOpenRequest(
        symbol="BTC/USDT", side=side, amount=Decimal("500"), leverage=lev
    )
    with pytest.raises(HTTPException) as exc:
        await routes.manual_open(req, _key="k")
    assert exc.value.status_code == code
    wired.gw.place.assert_not_awaited()


@pytest.mark.asyncio
async def test_manual_open_against_the_opposite_side_is_refused(wired):
    _venue(wired)
    wired.open.append(SimpleNamespace(symbol="BTC/USDT", side="BUY"))
    req = routes.ManualOpenRequest(symbol="BTC/USDT", side="SELL", amount=Decimal("500"))
    with pytest.raises(HTTPException) as exc:
        await routes.manual_open(req, _key="k")
    assert exc.value.status_code == 409
    wired.gw.place.assert_not_awaited()


@pytest.mark.asyncio
async def test_positions_show_leverage_margin_and_liquidation_price(wired):
    from datetime import datetime

    _venue(wired)
    opened = datetime(2026, 10, 11, 9, 0)
    rec = SimpleNamespace(
        id=7,
        symbol="BTC/USDT",
        side="SELL",
        opened_at=opened,
        source="agent",
        leverage=3.0,
        budget=Decimal("600"),
        entry_price=Decimal("100"),
    )
    pos = SimpleNamespace(
        symbol="BTC/USDT",
        side="short",
        entry_price=Decimal("100"),
        current_price=Decimal("90"),
        amount=Decimal("6"),
        unrealized_pnl=Decimal("60"),
        unrealized_pnl_pct=Decimal("0.1"),
        opened_at=opened,
    )
    wired.svc.mark_to_market = AsyncMock(return_value=[pos])
    wired.svc._repo = MagicMock(get_open_positions=AsyncMock(return_value=[rec]))
    (row,) = (await routes.open_positions(_key="k"))["positions"]
    assert row["leverage"] == 3.0 and Decimal(row["margin"]) == Decimal("200")
    assert float(row["liquidation_price"]) == pytest.approx(100 * (1 + 1 / 3 - 0.005))
