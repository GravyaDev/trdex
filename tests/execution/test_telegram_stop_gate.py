"""Stop-loss sanity gate for Telegram signals.

The signal's stop becomes the position's stop, so it must sit on the
loss side of the reference price and within ``max_stop_distance``.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from trdex.execution.telegram_gates import GateConfig, gate_stop_loss, run_all_gates
from trdex.telegram.parser import TelegramSignal


def _signal(direction: str, stop: float | None, entry: float | None = 100.0) -> TelegramSignal:
    return TelegramSignal(
        source="chat-1",
        symbol="BTC/USDT",
        direction=direction,  # type: ignore[arg-type]
        entry=entry,
        targets=[110.0] if direction == "BUY" else [90.0],
        stop_loss=stop,
        raw_text="",
    )


CFG = GateConfig()  # max_stop_distance default 0.10


@pytest.mark.asyncio
@pytest.mark.parametrize("direction,stop", [("BUY", 97.0), ("SELL", 103.0)])
async def test_stop_on_loss_side_within_distance_passes(direction, stop):
    got = await gate_stop_loss(_signal(direction, stop), current_price=100.0, config=CFG)
    assert got.passed is True


@pytest.mark.asyncio
async def test_missing_stop_passes_and_monitor_floor_applies():
    got = await gate_stop_loss(_signal("BUY", None), current_price=100.0, config=CFG)
    assert got.passed is True


@pytest.mark.asyncio
@pytest.mark.parametrize("direction,stop", [("BUY", 101.0), ("SELL", 99.0), ("BUY", 100.0)])
async def test_stop_on_wrong_side_is_rejected(direction, stop):
    got = await gate_stop_loss(_signal(direction, stop), current_price=100.0, config=CFG)
    assert got.passed is False
    assert "wrong side" in got.reason


@pytest.mark.asyncio
async def test_stop_too_far_is_rejected():
    got = await gate_stop_loss(_signal("BUY", 60.0), current_price=100.0, config=CFG)
    assert got.passed is False
    assert "stop distance" in got.reason


@pytest.mark.asyncio
async def test_at_market_signal_uses_current_price_as_reference():
    # entry=None: 95 is 5% below the current price of 100 → ok.
    got = await gate_stop_loss(_signal("BUY", 95.0, entry=None), current_price=100.0, config=CFG)
    assert got.passed is True


def test_config_rejects_out_of_range_max_stop_distance():
    with pytest.raises(ValueError, match="max_stop_distance"):
        GateConfig(max_stop_distance=0.0)
    with pytest.raises(ValueError, match="max_stop_distance"):
        GateConfig(max_stop_distance=1.5)


class _Repo:
    async def get_open_by_symbol_side(self, symbol, side):
        return None

    async def get_open_positions(self):
        return []


class _Outcomes:
    async def win_rate_by_source(self, source):
        return (0, 0.0)


class _Balance:
    available = Decimal("10000")


@pytest.mark.asyncio
async def test_run_all_gates_includes_stop_gate():
    result = await run_all_gates(
        _signal("BUY", 60.0),
        current_price=100.0,
        portfolio_repo=_Repo(),
        outcome_repo=_Outcomes(),
        balance=_Balance(),
        config=CFG,
    )
    assert result.passed is False
    assert "stop distance" in result.reason
