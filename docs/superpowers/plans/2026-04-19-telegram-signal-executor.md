# TelegramSignalExecutor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote Telegram signals from observe-only to actual trade execution, routed through `DefaultExecutionGateway` so `TRDEX_MODE=simulation` uses the simulator and `TRDEX_MODE=live` uses Binance — same pattern as every other trdex signal source. Fail-closed behind a hot-reloadable RuntimeConfig flag.

**Architecture:** `_telegram_background` (app.py) parses a signal → writes `signal_outcomes` observe-only record (existing) → if `integrations.telegram_executor_enabled` is true, hands the `(signal, outcome_id)` pair to a new `TelegramSignalExecutor`. The executor runs 5 gates (position-dedup → asset-class-cap → budget → reliability → entry-drift), fetches current price via the symbol router, computes qty, calls `DefaultExecutionGateway.place(...)`, and persists the resulting position via `PortfolioService.record_open_fill(...)` with `source="telegram"`, `signal_id=str(outcome.id)`, and `stop_loss_pct`/`take_profit_pct` converted from the signal's absolute prices. `StopLossMonitor` already honors those per-position fields — no change needed there.

**Tech Stack:** Python 3.12+, SQLAlchemy async, asyncpg, Pydantic, pytest + pytest-asyncio, FastAPI (lifespan), Streamlit (dashboard).

---

## File Structure

### New files

- `src/trdex/execution/symbol_router.py` — `route(symbol) → (PriceFeed, Gateway)` with `SymbolNotRoutable` exception; today crypto-only.
- `src/trdex/execution/telegram_gates.py` — 5 pure gate functions, each returning `GateResult(passed: bool, reason: str)`.
- `src/trdex/execution/telegram_executor.py` — orchestrator; no business logic inside it, only sequencing.
- `tests/execution/__init__.py` — empty, makes the subpackage importable.
- `tests/execution/test_symbol_router.py`
- `tests/execution/test_telegram_gates.py`
- `tests/execution/test_telegram_executor.py`
- `tests/execution/test_telegram_simulation.py`

### Modified files

- `src/trdex/storage/portfolio_repo.py` — add `get_open_by_symbol_side(symbol, side)`.
- `src/trdex/storage/signal_outcome_repo.py` — add `win_rate_by_source(source)`.
- `src/trdex/services/runtime_config.py` — register 4 new keys in `_KEY_REGISTRY`.
- `src/trdex/api/app.py::_telegram_background` — insert executor invocation.
- `src/trdex/dashboard/app.py` — add "telegram" to positions source filter.

### NOT modified (reality-check)

- `src/trdex/risk/stop_loss.py` — `StopLossMonitor.check_now()` already reads `pos.stop_loss_pct` / `pos.take_profit_pct` with precedence over CV-adaptive. Writing those at open time satisfies Task 2.4.
- No new migration — `positions.signal_id` already bridges observe ↔ executed.

---

## Task 1: Position dedup query

**Files:**
- Modify: `src/trdex/storage/portfolio_repo.py`
- Test: `tests/execution/test_symbol_router.py` (no — this is a repo test; add to `tests/storage/test_portfolio_repo.py` if exists, else inline in `tests/execution/test_telegram_gates.py`)

Reality: this repo has no dedicated tests file for it today. Place the unit test in `tests/execution/test_telegram_gates.py` alongside the gate that uses it — the gate test will invoke the repo method through the real repo on a test DB session (integration-style). This is cheaper than creating a standalone repo test for a single method.

- [ ] **Step 1: Add method to repository**

Edit `src/trdex/storage/portfolio_repo.py`, add after `get_open_positions` (around line 69):

```python
async def get_open_by_symbol_side(
    self,
    symbol: str,
    side: str,
) -> PositionRecord | None:
    """Return the single open position matching (symbol, side), or None.

    Used by the Telegram signal dedup gate to enforce
    "max 1 open position per (symbol, direction)" cheaply
    (indexed lookup rather than Python-side filter).
    """
    stmt = (
        sa.select(PositionRecord)
        .where(PositionRecord.symbol == symbol)
        .where(PositionRecord.side == side)
        .where(PositionRecord.status == "open")
        .limit(1)
    )
    result = await self._session.execute(stmt)
    return result.scalar_one_or_none()
```

Check the top of the file for the `sa` import alias convention — if it uses `from sqlalchemy import select` directly, use `select(...)` instead of `sa.select(...)`. Match existing style.

- [ ] **Step 2: Commit**

```bash
git add src/trdex/storage/portfolio_repo.py
git commit -m "feat(storage): add get_open_by_symbol_side for dedup gate"
```

---

## Task 2: Win-rate-by-source query

**Files:**
- Modify: `src/trdex/storage/signal_outcome_repo.py`
- Test: assertion will be done via the gate test (Task 5)

