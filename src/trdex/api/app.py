"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import APIKeyHeader

from trdex import __version__
from trdex.config import settings
from trdex.context.news_sources.cryptocompare import CryptoCompareNewsSource
from trdex.context.news_sources.stockdata import StockDataNewsSource
from trdex.context.scheduler import IngestionScheduler
from trdex.market.feeds.alphavantage import AlphaVantageFeed
from trdex.market.feeds.binance import BinanceFeed
from trdex.market.feeds.binance_ws import BinanceWSFeed
from trdex.market.feeds.coingecko import CoinGeckoFeed
from trdex.market.feeds.cryptocompare import CryptoCompareFeed
from trdex.market.feeds.forex import ForexFeed
from trdex.market.feeds.freecryptoapi import FreeCryptoAPIFeed
from trdex.market.manager import PriceFeedManager
from trdex.storage.db import get_session_factory
from trdex.telegram.monitor import TelegramMonitor
from trdex.telegram.tracker import SignalTracker

logger = logging.getLogger(__name__)

API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)

# Shared state — populated by the background task, read by /v1/signals
_tracker = SignalTracker()
_telegram_task: asyncio.Task[None] | None = None
_scheduler: IngestionScheduler | None = None
_agent_task: asyncio.Task[None] | None = None


async def _ingest_signal_to_qdrant(signal) -> None:
    """Embed a Telegram signal as context document and store in Qdrant."""
    try:
        from trdex.context.ingestion import ContextIngestionPipeline
        from trdex.context.vector_store import ContextDocument
        from datetime import timezone

        text = (
            f"Telegram signal: {signal.direction} {signal.symbol} "
            f"entry={signal.entry} targets={signal.targets} stop={signal.stop_loss}\n"
            f"Raw: {signal.raw_text}"
        )
        doc = ContextDocument(
            text=text,
            source="telegram_signal",
            symbol=signal.symbol,
            sentiment=0.6 if signal.direction == "BUY" else -0.6,
            published_at=__import__("datetime").datetime.now(tz=timezone.utc),
        )
        pipeline = ContextIngestionPipeline()
        await pipeline.setup()
        await pipeline.ingest([doc])
        logger.debug("[telegram] ingested signal for %s into Qdrant", signal.symbol)
    except Exception:
        logger.exception("[telegram] Qdrant ingestion failed for signal %s", getattr(signal, "symbol", "?"))


async def _telegram_background(monitor: TelegramMonitor, channels: list[str]) -> None:
    """Background task: stream signals from Telegram, track P&L, ingest into Qdrant."""
    try:
        async for signal in monitor.stream(channels):
            logger.info(
                "[telegram] %s %s from %s entry=%s",
                signal.direction, signal.symbol, signal.source, signal.entry,
            )
            # Ingest signal into Qdrant so Scout agent can read it as context
            await _ingest_signal_to_qdrant(signal)
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("[telegram] background task crashed")


