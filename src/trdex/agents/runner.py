"""AgentRunner: assembles MarketSnapshot from DB + feed, then runs the agent cycle."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from trdex.agents.graph import run_agent_cycle
from trdex.agents.state import AgentState, MarketSnapshot
from trdex.market.manager import PriceFeedManager
from trdex.storage.agent_run_models import AgentRunRecord
from trdex.storage.ohlcv_repo import OHLCVRepository

logger = logging.getLogger(__name__)

_DEFAULT_TIMEFRAME = "1h"
_DEFAULT_CANDLES = 100


class AgentRunner:
    """Wires market data (OHLCV DB + live feed) into `run_agent_cycle()`.

    Usage:
        runner = AgentRunner(session, feed_manager)
        state = await runner.run("BTC/USDT")
    """

    def __init__(self, session: AsyncSession, feed_manager: PriceFeedManager) -> None:
        self._session = session
        self._feeds = feed_manager
        self._ohlcv_repo = OHLCVRepository(session)

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

        # 3. Run agent cycle
        state = await run_agent_cycle(symbol=symbol, market_snapshot=snapshot)

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
