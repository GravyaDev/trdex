"""Shared state type for the LangGraph trading agent graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class MarketSnapshot:
    """Price and OHLCV data for a symbol at a point in time."""

    symbol: str
    price: float
    timestamp: datetime = field(default_factory=datetime.utcnow)
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
    """Analyst agent output."""

    signal: Literal["BUY", "SELL", "HOLD"] = "HOLD"
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
    status: Literal["filled", "rejected", "skipped"] = "skipped"
    filled_price: float | None = None
    filled_qty: float | None = None
    message: str = ""


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

    # Control
    error: str | None = None
    completed_at: datetime | None = None