async def _agent_scheduler_loop(session_factory, feed_manager, symbols: list[str], interval: int) -> None:
    """Background loop: run agent cycle for each symbol every `interval` seconds."""
    from trdex.agents.runner import AgentRunner
    from trdex.risk.stop_loss import get_kill_switch
    while True:
        try:
            if get_kill_switch().active:
                logger.warning("[AgentScheduler] kill switch active — skipping cycle")
            else:
                for sym in symbols:
                    try:
                        async with session_factory() as session:
                            runner = AgentRunner(session, feed_manager)
                            state = await runner.run(sym)
                            logger.info(
                                "[AgentScheduler] %s → signal=%s order=%s",
                                sym, state.analysis.signal, state.order.status,
                            )
                    except Exception:
                        logger.exception("[AgentScheduler] cycle failed for %s", sym)
        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("[AgentScheduler] unexpected error")
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            break


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _telegram_task, _scheduler, _agent_task

    # --- Price feed manager ---
    feed_manager = PriceFeedManager()
    feed_manager.register(BinanceFeed())
    feed_manager.register(CoinGeckoFeed(api_key=settings.coingecko_api_key))
    if settings.forex_api_key:
        feed_manager.register(ForexFeed(api_key=settings.forex_api_key))
    if settings.cryptocompare_api_key:
        feed_manager.register(CryptoCompareFeed(api_key=settings.cryptocompare_api_key))
    if settings.alphavantage_api_key:
        feed_manager.register(AlphaVantageFeed(api_key=settings.alphavantage_api_key))
    feed_manager.register(FreeCryptoAPIFeed(api_key=settings.freecryptoapi_key))
    ws_feed = BinanceWSFeed()
    feed_manager.register(ws_feed)

    # --- Portfolio service (session created per-call inside the service) ---
    session_factory = get_session_factory()

    from trdex.api.routes import portfolio as portfolio_routes
    from trdex.api.routes import agent as agent_routes
    portfolio_routes.set_service_factory(session_factory, feed_manager)
    agent_routes.set_agent_factory(session_factory, feed_manager)

    # Subscribe WS feed for existing open positions
    async with session_factory() as _session:
        from trdex.storage.portfolio_repo import PortfolioRepository
        _repo = PortfolioRepository(_session)
        _open = await _repo.get_open_positions()
        for _sym in {p.symbol for p in _open}:
            await ws_feed.subscribe_ticker(_sym)
            logger.info("[ws] subscribed %s", _sym)

    # --- Telegram streaming ---
    channels = settings.telegram_channels_list
    if channels and settings.telegram_api_id:
        monitor = TelegramMonitor(
            api_id=settings.telegram_api_id,
            api_hash=settings.telegram_api_hash,
            phone=settings.telegram_phone,
        )
        await monitor.start()
        _telegram_task = asyncio.create_task(
            _telegram_background(monitor, channels),
            name="telegram-stream",
        )
        logger.info("[telegram] streaming %d channels", len(channels))
    else:
        monitor = None
        logger.info("[telegram] skipped — no channels configured")

    # --- News ingestion scheduler ---
    _scheduler = IngestionScheduler(interval_seconds=settings.ingestion_interval)
    if settings.cryptocompare_api_key:
        _scheduler.register(CryptoCompareNewsSource(api_key=settings.cryptocompare_api_key))
    if settings.stockdata_api_key:
        _scheduler.register(StockDataNewsSource(api_key=settings.stockdata_api_key))
    _scheduler.set_symbols(settings.ingestion_symbols_list)
    from trdex.api.routes import context as context_routes
    context_routes.set_scheduler(_scheduler)
    if _scheduler._sources:
        await _scheduler.start()
        logger.info("[scheduler] news ingestion active — %d sources", len(_scheduler._sources))
    else:
        logger.info("[scheduler] skipped — no news API keys configured")

    # --- Stop-loss monitor ---
    from trdex.risk.stop_loss import StopLossMonitor
    from trdex.api.routes import risk as risk_routes
    sl_monitor = StopLossMonitor(
        session_factory=session_factory,
        feed_manager=feed_manager,
        check_interval=settings.sl_check_interval,
        position_sl_pct=settings.sl_position_pct,
        position_tp_pct=settings.sl_take_profit_pct,
        daily_drawdown_pct=settings.sl_daily_drawdown_pct,
        max_drawdown_pct=settings.gate_max_drawdown,
    )
    risk_routes.set_monitor(sl_monitor)
    await sl_monitor.start()

    # --- Agent scheduler ---
    agent_symbols = settings.agent_scheduler_symbols_list
    if settings.agent_scheduler_enabled and agent_symbols:
        _agent_task = asyncio.create_task(
            _agent_scheduler_loop(session_factory, feed_manager, agent_symbols, settings.agent_scheduler_interval),
            name="agent-scheduler",
        )
        logger.info("[AgentScheduler] started — symbols=%s interval=%ds", agent_symbols, settings.agent_scheduler_interval)
    else:
        logger.info("[AgentScheduler] disabled — set TRDEX_AGENT_SCHEDULER_ENABLED=true to enable")

    yield  # app runs here

    if _agent_task:
        _agent_task.cancel()
        await asyncio.gather(_agent_task, return_exceptions=True)
    await sl_monitor.stop()
    if _scheduler:
        await _scheduler.stop()
    if _telegram_task:
        _telegram_task.cancel()
        await asyncio.gather(_telegram_task, return_exceptions=True)
    if monitor:
        await monitor.stop()
    await feed_manager.close_all()


async def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> str:
    """Verify API key for authenticated endpoints.

    If TRDEX_API_KEY is not set, authentication is disabled (dev mode).
    """
    if not settings.api_key:
        return "dev-mode"
    if not api_key or not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(status_code=403, detail="Invalid or missing API key")
    return api_key


def create_app() -> FastAPI:
    app = FastAPI(
        title="trdex",
        version=__version__,
        description="Trading automation platform — AI-driven crypto, FX, multi-asset",
        lifespan=_lifespan,
    )

    from trdex.api.routes.portfolio import router as portfolio_router
    from trdex.api.routes.context import router as context_router
    from trdex.api.routes.agent import router as agent_router
    from trdex.api.routes.risk import router as risk_router
    app.include_router(portfolio_router)
    app.include_router(context_router)
    app.include_router(agent_router)
    app.include_router(risk_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.cors_origins] if settings.cors_origins else [],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key"],
    )

    # --- Public endpoints (no auth) ---

    @app.get("/v1/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # --- Authenticated endpoints ---

    @app.get("/v1/status")
    async def status(_key: str = Depends(verify_api_key)) -> dict[str, object]:
        return {
            "mode": settings.mode.value,
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "feeds": {},
            "strategies": {},
            "telegram": {
                "streaming": _telegram_task is not None and not _telegram_task.done(),
                "channels": settings.telegram_channels_list,
            },
        }

    @app.get("/v1/signals")
    async def signals(_key: str = Depends(verify_api_key)) -> dict[str, object]:
        """Returns signal tracker report: P&L per source."""
        return {"report": _tracker.report()}

    return app
