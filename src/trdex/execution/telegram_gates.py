"""Risk gates for TelegramSignalExecutor.

Each gate is a pure function that takes a context object and returns
a GateResult. Gates compose in a fixed order (see execute()).
First failure short-circuits; the reason is logged and the signal
is skipped. Gates are the full surface area of "should we take this
signal?" — the executor itself contains no gating logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
    from trdex.telegram.parser import TelegramSignal


@dataclass(frozen=True)
class GateResult:
    """Outcome of a single gate evaluation.

    Attributes:
        passed: True if the signal may proceed past this gate.
        reason: Short human-readable tag suitable for logs and
            future telemetry. Empty string when passed=True.
    """

    passed: bool
    reason: str


@dataclass(frozen=True)
class GateConfig:
    """Tunable thresholds for the reliability and entry-drift gates.

    Populated from RuntimeConfig at executor build time and passed
    into the gates as an immutable bundle. Hot-reload is achieved
    by rebuilding the executor when the RuntimeConfig listener fires.
    """

    asset_class_cap: int = 3
    reliability_min_samples: int = 20
    reliability_win_rate_min: float = 0.5
    entry_drift_tolerance: float = 0.005
    budget: Decimal = Decimal("100")

    def __post_init__(self) -> None:
        # Misconfig from RuntimeConfig must fail loud at build time, not
        # silently skip every signal or corrupt sizing math later.
        if self.asset_class_cap < 1:
            raise ValueError(
                f"asset_class_cap must be >= 1, got {self.asset_class_cap}"
            )
        if self.reliability_min_samples < 0:
            raise ValueError(
                f"reliability_min_samples must be >= 0, got {self.reliability_min_samples}"
            )
        if not (0.0 <= self.reliability_win_rate_min <= 1.0):
            raise ValueError(
                f"reliability_win_rate_min must be in [0, 1], got {self.reliability_win_rate_min}"
            )
        if self.entry_drift_tolerance < 0.0:
            raise ValueError(
                f"entry_drift_tolerance must be >= 0, got {self.entry_drift_tolerance}"
            )
        if self.budget <= 0:
            raise ValueError(f"budget must be > 0, got {self.budget}")


# ── Implementation ──────────────────────────────────────────────────────

logger = logging.getLogger(__name__)


@runtime_checkable
class _BalanceLike(Protocol):
    """Minimal balance protocol for the budget gate.

    Concrete impls live in trdex.portfolio.service; the gate only
    needs an `available` field as Decimal.
    """

    available: Decimal


# ── Individual gates ────────────────────────────────────────────────────

async def gate_position_dedup(
    signal: TelegramSignal,
    *,
    portfolio_repo: PortfolioRepository,
) -> GateResult:
    """Block if an open position already exists for (symbol, direction)."""
    existing = await portfolio_repo.get_open_by_symbol_side(
        signal.symbol, signal.direction
    )
    if existing is not None:
        return GateResult(
            passed=False,
            reason=f"position already open for {signal.symbol} {signal.direction}",
        )
    return GateResult(passed=True, reason="")


async def gate_asset_class_cap(
    signal: TelegramSignal,
    *,
    portfolio_repo: PortfolioRepository,
    config: GateConfig,
) -> GateResult:
    """Block if we already have `asset_class_cap` crypto positions open.

    Today only crypto counts; when multi-asset lands, add an
    asset_class column and filter here.
    """
    opens = await portfolio_repo.get_open_positions()
    if len(opens) >= config.asset_class_cap:
        return GateResult(
            passed=False,
            reason=f"asset-class cap reached ({len(opens)}/{config.asset_class_cap})",
        )
    return GateResult(passed=True, reason="")


async def gate_budget(
    signal: TelegramSignal,
    *,
    balance: _BalanceLike,
    config: GateConfig,
) -> GateResult:
    """Block if ledger available balance can't cover one signal budget."""
    if balance.available < config.budget:
        return GateResult(
            passed=False,
            reason=f"budget unavailable (have {balance.available}, need {config.budget})",
        )
    return GateResult(passed=True, reason="")


async def gate_reliability(
    signal: TelegramSignal,
    *,
    outcome_repo: SignalOutcomeRepository,
    config: GateConfig,
) -> GateResult:
    """Below `reliability_min_samples`: pass-through (unknown, not unreliable).
    At/above samples: require win_rate >= reliability_win_rate_min.
    """
    n, win_rate = await outcome_repo.win_rate_by_source(signal.source)
    if n < config.reliability_min_samples:
        return GateResult(passed=True, reason="")
    if win_rate < config.reliability_win_rate_min:
        return GateResult(
            passed=False,
            reason=(
                f"reliability below threshold"
                f" ({win_rate:.2f} < {config.reliability_win_rate_min}"
                f" after {n} samples)"
            ),
        )
    return GateResult(passed=True, reason="")


async def gate_entry_drift(
    signal: TelegramSignal,
    *,
    current_price: float,
    config: GateConfig,
) -> GateResult:
    """If signal.entry is None: at-market, pass-through.
    Else require abs(current - entry) / entry <= entry_drift_tolerance.
    """
    if signal.entry is None:
        return GateResult(passed=True, reason="")
    drift = abs(current_price - signal.entry) / signal.entry
    if drift > config.entry_drift_tolerance:
        return GateResult(
            passed=False,
            reason=f"entry drift {drift:.4f} > tolerance {config.entry_drift_tolerance}",
        )
    return GateResult(passed=True, reason="")


# ── Composition ─────────────────────────────────────────────────────────

async def run_all_gates(
    signal: TelegramSignal,
    *,
    current_price: float,
    portfolio_repo: PortfolioRepository,
    outcome_repo: SignalOutcomeRepository,
    balance: _BalanceLike,
    config: GateConfig,
) -> GateResult:
    """Run all gates in fixed order; short-circuit on first failure.

    Order is intentional: cheapest checks (no I/O) first, then indexed
    DB reads, then the price-dependent drift gate last (assumes caller
    already fetched current_price; that call is the most expensive).
    """
    result = await gate_position_dedup(signal, portfolio_repo=portfolio_repo)
    if not result.passed:
        return result

    result = await gate_asset_class_cap(signal, portfolio_repo=portfolio_repo, config=config)
    if not result.passed:
        return result

    result = await gate_budget(signal, balance=balance, config=config)
    if not result.passed:
        return result

    result = await gate_reliability(signal, outcome_repo=outcome_repo, config=config)
    if not result.passed:
        return result

    result = await gate_entry_drift(signal, current_price=current_price, config=config)
    if not result.passed:
        return result

    return GateResult(passed=True, reason="")