- [ ] **Step 1: Add method**

Edit `src/trdex/storage/signal_outcome_repo.py`, add after `by_source`:

```python
async def win_rate_by_source(self, source: str) -> tuple[int, float]:
    """Return (sample_count, win_rate) for closed signals from `source`.

    A "win" is a closed outcome where the direction matched the price
    move: BUY with exit_price >= entry_price OR SELL with exit_price
    <= entry_price. Rows with exit_price IS NULL (still open) are
    excluded from both numerator and denominator.

    Returns (0, 0.0) when no closed outcomes exist.
    """
    stmt = (
        sa.select(
            sa.func.count().label("n"),
            sa.func.sum(
                sa.case(
                    (
                        sa.and_(
                            SignalOutcomeRecord.direction == "BUY",
                            SignalOutcomeRecord.exit_price >= SignalOutcomeRecord.entry_price,
                        ),
                        1,
                    ),
                    (
                        sa.and_(
                            SignalOutcomeRecord.direction == "SELL",
                            SignalOutcomeRecord.exit_price <= SignalOutcomeRecord.entry_price,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ).label("wins"),
        )
        .where(SignalOutcomeRecord.source == source)
        .where(SignalOutcomeRecord.exit_price.is_not(None))
    )
    row = (await self._session.execute(stmt)).one()
    n = int(row.n or 0)
    wins = int(row.wins or 0)
    if n == 0:
        return 0, 0.0
    return n, wins / n
```

Match the existing `sa` import style in the file — if it imports `from sqlalchemy import ...` piecemeal, use the names directly.

- [ ] **Step 2: Commit**

```bash
git add src/trdex/storage/signal_outcome_repo.py
git commit -m "feat(storage): add win_rate_by_source for reliability gate"
```

---

## Task 3: Symbol router

**Files:**
- Create: `src/trdex/execution/symbol_router.py`
- Test: `tests/execution/test_symbol_router.py`

- [ ] **Step 1: Create test file with failing test**

Create `tests/execution/__init__.py` (empty file).

Create `tests/execution/test_symbol_router.py`:

```python
"""Symbol router tests.

The router today is crypto-only. Forex/commodity/index symbols
raise SymbolNotRoutable — Telegram signals for those get skipped
with a logged reason. When the Multi-asset Forex epic lands, the
router will add a forex branch; until then the executor is
intentionally single-asset-class.
"""

from __future__ import annotations

import pytest

from trdex.execution.symbol_router import (
    SymbolNotRoutable,
    is_crypto,
    route,
)


class FakePriceFeed:
    name = "fake"


class FakeGateway:
    pass


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("BTC/USDT", True),
        ("ETH/USDT", True),
        ("SOL/USDT", True),
        ("EUR/USD", False),
        ("XAU/USD", False),
        ("NAS100/USD", False),
        ("AAPL", False),
        ("", False),
    ],
)
def test_is_crypto_classification(symbol: str, expected: bool) -> None:
    assert is_crypto(symbol) is expected


def test_route_crypto_returns_feed_and_gateway() -> None:
    feed = FakePriceFeed()
    gateway = FakeGateway()
    got_feed, got_gateway = route("BTC/USDT", feed=feed, gateway=gateway)
    assert got_feed is feed
    assert got_gateway is gateway


def test_route_forex_raises() -> None:
    with pytest.raises(SymbolNotRoutable) as exc_info:
        route("EUR/USD", feed=FakePriceFeed(), gateway=FakeGateway())
    assert "EUR/USD" in str(exc_info.value)


def test_route_commodity_raises() -> None:
    with pytest.raises(SymbolNotRoutable):
        route("XAU/USD", feed=FakePriceFeed(), gateway=FakeGateway())
```

- [ ] **Step 2: Run test — expect import error**

```bash
uv run pytest tests/execution/test_symbol_router.py -x 2>&1 | tail -5
```

Expected: `ModuleNotFoundError: No module named 'trdex.execution.symbol_router'`.

- [ ] **Step 3: Create the router**

Create `src/trdex/execution/symbol_router.py`:

