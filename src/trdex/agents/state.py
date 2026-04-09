"""Shared state type for the LangGraph trading agent graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from trdex.agents.intent import Intent


@dataclass
class MarketSnapshot:
    """Price and OHLCV data for a symbol at a point in time."""

    symbol: str
    price: float
    timestamp: datetime = field(default_factory=lambda: datetime.now(tz=timezone.utc))
    volume_24h: float | None = None
    change_24h_pct: float | None = None
    # OHLCV candles: list of (ts, open, high, low, close, volume)
    candles: list[tuple[datetime, float, float, float, float, float]] = field(
        default_factory=list
    )


@dataclass
class SentimentContext:
    """Retrieved context documents from Qdrant."""

    items: list[dict] = field(default_factory=list)  # from ContextIngestionPipeline.query()
    summary: str = ""


@dataclass
class AnalysisResult:
    """Analyst agent output.

    ``intent`` is the post-refactor (2026-04-08) operational intent
    that downstream nodes act on. It is the canonical field; the legacy
    ``signal`` string has been removed — see brainstorm decision log
    ``.claude/reports/brainstorm-2026-04-07-intent-enum.md`` for the
    full rationale.
    """

    intent: Intent = Intent.HOLD
    confidence: float = 0.0           # 0.0 – 1.0
    reasoning: str = ""
    indicators: dict[str, float] = field(default_factory=dict)


@dataclass
class RiskDecision:
    """Risk manager output."""

    approved: bool = False
    reason: str = ""
    position_size: float = 0.0        # fraction of portfolio (0.0 – 1.0)
    stop_loss_pct: float = 0.02       # default 2%
    take_profit_pct: float = 0.04     # default 4%


@dataclass
class OrderResult:
    """Executor agent output."""

    order_id: str = ""
    status: Literal["filled", "rejected", "skipped", "pending"] = "skipped"
    filled_price: float | None = None
    filled_qty: float | None = None
    message: str = ""


@dataclass
class PortfolioContext:
    """Live portfolio state injected into the agent cycle for risk decisions."""

    equity: float = 0.0                # total equity (cash + unrealized P&L)
    open_position_symbols: list[str] = field(default_factory=list)  # all sources
    # D21: subset of ``open_position_symbols`` restricted to
    # ``positions.source = 'agent'``. The ``signal_to_intent`` translator
    # consults THIS list (not the full one) so the agent never tries to
    # close a position opened by another source (e.g. Telegram tracker).
    open_position_symbols_by_agent: list[str] = field(default_factory=list)
    unrealized_pnl: float = 0.0        # aggregate unrealized P&L across all open positions
    realized_pnl: float = 0.0          # total realized P&L (session)
    drawdown_pct: float = 0.0          # current drawdown from peak equity (0.0–1.0)


@dataclass
class AgentState:
    """Full mutable state passed through the LangGraph graph."""

    # Input
    symbol: str = ""
    run_id: str = ""

    # Populated by each node in sequence
    market: MarketSnapshot | None = None
    sentiment: SentimentContext = field(default_factory=SentimentContext)
    analysis: AnalysisResult = field(default_factory=AnalysisResult)
    risk: RiskDecision = field(default_factory=RiskDecision)
    order: OrderResult = field(default_factory=OrderResult)

    # Live portfolio context — injected by AgentRunner before the cycle
    portfolio: PortfolioContext = field(default_factory=PortfolioContext)

    # DB session factory — injected by AgentRunner, used by nodes to persist facts.
    # Not serialized by LangGraph (Any type, excluded from repr).
    session_factory: Any = field(default=None, repr=False)

    # Execution gateway — injected by AgentRunner. DefaultExecutionGateway if None.
    # Not serialized by LangGraph (Any type, excluded from repr).
    gateway: Any = field(default=None, repr=False)  # DefaultExecutionGateway | None

    # Memory context loader — injected by AgentRunner. MemoryContextLoader | None.
    # Used by nodes to read aggregated context from the 6-tier memory stack.
    memory_loader: Any = field(default=None, repr=False)

    # Pre-built memory snapshot text from the 6-tier stack, set by the first
    # node that loads it (typically Analyst). Downstream nodes can read it
    # without rebuilding. Kept for backward compatibility — equal to
    # ``memory_snapshots.get("analyst", "")`` after Analyst runs.
    memory_snapshot_text: str = ""

    # Per-agent memory snapshots populated as the cycle progresses.
    # Key = agent name (scout, analyst, risk, executor).
    # Value = MemoryContext.to_prompt_text() for that agent.
    memory_snapshots: dict[str, str] = field(default_factory=dict)

    # Control
    error: str | None = None
    completed_at: datetime | None = None
