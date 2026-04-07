"""AgentRunner: assembles MarketSnapshot from DB + feed, then runs the agent cycle."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from trdex.agents.graph import run_agent_cycle
from trdex.agents.state import AgentState, MarketSnapshot, PortfolioContext
from trdex.market.manager import PriceFeedManager
from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.ohlcv_repo import OHLCVRepository
from trdex.storage.balance_repo import BalanceRepository
from trdex.storage.portfolio_repo import PortfolioRepository

logger = logging.getLogger(__name__)

_DEFAULT_TIMEFRAME = "1h"
_DEFAULT_CANDLES = 100


class AgentRunner:
    """Wires market data (OHLCV DB + live feed) into `run_agent_cycle()`.

    Usage:
        runner = AgentRunner(session, feed_manager)
        state = await runner.run("BTC/USDT")
    """

    def __init__(
        self,
        session: AsyncSession,
        feed_manager: PriceFeedManager,
        session_factory=None,
        gateway=None,
        memory_loader=None,
    ) -> None:
        self._session = session
        self._feeds = feed_manager
        self._ohlcv_repo = OHLCVRepository(session)
        self._session_factory = session_factory
        self._gateway = gateway
        self._memory_loader = memory_loader

    async def _load_portfolio_context(self) -> PortfolioContext:
        """Load live portfolio state from DB for risk gate decisions."""
        try:
            pos_repo = PortfolioRepository(self._session)
            bal_repo = BalanceRepository(self._session)

            open_positions = await pos_repo.get_open_positions()
            open_symbols = [p.symbol for p in open_positions]

            unrealized_pnl = sum(
                (float(p.exit_price or 0) - float(p.entry_price)) * float(p.amount)
                if p.side == "BUY"
                else (float(p.entry_price) - float(p.exit_price or 0)) * float(p.amount)
                for p in open_positions
            )

            # Cash balance from ledger (authoritative source)
            balance = float(await bal_repo.current_balance())
            peak_balance = float(await bal_repo.peak_balance())
            equity = balance + unrealized_pnl
            peak_equity = peak_balance  # peak is tracked via ledger entries at fill time
            drawdown_pct = max(0.0, (peak_equity - equity) / peak_equity) if peak_equity > 0 else 0.0

            return PortfolioContext(
                equity=equity,
                open_position_symbols=open_symbols,
                unrealized_pnl=unrealized_pnl,
                realized_pnl=balance - peak_balance,  # net change from peak
                drawdown_pct=drawdown_pct,
            )
        except Exception:
            logger.exception("[runner] failed to load portfolio context — using empty defaults")
            return PortfolioContext()

    async def run(
        self,
        symbol: str,
        timeframe: str = _DEFAULT_TIMEFRAME,
        candle_limit: int = _DEFAULT_CANDLES,
    ) -> AgentState:
        """Build MarketSnapshot and run one full agent cycle.

        Data priority:
        1. OHLCV candles from TimescaleDB (fastest, no rate-limit)
        2. Falls back to live feed if DB has no data for the symbol
        3. Current price always fetched live for accuracy
        """
        # 1. Fetch current price live
        try:
            ticker = await self._feeds.get_ticker(symbol)
            current_price = float(ticker.price)
        except Exception:
            logger.exception("[runner] failed to fetch live ticker for %s", symbol)
            current_price = 0.0

        # 2. Fetch OHLCV — prefer DB, fallback to live feed
        candles_raw: list[tuple[datetime, float, float, float, float, float]] = []
        try:
            records = await self._ohlcv_repo.fetch(symbol, timeframe, limit=candle_limit)
            if records:
                candles_raw = [
                    (r.timestamp, float(r.open), float(r.high), float(r.low),
                     float(r.close), float(r.volume))
                    for r in records
                ]
                logger.debug("[runner] loaded %d candles from DB for %s", len(candles_raw), symbol)
        except Exception:
            logger.exception("[runner] DB candle fetch failed for %s", symbol)

        if not candles_raw:
            try:
                live_candles = await self._feeds.get_ohlcv(symbol, timeframe, limit=candle_limit)
                candles_raw = [
                    (c.timestamp, float(c.open), float(c.high), float(c.low),
                     float(c.close), float(c.volume))
                    for c in live_candles
                ]
                logger.debug("[runner] loaded %d candles from live feed for %s", len(candles_raw), symbol)
            except Exception:
                logger.exception("[runner] live candle fetch also failed for %s", symbol)

        snapshot = MarketSnapshot(
            symbol=symbol,
            price=current_price,
            timestamp=datetime.now(tz=timezone.utc),
            candles=candles_raw,
        )

        # 3. Load portfolio context for risk gate decisions
        portfolio_ctx = await self._load_portfolio_context()

        # 4. Run agent cycle
        state = await run_agent_cycle(
            symbol=symbol,
            market_snapshot=snapshot,
            portfolio_context=portfolio_ctx,
            session_factory=self._session_factory,
            gateway=self._gateway,
            memory_loader=self._memory_loader,
        )

        # 4. Persist result
        await self._persist(state)

        return state

    async def _persist(self, state: AgentState) -> None:
        """Save agent run result to agent_runs table."""
        try:
            ran_at = (state.completed_at or datetime.now(tz=timezone.utc)).replace(tzinfo=None)
            record = AgentRunRecord(
                run_id=state.run_id,
                symbol=state.symbol,
                ran_at=ran_at,
                signal=state.analysis.signal,
                confidence=state.analysis.confidence,
                reasoning=state.analysis.reasoning,
                indicators=state.analysis.indicators,
                risk_approved=state.risk.approved,
                risk_reason=state.risk.reason,
                position_size=state.risk.position_size,
                stop_loss_pct=state.risk.stop_loss_pct,
                take_profit_pct=state.risk.take_profit_pct,
                order_status=state.order.status,
                filled_price=state.order.filled_price,
                filled_qty=state.order.filled_qty,
                order_message=state.order.message,
                error=state.error,
            )
            self._session.add(record)
            await self._session.commit()
            logger.info("[runner] persisted run_id=%s signal=%s order=%s",
                        state.run_id, state.analysis.signal, state.order.status)
        except Exception:
            logger.exception("[runner] failed to persist agent run for %s", state.symbol)
