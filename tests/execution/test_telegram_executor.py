"""TelegramSignalExecutor integration-lite tests.

Mocks gateway + feed + repos at the seam. Asserts:
- happy path writes a position with source='telegram', signal_id set,
  stop_loss_pct and take_profit_pct computed from signal prices.
- gate failure returns early without calling gateway.place.
- SymbolNotRoutable short-circuits with the router reason.
- gateway failure logs and returns — no exception leaks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from trdex.execution.telegram_executor import TelegramSignalExecutor
from trdex.execution.telegram_gates import GateConfig
from trdex.telegram.parser import TelegramSignal


# ── Minimal fakes ──────────────────────────────────────────────────────

@dataclass
class FakeOrderResult:
    status: str = "filled"
    filled_price: float = 90000.0
    filled_qty: float = 0.00111
    fee: float = 0.0
    order_id: str = "fake-order-1"
    message: str = "Simulated fill: BUY BTC/USDT"


class FakeGateway:
    def __init__(self, result: FakeOrderResult | None = None, raises: Exception | None = None) -> None:
        self._result = result or FakeOrderResult()
        self._raises = raises
        self.calls: list[dict] = []

    async def place(
        self, *, symbol: str, direction: str, qty: float, price: float, idempotency_key: str | None = None
    ) -> FakeOrderResult:
        self.calls.append({"symbol": symbol, "direction": direction, "qty": qty, "price": price, "key": idempotency_key})
        if self._raises:
            raise self._raises
        return self._result


class FakeFeed:
    name = "fake-feed"

    def __init__(self, price: float = 90000.0) -> None:
        self._price = price

    async def get_current_price(self, symbol: str) -> float:
        return self._price


@dataclass
class FakePosition:
    id: int = 1
    symbol: str = "BTC/USDT"
    side: str = "BUY"
    status: str = "open"
    source: str = "telegram"
    signal_id: str | None = None
    stop_loss_pct: float | None = None
    take_profit_pct: float | None = None


class FakePortfolioService:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self._next_id = 1

    async def record_open_fill(self, **kwargs: Any) -> FakePosition:
        self.calls.append(dict(kwargs))
        pos = FakePosition(
            id=self._next_id,
            symbol=kwargs["symbol"],
            side=kwargs["side"],
            source=kwargs.get("source", "manual"),
            signal_id=kwargs.get("signal_id"),
            stop_loss_pct=kwargs.get("stop_loss_pct"),
            take_profit_pct=kwargs.get("take_profit_pct"),
        )
        self._next_id += 1
        return pos


class FakePortfolioRepo:
    def __init__(self, open_positions: list[FakePosition] | None = None) -> None:
        self._positions = open_positions or []

    async def get_open_by_symbol_side(self, symbol: str, side: str) -> FakePosition | None:
        for p in self._positions:
            if p.symbol == symbol and p.side == side:
                return p
        return None

    async def get_open_positions(self) -> list[FakePosition]:
        return list(self._positions)


class FakeOutcomeRepo:
    async def win_rate_by_source(self, source: str) -> tuple[int, float]:
        return (0, 0.0)


@dataclass
class FakeBalance:
    available: Decimal = Decimal("10000")


def make_signal(entry: float | None = 90000.0) -> TelegramSignal:
    return TelegramSignal(
        source="chat-12345",
        symbol="BTC/USDT",
        direction="BUY",
        entry=entry,
        targets=[94500.0],  # +5% of 90000
        stop_loss=87300.0,  # -3% of 90000
        raw_text="BUY BTCUSDT entry 90000 tp 94500 sl 87300",
    )


def _make_executor(
    *,
    gateway: FakeGateway | None = None,
    feed: FakeFeed | None = None,
    portfolio_repo: FakePortfolioRepo | None = None,
    portfolio_service: FakePortfolioService | None = None,
    outcome_repo: FakeOutcomeRepo | None = None,
    balance: FakeBalance | None = None,
    config: GateConfig | None = None,
) -> TelegramSignalExecutor:
    return TelegramSignalExecutor(
        gateway=gateway or FakeGateway(),
        feed=feed or FakeFeed(price=90000.0),
        portfolio_repo=portfolio_repo or FakePortfolioRepo(),
        portfolio_service=portfolio_service or FakePortfolioService(),
        outcome_repo=outcome_repo or FakeOutcomeRepo(),
        balance_provider=lambda: balance or FakeBalance(),
        config=config or GateConfig(),
    )


# ── Tests ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_path_opens_position_with_signal_sl_tp() -> None:
    svc = FakePortfolioService()
    gw = FakeGateway()
    executor = _make_executor(gateway=gw, portfolio_service=svc)
    signal = make_signal()

    outcome = await executor.execute(signal, outcome_id=42)

    assert outcome.status == "executed"
    assert len(gw.calls) == 1
    assert gw.calls[0]["symbol"] == "BTC/USDT"
    assert gw.calls[0]["direction"] == "BUY"
    assert gw.calls[0]["qty"] == pytest.approx(100.0 / 90000.0, rel=1e-6)

    # Position persisted with signal metadata
    assert len(svc.calls) == 1
    call = svc.calls[0]
    assert call["source"] == "telegram"
    assert call["signal_id"] == "42"
    # TP = +5%, SL = -3% relative to entry 90000
    assert call["take_profit_pct"] == pytest.approx(0.05, rel=1e-4)
    assert call["stop_loss_pct"] == pytest.approx(0.03, rel=1e-4)


@pytest.mark.asyncio
async def test_at_market_signal_uses_current_price() -> None:
    svc = FakePortfolioService()
    gw = FakeGateway()
    feed = FakeFeed(price=95000.0)
    executor = _make_executor(gateway=gw, feed=feed, portfolio_service=svc)
    signal = make_signal(entry=None)  # at market

    outcome = await executor.execute(signal, outcome_id=7)

    assert outcome.status == "executed"
    assert gw.calls[0]["price"] == 95000.0


@pytest.mark.asyncio
async def test_gate_failure_skips_without_order() -> None:
    gw = FakeGateway()
    # Position already open → dedup fails
    repo = FakePortfolioRepo(open_positions=[FakePosition(symbol="BTC/USDT", side="BUY")])
    executor = _make_executor(gateway=gw, portfolio_repo=repo)

    outcome = await executor.execute(make_signal(), outcome_id=1)

    assert outcome.status == "skipped"
    assert "already open" in outcome.reason.lower()
    assert gw.calls == []


@pytest.mark.asyncio
async def test_symbol_not_routable_skips_early() -> None:
    gw = FakeGateway()
    executor = _make_executor(gateway=gw)
    # Forex symbol → router raises SymbolNotRoutable
    signal = TelegramSignal(
        source="chat-1", symbol="EUR/USD", direction="BUY",
        entry=1.1, targets=[1.11], stop_loss=1.09, raw_text="",
    )

    outcome = await executor.execute(signal, outcome_id=1)

    assert outcome.status == "skipped"
    assert "not routable" in outcome.reason.lower()
    assert gw.calls == []


@pytest.mark.asyncio
async def test_gateway_failure_is_contained() -> None:
    gw = FakeGateway(raises=RuntimeError("binance down"))
    executor = _make_executor(gateway=gw)

    outcome = await executor.execute(make_signal(), outcome_id=1)

    assert outcome.status == "error"
    assert "binance down" in outcome.reason.lower()


@pytest.mark.asyncio
async def test_sell_signal_computes_sl_tp_correctly() -> None:
    """For SELL, SL is ABOVE entry and TP is BELOW entry."""
    svc = FakePortfolioService()
    executor = _make_executor(portfolio_service=svc)
    signal = TelegramSignal(
        source="chat-1", symbol="BTC/USDT", direction="SELL",
        entry=90000.0,
        targets=[85500.0],   # -5%
        stop_loss=92700.0,   # +3%
        raw_text="",
    )

    await executor.execute(signal, outcome_id=1)

    call = svc.calls[0]
    # SL and TP percentages are absolute (always positive), direction-agnostic;
    # StopLossMonitor already interprets them by side.
    assert call["stop_loss_pct"] == pytest.approx(0.03, rel=1e-4)
    assert call["take_profit_pct"] == pytest.approx(0.05, rel=1e-4)
