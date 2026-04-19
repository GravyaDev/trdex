"""Risk gates for TelegramSignalExecutor.

Each gate is a pure function that takes a context object and returns
a GateResult. Gates compose in a fixed order (see execute()).
First failure short-circuits; the reason is logged and the signal
is skipped. Gates are the full surface area of "should we take this
signal?" — the executor itself contains no gating logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

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


# Gates are implemented as async functions in Task 5.
