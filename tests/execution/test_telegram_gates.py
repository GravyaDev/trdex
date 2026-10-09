"""Gate unit tests.

Each gate tested in isolation with fakes. Full happy path + every
failure reason. One ordering test asserts that when two gates would
both fail, the first-in-order one wins.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import pytest

from trdex.execution.telegram_gates import (
    GateConfig,
    GateResult,
    run_all_gates,
    gate_asset_class_cap,
    gate_budget,
    gate_entry_drift,
    gate_position_dedup,
    gate_reliability,
)
from trdex.telegram.parser import TelegramSignal


# ── Fakes ──────────────────────────────────────────────────────────────

@dataclass
class FakePosition:
    symbol: str
    side: str
    status: str = "open"


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


class FakeSignalOutcomeRepo:
    def __init__(self, win_rate_data: dict[str, tuple[int, float]] | None = None) -> None:
        self._data = win_rate_data or {}

    async def win_rate_by_source(self, source: str) -> tuple[int, float]:
        return self._data.get(source, (0, 0.0))


class FakeBalance:
    def __init__(self, available: Decimal) -> None:
        self.available = available


def make_signal(
    symbol: str = "BTC/USDT",
    direction: str = "BUY",
    entry: float | None = 90000.0,
    source: str = "12345",
) -> TelegramSignal:
    return TelegramSignal(
        source=source,
        symbol=symbol,
        direction=direction,  # type: ignore[arg-type]
        entry=entry,
        targets=[91000.0],
        stop_loss=89000.0,
        raw_text="BUY BTCUSDT entry 90000",
    )


# ── Gate 1: position_dedup ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_dedup_passes_when_no_open() -> None:
    repo = FakePortfolioRepo(open_positions=[])
    signal = make_signal()
    got = await gate_position_dedup(signal, portfolio_repo=repo)
    assert got == GateResult(passed=True, reason="")


@pytest.mark.asyncio
async def test_dedup_blocks_when_same_symbol_side_open() -> None:
    repo = FakePortfolioRepo(open_positions=[FakePosition(symbol="BTC/USDT", side="BUY")])
    signal = make_signal(symbol="BTC/USDT", direction="BUY")
    got = await gate_position_dedup(signal, portfolio_repo=repo)
    assert got.passed is False
    assert "already open" in got.reason.lower()


@pytest.mark.asyncio
async def test_dedup_allows_different_side_on_same_symbol() -> None:
    repo = FakePortfolioRepo(open_positions=[FakePosition(symbol="BTC/USDT", side="BUY")])
    signal = make_signal(symbol="BTC/USDT", direction="SELL")
    got = await gate_position_dedup(signal, portfolio_repo=repo)
    assert got.passed is True


# ── Gate 2: asset_class_cap ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_asset_cap_passes_below_limit() -> None:
    repo = FakePortfolioRepo(open_positions=[
        FakePosition(symbol="BTC/USDT", side="BUY"),
        FakePosition(symbol="ETH/USDT", side="BUY"),
    ])
    config = GateConfig(asset_class_cap=3)
    got = await gate_asset_class_cap(
        make_signal(symbol="SOL/USDT"), portfolio_repo=repo, config=config
    )
    assert got.passed is True


@pytest.mark.asyncio
async def test_asset_cap_blocks_at_limit() -> None:
    repo = FakePortfolioRepo(open_positions=[
        FakePosition(symbol="BTC/USDT", side="BUY"),
        FakePosition(symbol="ETH/USDT", side="BUY"),
        FakePosition(symbol="SOL/USDT", side="BUY"),
    ])
    config = GateConfig(asset_class_cap=3)
    got = await gate_asset_class_cap(
        make_signal(symbol="BNB/USDT"), portfolio_repo=repo, config=config
    )
    assert got.passed is False
    assert "cap" in got.reason.lower()


# ── Gate 3: budget ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_budget_passes_when_balance_sufficient() -> None:
    config = GateConfig(budget=Decimal("100"))
    balance = FakeBalance(available=Decimal("500"))
    got = await gate_budget(make_signal(), balance=balance, config=config)
    assert got.passed is True


@pytest.mark.asyncio
async def test_budget_blocks_when_insufficient() -> None:
    config = GateConfig(budget=Decimal("100"))
    balance = FakeBalance(available=Decimal("50"))
    got = await gate_budget(make_signal(), balance=balance, config=config)
    assert got.passed is False
    assert "budget" in got.reason.lower()


# ── Gate 4: reliability ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reliability_passes_when_under_sample_threshold() -> None:
    config = GateConfig(reliability_min_samples=20, reliability_win_rate_min=0.5)
    repo = FakeSignalOutcomeRepo(win_rate_data={"12345": (5, 0.2)})  # low rate but few samples
    got = await gate_reliability(make_signal(source="12345"), outcome_repo=repo, config=config)
    assert got.passed is True


@pytest.mark.asyncio
async def test_reliability_passes_when_rate_above_min() -> None:
    config = GateConfig(reliability_min_samples=20, reliability_win_rate_min=0.5)
    repo = FakeSignalOutcomeRepo(win_rate_data={"12345": (30, 0.7)})
    got = await gate_reliability(make_signal(source="12345"), outcome_repo=repo, config=config)
    assert got.passed is True


@pytest.mark.asyncio
async def test_reliability_blocks_when_rate_low_and_samples_sufficient() -> None:
    config = GateConfig(reliability_min_samples=20, reliability_win_rate_min=0.5)
    repo = FakeSignalOutcomeRepo(win_rate_data={"12345": (30, 0.3)})
    got = await gate_reliability(make_signal(source="12345"), outcome_repo=repo, config=config)
    assert got.passed is False
    assert "reliability" in got.reason.lower()


# ── Gate 5: entry_drift ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_drift_passes_when_signal_entry_is_none() -> None:
    config = GateConfig(entry_drift_tolerance=0.005)
    got = await gate_entry_drift(make_signal(entry=None), current_price=100.0, config=config)
    assert got.passed is True


@pytest.mark.asyncio
async def test_drift_passes_within_tolerance() -> None:
    config = GateConfig(entry_drift_tolerance=0.005)  # 0.5%
    got = await gate_entry_drift(make_signal(entry=100.0), current_price=100.3, config=config)
    assert got.passed is True


@pytest.mark.asyncio
async def test_drift_blocks_beyond_tolerance() -> None:
    config = GateConfig(entry_drift_tolerance=0.005)
    got = await gate_entry_drift(make_signal(entry=100.0), current_price=101.0, config=config)
    assert got.passed is False
    assert "drift" in got.reason.lower()


# ── Ordering ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_run_all_gates_stops_at_first_failure() -> None:
    """When multiple gates would fail, the first-in-order wins."""
    # Position dedup (first) will fail, budget (third) would also fail
    portfolio_repo = FakePortfolioRepo(open_positions=[
        FakePosition(symbol="BTC/USDT", side="BUY"),
    ])
    outcome_repo = FakeSignalOutcomeRepo()
    balance = FakeBalance(available=Decimal("1"))  # would fail budget
    config = GateConfig(budget=Decimal("100"))
    result = await run_all_gates(
        make_signal(symbol="BTC/USDT", direction="BUY"),
        current_price=90000.0,
        portfolio_repo=portfolio_repo,
        outcome_repo=outcome_repo,
        balance=balance,
        config=config,
    )
    assert result.passed is False
    assert "already open" in result.reason.lower()


# ── Config validation (security hardening) ─────────────────────────────


def test_gate_config_rejects_zero_asset_class_cap() -> None:
    with pytest.raises(ValueError, match="asset_class_cap"):
        GateConfig(asset_class_cap=0)


def test_gate_config_rejects_negative_asset_class_cap() -> None:
    with pytest.raises(ValueError, match="asset_class_cap"):
        GateConfig(asset_class_cap=-1)


def test_gate_config_rejects_zero_budget() -> None:
    with pytest.raises(ValueError, match="budget"):
        GateConfig(budget=Decimal("0"))


def test_gate_config_rejects_negative_budget() -> None:
    with pytest.raises(ValueError, match="budget"):
        GateConfig(budget=Decimal("-10"))


def test_gate_config_rejects_out_of_range_win_rate() -> None:
    with pytest.raises(ValueError, match="reliability_win_rate_min"):
        GateConfig(reliability_win_rate_min=1.5)
    with pytest.raises(ValueError, match="reliability_win_rate_min"):
        GateConfig(reliability_win_rate_min=-0.1)


def test_gate_config_rejects_negative_drift_tolerance() -> None:
    with pytest.raises(ValueError, match="entry_drift_tolerance"):
        GateConfig(entry_drift_tolerance=-0.01)


def test_gate_config_rejects_negative_reliability_samples() -> None:
    with pytest.raises(ValueError, match="reliability_min_samples"):
        GateConfig(reliability_min_samples=-1)


def test_gate_config_accepts_boundary_values() -> None:
    """Boundaries are inclusive where it makes sense (cap=1, samples=0,
    wr=0.0 and wr=1.0, drift=0.0). This anchors them so a future
    tightening of the bounds breaks this test explicitly."""
    GateConfig(
        asset_class_cap=1,
        reliability_min_samples=0,
        reliability_win_rate_min=0.0,
        entry_drift_tolerance=0.0,
        budget=Decimal("0.01"),
    )
    GateConfig(reliability_win_rate_min=1.0)