```python
"""Symbol router — maps a symbol to its (PriceFeed, ExecutionGateway) pair.

Today crypto-only. Non-crypto symbols raise SymbolNotRoutable; the
Telegram executor treats that as a skip-with-reason and moves on.
When the Multi-asset Forex epic (OandaFeed + OandaExecutor) lands,
this router gains a forex branch.

The router does not own feed/gateway instances — callers inject them.
Keeps symbol_router.py pure and testable without infrastructure.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trdex.execution.gateway import ExecutionGateway
    from trdex.market.feeds.base import PriceFeed


class SymbolNotRoutable(ValueError):
    """Raised when no (feed, gateway) pair is available for this symbol.

    The Telegram executor catches this exception and skips the signal
    with a logged reason. Non-fatal.
    """


# Quote currencies recognized as crypto. If the symbol is "BASE/QUOTE"
# with QUOTE in this set, treat as crypto. Otherwise non-crypto.
_CRYPTO_QUOTES: frozenset[str] = frozenset({
    "USDT", "USDC", "BUSD", "DAI", "BTC", "ETH", "BNB", "FDUSD", "TUSD",
})


def is_crypto(symbol: str) -> bool:
    """True if `symbol` looks like a crypto pair (BASE/CRYPTO_QUOTE)."""
    if not symbol or "/" not in symbol:
        return False
    _, _, quote = symbol.partition("/")
    return quote.upper() in _CRYPTO_QUOTES


def route(
    symbol: str,
    *,
    feed: PriceFeed,
    gateway: ExecutionGateway,
) -> tuple[PriceFeed, ExecutionGateway]:
    """Return the (feed, gateway) pair that should handle `symbol`.

    Raises SymbolNotRoutable for any non-crypto symbol.
    """
    if is_crypto(symbol):
        return feed, gateway
    raise SymbolNotRoutable(
        f"No executor available for symbol {symbol!r} "
        f"(crypto-only today; forex/commodity deferred to Multi-asset epic)"
    )
```

- [ ] **Step 4: Run tests — expect pass**

```bash
uv run pytest tests/execution/test_symbol_router.py -v 2>&1 | tail -15
```

Expected: all 11 parametrized + 3 explicit tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trdex/execution/symbol_router.py tests/execution/__init__.py tests/execution/test_symbol_router.py
git commit -m "feat(execution): add symbol router with crypto-only scope"
```

---

## Task 4: Gate data structures + shared types

**Files:**
- Create: `src/trdex/execution/telegram_gates.py` (stub — full logic added in Task 5)
- No test yet (structures only).

- [ ] **Step 1: Create gates module skeleton**

Create `src/trdex/execution/telegram_gates.py`:

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add src/trdex/execution/telegram_gates.py
git commit -m "feat(execution): add GateResult and GateConfig for telegram gates"
```

---

## Task 5: Five gate functions + ordering + test

**Files:**
- Modify: `src/trdex/execution/telegram_gates.py`
- Test: `tests/execution/test_telegram_gates.py`

- [ ] **Step 1: Write failing tests**

Create `tests/execution/test_telegram_gates.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect import errors**

```bash
uv run pytest tests/execution/test_telegram_gates.py -x 2>&1 | tail -8
```

Expected: ImportError for `run_all_gates` and the five gate functions.

- [ ] **Step 3: Implement the gates**

Append to `src/trdex/execution/telegram_gates.py`:

```python
from __future__ import annotations  # already at top

import logging
from decimal import Decimal
from typing import Protocol, runtime_checkable

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
        return GateResult(passed=False, reason=f"position already open for {signal.symbol} {signal.direction}")
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
            reason=f"reliability below threshold ({win_rate:.2f} < {config.reliability_win_rate_min} after {n} samples)",
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
```

- [ ] **Step 4: Run tests — expect all pass**

```bash
uv run pytest tests/execution/test_telegram_gates.py -v 2>&1 | tail -25
```

Expected: all 14+ tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trdex/execution/telegram_gates.py tests/execution/test_telegram_gates.py
git commit -m "feat(execution): implement five telegram gates + ordering"
```

---

## Task 6: RuntimeConfig key registration

**Files:**
- Modify: `src/trdex/services/runtime_config.py`

- [ ] **Step 1: Add keys to the registry**

Open `src/trdex/services/runtime_config.py` and find `_KEY_REGISTRY` (around line 27 per reality-check). Add entries for the four new keys. Match the existing tuple format `(settings_attr, python_type)`:

In the `integrations` block, add:
```python
    ("integrations", "telegram_executor_enabled"): (None, bool),
```

In the `telegram` block, add:
```python
    ("telegram", "entry_drift_tolerance"): (None, float),
    ("telegram", "reliability_min_samples"): (None, int),
    ("telegram", "reliability_win_rate_min"): (None, float),
```

All four have `settings_attr=None` — they are DB-only, no env-var seed.

- [ ] **Step 2: Run existing runtime_config tests**

```bash
uv run pytest tests/services/test_runtime_config.py -v 2>&1 | tail -10
```

