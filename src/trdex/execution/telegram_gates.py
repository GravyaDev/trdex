"""Risk gates for TelegramSignalExecutor.

Each gate is a pure function that takes a context object and returns
a GateResult. Gates compose in a fixed order (see execute()).
First failure short-circuits; the reason is logged and the signal
is skipped. Gates are the full surface area of "should we take this
signal?" — the executor itself contains no gating logic.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from trdex.risk.sizing import RegimeBounds, check_regime

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
    max_stop_distance: float = 0.10
    budget: Decimal = Decimal("100")
    # Volatility regime, same bounds as Risk Gate 4c (see
    # regime_gate_settings). ``regime_blocker`` blocks every entry
    # regardless of CV: invalid bounds, or in live missing/stale ones.
    regime: RegimeBounds = field(default_factory=RegimeBounds)
    regime_blocker: str | None = None

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
        if not (0.0 < self.max_stop_distance <= 1.0):
            raise ValueError(
                f"max_stop_distance must be in (0, 1], got {self.max_stop_distance}"
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


async def gate_stop_loss(
    signal: TelegramSignal,
    *,
    current_price: float,
    config: GateConfig,
) -> GateResult:
    """The signal's stop becomes the position's stop, so sanity-check it.

    No stop: pass (the StopLossMonitor's adaptive floor applies).
    Otherwise the stop must sit on the loss side of the reference price
    (entry, or current price for at-market signals) and no further than
    ``max_stop_distance`` from it.
    """
    if signal.stop_loss is None:
        return GateResult(passed=True, reason="")
    reference = signal.entry if signal.entry is not None else current_price
    if reference <= 0:
        return GateResult(passed=False, reason=f"invalid reference price {reference}")
    wrong_side = (
        signal.stop_loss >= reference if signal.direction == "BUY"
        else signal.stop_loss <= reference
    )
    if wrong_side:
        return GateResult(
            passed=False,
            reason=(
                f"stop on wrong side ({signal.direction} stop {signal.stop_loss}"
                f" vs reference {reference})"
            ),
        )
    distance = abs(signal.stop_loss - reference) / reference
    if distance > config.max_stop_distance:
        return GateResult(
            passed=False,
            reason=f"stop distance {distance:.4f} > max {config.max_stop_distance}",
        )
    return GateResult(passed=True, reason="")


def gate_regime(
    signal: TelegramSignal,
    *,
    cv: float | None,
    config: GateConfig,
) -> GateResult:
    """Risk Gate 4c for Telegram entries: block outside the tested CV range.

    ``cv`` is the CV of the last VOL_WINDOW 1h closes (the Analyst's
    formula); ``None`` with configured bounds means unknown → block.
    Unconfigured bounds pass (simulation); live sets ``regime_blocker``.
    """
    if config.regime_blocker:
        return GateResult(passed=False, reason=f"volatility regime gate: {config.regime_blocker}")
    reason = check_regime(cv, config.regime)
    if reason is not None:
        return GateResult(passed=False, reason=f"volatility regime gate: {reason}")
    return GateResult(passed=True, reason="")


def _bound(raw: Any) -> float | None:
    text = str(raw).strip() if raw is not None else ""
    return float(text) if text else None  # ValueError on garbage: caller blocks


def regime_gate_settings(cfg: Any, *, live: bool, now: datetime) -> tuple[RegimeBounds, str | None]:
    """(bounds, blocker) for GateConfig from Runtime Config.

    Same policy as the agent path: in simulation unset bounds turn the
    gate off; in live the bounds must pass the readiness regime criteria
    (set, coherent, regime_data_end within regime_max_age_days), which
    for agent entries Gate 5 enforces. Invalid values block in both modes.
    ``cfg`` None (no Runtime Config) blocks.
    """
    if cfg is None:
        return RegimeBounds(), "Runtime Config unavailable (fail-closed)"
    raw = {
        "cv_min": cfg.get("thresholds", "regime_cv_min", ""),
        "cv_max": cfg.get("thresholds", "regime_cv_max", ""),
        "data_end": cfg.get("thresholds", "regime_data_end", ""),
        "set_at": cfg.get("thresholds", "regime_set_at", ""),
        "max_age_days": cfg.get_typed("thresholds", "regime_max_age_days", 0),
    }
    try:
        bounds = RegimeBounds.from_config(_bound(raw["cv_min"]), _bound(raw["cv_max"]))
    except ValueError as exc:
        return RegimeBounds(), f"invalid regime bounds: {exc}"
    if live:
        from trdex.risk.readiness import _to_naive_utc, regime_criteria

        failures, _ = regime_criteria(**raw, min_days=0, now=_to_naive_utc(now))
        if failures:
            return bounds, "; ".join(failures)
    return bounds, None


# ── Composition ─────────────────────────────────────────────────────────

async def run_all_gates(
    signal: TelegramSignal,
    *,
    current_price: float,
    portfolio_repo: PortfolioRepository,
    outcome_repo: SignalOutcomeRepository,
    balance: _BalanceLike,
    config: GateConfig,
    cv_provider: Callable[[], Awaitable[float | None]] | None = None,
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

    result = await gate_stop_loss(signal, current_price=current_price, config=config)
    if not result.passed:
        return result

    # Regime last: the CV needs candles (a feed call), fetched only when
    # bounds apply and every cheaper gate has passed.
    cv = None
    if config.regime_blocker is None and config.regime.configured and cv_provider is not None:
        cv = await cv_provider()
    result = gate_regime(signal, cv=cv, config=config)
    if not result.passed:
        return result

    return GateResult(passed=True, reason="")