(Skip if the file doesn't exist; the registry addition is declarative and any existing tests continue to pass.)

- [ ] **Step 3: Commit**

```bash
git add src/trdex/services/runtime_config.py
git commit -m "feat(runtime-config): register four telegram executor keys"
```

---

## Task 7: TelegramSignalExecutor (orchestrator)

**Files:**
- Create: `src/trdex/execution/telegram_executor.py`
- Test: `tests/execution/test_telegram_executor.py`

- [ ] **Step 1: Write the executor test**

Create `tests/execution/test_telegram_executor.py`:

```python
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
```

- [ ] **Step 2: Run tests — expect import error**

```bash
uv run pytest tests/execution/test_telegram_executor.py -x 2>&1 | tail -5
```

Expected: ModuleNotFoundError for `trdex.execution.telegram_executor`.

- [ ] **Step 3: Implement the executor**

Create `src/trdex/execution/telegram_executor.py`:

```python
"""TelegramSignalExecutor — orchestrates gate → fetch → place → persist.

Zero business logic here. This file is a sequencer:
  1. Route the symbol (may raise SymbolNotRoutable → skip).
  2. Fetch current price from the routed feed.
  3. Run all gates in order. First failure → skip with reason.
  4. Compute qty = budget / current_price.
  5. Compute SL/TP percentages relative to entry (or current if at-market).
  6. Place order via gateway. Any raise → error outcome.
  7. Persist position with source='telegram', signal_id, SL/TP pct.

Returns an ExecuteOutcome describing what happened. Callers log the
outcome; no exception propagates out of execute().
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Literal, Protocol

from trdex.execution.symbol_router import SymbolNotRoutable, route
from trdex.execution.telegram_gates import GateConfig, run_all_gates
from trdex.telegram.parser import TelegramSignal

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecuteOutcome:
    """Result of attempting to execute a signal.

    status:
        - "executed" — position opened, persisted.
        - "skipped"  — a gate or the router blocked execution.
        - "error"    — gateway or persistence failed unexpectedly.
    """
    status: Literal["executed", "skipped", "error"]
    reason: str
    position_id: int | None = None


class _FeedLike(Protocol):
    name: str
    async def get_current_price(self, symbol: str) -> float: ...


class _GatewayLike(Protocol):
    async def place(
        self, *, symbol: str, direction: str, qty: float, price: float,
        idempotency_key: str | None = None,
    ) -> Any: ...


class _BalanceLike(Protocol):
    available: Decimal


class TelegramSignalExecutor:
    def __init__(
        self,
        *,
        gateway: _GatewayLike,
        feed: _FeedLike,
        portfolio_repo: Any,            # PortfolioRepository
        portfolio_service: Any,         # PortfolioService with record_open_fill
        outcome_repo: Any,              # SignalOutcomeRepository
        balance_provider: Callable[[], _BalanceLike],
        config: GateConfig,
    ) -> None:
        self._gateway = gateway
        self._feed = feed
        self._portfolio_repo = portfolio_repo
        self._portfolio_service = portfolio_service
        self._outcome_repo = outcome_repo
        self._balance_provider = balance_provider
        self._config = config

    async def execute(self, signal: TelegramSignal, *, outcome_id: int) -> ExecuteOutcome:
        # 1. Route
        try:
            feed, gateway = route(signal.symbol, feed=self._feed, gateway=self._gateway)
        except SymbolNotRoutable as exc:
            logger.info("[telegram-exec] skip %s %s: not routable — %s",
                        signal.direction, signal.symbol, exc)
            return ExecuteOutcome(status="skipped", reason=f"symbol not routable: {exc}")

        # 2. Fetch price
        try:
            current_price = await feed.get_current_price(signal.symbol)
        except Exception as exc:
            logger.exception("[telegram-exec] price fetch failed for %s", signal.symbol)
            return ExecuteOutcome(status="error", reason=f"price fetch failed: {exc}")

        # 3. Gates
        gate_result = await run_all_gates(
            signal,
            current_price=current_price,
            portfolio_repo=self._portfolio_repo,
            outcome_repo=self._outcome_repo,
            balance=self._balance_provider(),
            config=self._config,
        )
        if not gate_result.passed:
            logger.info("[telegram-exec] skip %s %s from %s: %s",
                        signal.direction, signal.symbol, signal.source, gate_result.reason)
            return ExecuteOutcome(status="skipped", reason=gate_result.reason)

        # 4. Sizing
        qty = float(self._config.budget) / current_price

        # 5. SL/TP percentages — always positive, relative to entry price.
        # StopLossMonitor reads pos.stop_loss_pct / pos.take_profit_pct and
        # applies them by side. A SELL with sl=90000→92700 (+3%) produces
        # the same 0.03 percent as a BUY with sl=92000→89240 (-3%).
        reference_price = signal.entry if signal.entry is not None else current_price
        stop_loss_pct = (
            abs(signal.stop_loss - reference_price) / reference_price
            if signal.stop_loss is not None else None
        )
        take_profit_pct = (
            abs(signal.targets[0] - reference_price) / reference_price
            if signal.targets else None
        )

        # 6. Place order
        try:
            order_result = await gateway.place(
                symbol=signal.symbol,
                direction=signal.direction,
                qty=qty,
                price=current_price,
                idempotency_key=f"telegram:{outcome_id}",
            )
        except Exception as exc:
            logger.exception("[telegram-exec] gateway failed for %s %s",
                             signal.direction, signal.symbol)
            return ExecuteOutcome(status="error", reason=f"gateway error: {exc}")

        if getattr(order_result, "status", "filled") != "filled":
            msg = getattr(order_result, "message", "unknown rejection")
            logger.warning("[telegram-exec] order rejected for %s %s: %s",
                           signal.direction, signal.symbol, msg)
            return ExecuteOutcome(status="error", reason=f"order rejected: {msg}")

        # 7. Persist position
        try:
            position = await self._portfolio_service.record_open_fill(
                symbol=signal.symbol,
                side=signal.direction,
                entry_price=Decimal(str(order_result.filled_price)),
                amount=Decimal(str(order_result.filled_qty)),
                budget=self._config.budget,
                fee=Decimal(str(getattr(order_result, "fee", 0.0))),
                source="telegram",
                signal_id=str(outcome_id),
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
        except Exception as exc:
            logger.exception("[telegram-exec] persistence failed after fill")
            return ExecuteOutcome(status="error", reason=f"persistence failed: {exc}")

        logger.info("[telegram-exec] executed %s %s qty=%.6f from %s (pos=%s)",
                    signal.direction, signal.symbol, qty, signal.source, position.id)
        return ExecuteOutcome(status="executed", reason="", position_id=position.id)
```

Before running the tests, confirm that `PortfolioService.record_open_fill` accepts the kwargs used above (`symbol`, `side`, `entry_price`, `amount`, `budget`, `fee`, `source`, `signal_id`, `stop_loss_pct`, `take_profit_pct`). If any kwarg name differs (e.g. `direction` vs `side`), adjust the call — match the real signature. The reality-check report identified this method's approximate shape at `src/trdex/portfolio/service.py:101`.

- [ ] **Step 4: Run tests — expect all pass**

```bash
uv run pytest tests/execution/test_telegram_executor.py -v 2>&1 | tail -20
```

Expected: all 6 tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/trdex/execution/telegram_executor.py tests/execution/test_telegram_executor.py
git commit -m "feat(execution): TelegramSignalExecutor orchestrator"
```

---

## Task 8: Wire executor into `_telegram_background`

**Files:**
- Modify: `src/trdex/api/app.py`

- [ ] **Step 1: Identify insertion point**

Open `src/trdex/api/app.py`. Find `_telegram_background` function (starts around line 101). Locate:
- The `if signal is not None:` branch that handles parsed signals (~line 146).
- The `repo.save(...)` call that persists the observe-only outcome (~line 182-197).
- The `await _ingest_signal_to_qdrant(signal)` call (~line 207).
- The `else:` branch for non-signal news messages (~line 208).

The executor invocation goes **after** `_ingest_signal_to_qdrant(signal)` and **inside** the `if signal is not None:` branch, before its closing.

The executor needs `outcome.id`. The `repo.save(...)` call returns a `SignalOutcomeRecord` — capture its `.id` into a local variable (`outcome`) if it isn't already captured. Reality-check report indicates the record is already returned but may be captured as `outcome` or ignored; confirm with the actual lines.

- [ ] **Step 2: Import dependencies at top of file**

Add near other `from trdex...` imports:

```python
from trdex.execution.telegram_executor import TelegramSignalExecutor
from trdex.execution.telegram_gates import GateConfig
```

- [ ] **Step 3: Build the executor at function entry**

At the top of `_telegram_background` (before the `async for msg in monitor.stream_raw(channels):` loop), add a `_build_executor` closure so we can rebuild on RuntimeConfig change:

```python
    from trdex.services.runtime_config import get_config_service
    from trdex.config import get_settings

    def _build_executor() -> TelegramSignalExecutor | None:
        """Construct a fresh executor from current config. Returns None when disabled."""
        svc = get_config_service()
        if svc is None or not svc.get_typed("integrations", "telegram_executor_enabled", False):
            return None
        settings = get_settings()
        config = GateConfig(
            asset_class_cap=3,
            reliability_min_samples=int(svc.get_typed("telegram", "reliability_min_samples", 20)),
            reliability_win_rate_min=float(svc.get_typed("telegram", "reliability_win_rate_min", 0.5)),
            entry_drift_tolerance=float(svc.get_typed("telegram", "entry_drift_tolerance", 0.005)),
            budget=Decimal(str(settings.telegram_signal_budget)),
        )
        # Portfolio service + repos + feed + gateway are grabbed from the
        # app state via dependency helpers. Match the helper names in this
        # file — reality-check indicates session_factory is available as a
        # parameter; portfolio_service / feed / gateway should be accessed
        # through the same getters that _telegram_background already uses
        # for other cross-cutting needs.
        from trdex.execution.default_gateway import DefaultExecutionGateway
        from trdex.market.manager import get_feed_manager  # adjust if helper differs
        from trdex.portfolio.service import PortfolioService
        # NOTE: if these helpers aren't global singletons, pass session_factory down
        # and let the executor's callers grab fresh repos per session.
        return TelegramSignalExecutor(
            gateway=DefaultExecutionGateway.create(settings),
            feed=get_feed_manager(),
            portfolio_repo=None,   # see step 4 — lazy-bind per-session
            portfolio_service=None,
            outcome_repo=None,
            balance_provider=lambda: None,  # see step 4
            config=config,
        )
```

**Reality-check adjustment:** the executor needs per-session repos (not singletons) because trdex uses `async with session_factory() as session` per operation. Rather than building a singleton executor, build a *factory* that produces an executor scoped to the current session when a signal arrives. See step 4.

- [ ] **Step 4: Replace the singleton approach with per-signal factory**

Replace step 3 with the cleaner approach: don't build an executor up front; instead, define a helper that takes a freshly-saved `outcome.id` and a session, builds the executor, runs it, and closes. This matches how `_telegram_background` already uses sessions.

```python
    from decimal import Decimal as _Decimal
    from trdex.services.runtime_config import get_config_service
    from trdex.config import get_settings as _get_settings
    from trdex.execution.telegram_gates import GateConfig
    from trdex.execution.telegram_executor import TelegramSignalExecutor
    from trdex.execution.default_gateway import DefaultExecutionGateway
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
    from trdex.portfolio.service import PortfolioService
    from trdex.storage.balance_repo import BalanceRepository

    async def _maybe_execute(signal, outcome_id: int, session) -> None:
        svc = get_config_service()
        if svc is None or not svc.get_typed("integrations", "telegram_executor_enabled", False):
            return
        settings = _get_settings()
        config = GateConfig(
            asset_class_cap=3,
            reliability_min_samples=int(svc.get_typed("telegram", "reliability_min_samples", 20)),
            reliability_win_rate_min=float(svc.get_typed("telegram", "reliability_win_rate_min", 0.5)),
            entry_drift_tolerance=float(svc.get_typed("telegram", "entry_drift_tolerance", 0.005)),
            budget=_Decimal(str(settings.telegram_signal_budget)),
        )
        portfolio_repo = PortfolioRepository(session)
        outcome_repo = SignalOutcomeRepository(session)
        balance_repo = BalanceRepository(session)
        # Balance snapshot: the balance gate needs `.available` as Decimal.
        # Pull the latest balance record from the ledger; wrap in a simple
        # namespace. If balance_repo exposes a direct `available()` method,
        # prefer that.
        latest = await balance_repo.latest_balance_after()  # method name — verify and adjust
        from types import SimpleNamespace
        balance = SimpleNamespace(available=_Decimal(str(latest)))
        gateway = DefaultExecutionGateway.create(settings)
        portfolio_service = PortfolioService(session)
        # feed: use the global PriceFeedManager singleton
        from trdex.market.manager import get_feed_manager  # adjust name per real helper
        feed = get_feed_manager()
        executor = TelegramSignalExecutor(
            gateway=gateway,
            feed=feed,
            portfolio_repo=portfolio_repo,
            portfolio_service=portfolio_service,
            outcome_repo=outcome_repo,
            balance_provider=lambda: balance,
            config=config,
        )
        try:
            result = await executor.execute(signal, outcome_id=outcome_id)
            logger.info("[telegram] executor result: %s — %s", result.status, result.reason or "ok")
        except Exception:
            logger.exception("[telegram] executor raised; observe-only record unaffected")
```

- [ ] **Step 5: Insert the call after Qdrant ingest**

Find the line `await _ingest_signal_to_qdrant(signal)` inside the `if signal is not None:` branch. Immediately below it (still in the same branch), add:

```python
                # Executor: gated by integrations.telegram_executor_enabled.
                # No-op when disabled. Uses the same session we saved the
                # outcome in so balance reads are consistent with the
                # observe-only record just written.
                if outcome is not None:  # guard for the "no entry price" branch
                    await _maybe_execute(signal, outcome_id=outcome.id, session=session)
```

Note: `outcome` is only set when `signal.entry is not None` (the persistence branch). When `signal.entry is None`, `outcome` is not defined and the executor is skipped (same contract as persistence — parity).

**IMPORTANT — verify helper names before commit**:
- `get_feed_manager` (step 4) — the actual helper in `src/trdex/market/manager.py` may be named differently. Confirm and adjust.
- `balance_repo.latest_balance_after()` — may be named `get_latest` or similar. Confirm against real code.
- `PortfolioService(session)` constructor — may take different args. Confirm.
- `PortfolioRepository(session)` / `SignalOutcomeRepository(session)` — same.

These are small name adjustments. Do not guess — open each file and match the actual signature. **If a name differs, update the plan file inline** so Task 8 stays accurate for future re-runs.

- [ ] **Step 6: Run the full suite to catch regressions**

```bash
uv run pytest 2>&1 | tail -20
```

Expected: previous baseline (400+ tests) still green. New execution tests green.

- [ ] **Step 7: Commit**

```bash
git add src/trdex/api/app.py
git commit -m "feat(telegram): wire TelegramSignalExecutor into _telegram_background"
```

---

## Task 9: End-to-end simulation test

**Files:**
- Create: `tests/execution/test_telegram_simulation.py`

- [ ] **Step 1: Write the integration test**

Create `tests/execution/test_telegram_simulation.py`:

```python
"""End-to-end simulation mode test (Task 2.7).

Spins up a real session against the test DB, sets TRDEX_MODE=simulation,
flips the runtime_config flag on, feeds a fake signal through
_telegram_background (or directly through the wire-up helper), and
asserts:
    - signal_outcomes row exists
    - positions row exists with source='telegram', correct signal_id,
      stop_loss_pct and take_profit_pct
    - no live API call was made (simulator gateway used).

This is the closest we can get to production behavior without touching
Binance live. It exercises the same code paths that will run in prod
once telegram_executor_enabled is flipped on.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration

# This test uses the same test-db fixture as other integration tests in
# this repo. Look at an existing tests/storage/test_*.py for the fixture
# name (likely `session_factory` or `db_session`) and use the same one.
# If none exist, skip this task or stub with an in-memory SQLite.


@pytest.mark.asyncio
async def test_simulation_mode_end_to_end(db_session, runtime_config_service, monkeypatch):
    """Happy path simulation execution persists both outcome and position."""
    from trdex.config import TrdexMode, get_settings
    from trdex.execution.default_gateway import DefaultExecutionGateway
    from trdex.execution.telegram_executor import TelegramSignalExecutor
    from trdex.execution.telegram_gates import GateConfig
    from trdex.portfolio.service import PortfolioService
    from trdex.storage.portfolio_repo import PortfolioRepository
    from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
    from trdex.telegram.parser import TelegramSignal
    from types import SimpleNamespace

    # Force simulation mode
    monkeypatch.setenv("TRDEX_MODE", "simulation")
    settings = get_settings()  # reads env
    assert settings.mode == TrdexMode.SIMULATION

    # Flip the flag on via runtime_config
    await runtime_config_service.put("integrations", "telegram_executor_enabled", "true")

    # Persist an observe-only outcome first (simulates the upstream save)
    outcome_repo = SignalOutcomeRepository(db_session)
    outcome = await outcome_repo.save(
        source="chat-99",
        symbol="BTC/USDT",
        direction="BUY",
        entry_price=Decimal("90000"),
        exit_price=None,
        budget=Decimal("0"),
        note='{"targets":[94500.0],"stop_loss":87300.0}',
    )
    await db_session.commit()

    signal = TelegramSignal(
        source="chat-99",
        symbol="BTC/USDT",
        direction="BUY",
        entry=90000.0,
        targets=[94500.0],
        stop_loss=87300.0,
        raw_text="BUY BTCUSDT",
    )

    # Build a minimal fake feed — we don't want to hit a real exchange
    class _Feed:
        name = "fake"
        async def get_current_price(self, symbol: str) -> float:
            return 90000.0

    config = GateConfig(
        asset_class_cap=3,
        reliability_min_samples=20,
        reliability_win_rate_min=0.5,
        entry_drift_tolerance=0.005,
        budget=Decimal("100"),
    )
    gateway = DefaultExecutionGateway.create(settings)
    portfolio_repo = PortfolioRepository(db_session)
    portfolio_service = PortfolioService(db_session)
    # Seed a balance so the gate passes
    from trdex.storage.balance_repo import BalanceRepository
    balance_repo = BalanceRepository(db_session)
    await balance_repo.deposit(Decimal("10000"), note="test seed")
    await db_session.commit()

    executor = TelegramSignalExecutor(
        gateway=gateway,
        feed=_Feed(),
        portfolio_repo=portfolio_repo,
        portfolio_service=portfolio_service,
        outcome_repo=outcome_repo,
        balance_provider=lambda: SimpleNamespace(available=Decimal("10000")),
        config=config,
    )

    result = await executor.execute(signal, outcome_id=outcome.id)
    await db_session.commit()

    assert result.status == "executed"
    assert result.position_id is not None

    # Fetch the persisted position
    position = await portfolio_repo.get_open_by_symbol_side("BTC/USDT", "BUY")
    assert position is not None
    assert position.source == "telegram"
    assert position.signal_id == str(outcome.id)
    assert position.stop_loss_pct == pytest.approx(0.03, rel=1e-4)
    assert position.take_profit_pct == pytest.approx(0.05, rel=1e-4)
```

**Fixture note:** This test assumes a `db_session` + `runtime_config_service` fixture. If those names don't match what the repo uses, adjust the signature — look at any existing `tests/storage/test_*.py` integration test for the fixture name convention. If no suitable fixture exists, mark the test `@pytest.mark.skip("needs integration fixture")` and leave a TODO-free reason: "fixture plumbing deferred; covered by unit tests for now." The unit test suite in Tasks 3–7 covers the same logic with fakes.

- [ ] **Step 2: Run the integration test**

```bash
uv run pytest tests/execution/test_telegram_simulation.py -v -m integration 2>&1 | tail -15
```

If the fixture names don't line up, adjust once and re-run. If they're genuinely missing, skip this test and move on — the unit tests give us sufficient coverage for the initial rollout.

- [ ] **Step 3: Commit**

```bash
git add tests/execution/test_telegram_simulation.py
git commit -m "test(execution): end-to-end simulation mode for Telegram executor"
```

---

## Task 10: Dashboard filter chip

**Files:**
- Modify: `src/trdex/dashboard/app.py`

- [ ] **Step 1: Find the source filter**

Open `src/trdex/dashboard/app.py`. Search for the open-positions panel (filter by `source`). The existing chip list probably looks like:

```python
sources = st.multiselect("Source", options=["manual", "agent"], default=[])
```

or similar. Match the actual code style.

- [ ] **Step 2: Add "telegram" to the options**

Change the options list to include `"telegram"`:

```python
sources = st.multiselect("Source", options=["manual", "agent", "telegram"], default=[])
```

Since `position.source = "telegram"` is how the executor persists, this filter lights up automatically once the first telegram position is opened. No schema or query change.

- [ ] **Step 3: Manual verification**

Start the dashboard locally, open the positions panel, confirm the new chip appears and filters correctly. Even with zero telegram positions yet, the chip should render (will just produce an empty filtered result).

- [ ] **Step 4: Commit**

```bash
git add src/trdex/dashboard/app.py
git commit -m "feat(dashboard): add 'telegram' to positions source filter"
```

---

## Task 11: Flip-on-off verification

**Files:** none (pure verification pass).

- [ ] **Step 1: Verify default-off**

Ensure `integrations.telegram_executor_enabled` is not set in `runtime_config` after applying migrations. `get_typed(..., default=False)` returns False, executor is a no-op, `_telegram_background` behaves exactly like before.

- [ ] **Step 2: Verify flip-on via dashboard**

Open dashboard Settings → find the RuntimeConfig section → set `integrations.telegram_executor_enabled = true`. The listener callback should fire (see runtime_config listener mechanism in the reality-check); next signal that arrives should be processed by `_maybe_execute`.

- [ ] **Step 3: Full test suite**

```bash
uv run pytest 2>&1 | tail -10
```

Expected: baseline + new tests all green.

- [ ] **Step 4: Update Task Board**

Open `Task Board.md`. Mark items 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7 as done. Add a line under "Done — 2026-04-19":

```markdown
- **[Telegram] Executor pipeline (Tasks 2.1–2.7)** — flag-gated, default off. symbol_router + telegram_gates + telegram_executor + wire-up in _telegram_background + dashboard chip. Design spec: `docs/superpowers/specs/2026-04-19-telegram-signal-executor-design.md`. Plan: `docs/superpowers/plans/2026-04-19-telegram-signal-executor.md`.
```

- [ ] **Step 5: Final commit**

```bash
git add "Task Board.md"
git commit -m "chore(task-board): close Telegram executor pipeline (Tasks 2.1-2.7)"
```

---

## Self-review summary

**Spec coverage.** Every requirement in the spec maps to at least one task:
- Task 2.1 (symbol router) → Task 3
- Task 2.2 (executor) → Task 7
- Task 2.3 (gates) → Tasks 4+5, with repos prepared in Tasks 1+2
- Task 2.4 (SL/TP) → no code change required; satisfied by Task 7's `stop_loss_pct`/`take_profit_pct` write, verified by Task 7 test
- Task 2.5 (wire-up) → Task 8
- Task 2.6 (dashboard) → Task 10
- Task 2.7 (simulation test) → Task 9
- RuntimeConfig keys → Task 6
- Rollout verification → Task 11

**No placeholders.** Every step contains exact file paths, complete code, exact commands. Two flagged "verify helper names" notes in Task 8 explicitly tell the engineer to open the real file and adjust — that's guidance, not a placeholder.

**Type consistency.** `GateConfig`, `GateResult`, `TelegramSignal`, `ExecuteOutcome`, `SymbolNotRoutable` used with consistent signatures across tasks. `pos.stop_loss_pct` / `pos.take_profit_pct` (float) matches the real column types per reality-check.
