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
from trdex.config import TrdexMode, settings
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


# Agent scheduler loop is now defined in trdex.agents.scheduler so it can
# be imported by smoke_level4 (and future tests) without spinning up the
# full FastAPI lifespan. The lifespan below imports it on demand.


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _telegram_task, _scheduler, _agent_task

    # --- Apply DB migrations (idempotent, self-healing on fresh deploys) ---
    # Must run before anything else touches the database. The migration
    # runner uses IF NOT EXISTS everywhere, so this is a no-op on already
    # migrated databases and completes in <1s. A fresh Coolify volume
    # would otherwise crash later with "relation \"positions\" does not
    # exist" because nothing else applies the schema.
    from trdex.scripts.apply_migrations import run_migrations
    rc = await run_migrations()
    if rc != 0:
        logger.critical("[lifespan] migration step failed (rc=%s) — aborting startup", rc)
        raise RuntimeError("database migrations failed; see logs above")
    logger.info("[lifespan] migrations applied (or already up to date)")

    # --- Ensure Qdrant context collection exists ---
    # ContextIngestionPipeline.ensure_collection() is idempotent. Calling
    # it here means the first news-ingestion tick (or Telegram signal)
    # doesn't race on collection creation.
    try:
        from trdex.context.vector_store import QdrantStore
        await QdrantStore().ensure_collection()
        logger.info("[lifespan] Qdrant collection ensured")
    except Exception as exc:
        # Non-fatal: Qdrant may be down in dev, or embeddings disabled.
        # The app can still run; only the context ingestion features
        # will degrade. News scheduler and Telegram task already guard
        # their own exceptions.
        logger.warning("[lifespan] Qdrant collection setup failed: %s", exc)

    # --- Session factory (needed early for tracker load) ---
    session_factory = get_session_factory()

    # --- Security checks ---
    if not settings.api_key:
        logger.warning(
            "[security] TRDEX_API_KEY is not set — API is unauthenticated. "
            "Set TRDEX_API_KEY before deploying to production."
        )
    if settings.mode != TrdexMode.SIMULATION and settings._uses_default_db_creds:
        logger.critical(
            "[security] REFUSING TO START in %s mode with default DB password "
            "'trdex:trdex'. Set a strong POSTGRES_PASSWORD in .env / Coolify.",
            settings.mode.value,
        )
        raise RuntimeError("Default DB credentials not allowed outside simulation mode")

    # --- Restore KillSwitch state from DB (survives restarts) ---
    from trdex.risk.stop_loss import get_kill_switch
    ks = get_kill_switch()
    ks.configure(session_factory)
    await ks.load_from_db()

    # --- Restore SignalTracker history from DB ---
    await _tracker.load_from_db(session_factory)

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

    # --- Load market specs (lot size, precision, min notional) ---
    # Must run after BinanceFeed is registered. Uses the underlying CCXT
    # exchange to call load_markets() once. The cached specs are used by
    # the Simulator and LiveExecutor to truncate quantities to valid
    # step sizes before placing orders.
    from trdex.market import specs as market_specs
    binance_feed = feed_manager.feeds.get("binance")
    if binance_feed:
        try:
            await market_specs.load(binance_feed._exchange)
        except Exception as exc:
            logger.warning("[lifespan] market specs load failed: %s — lot size truncation disabled", exc)

    # --- Execution gateway (shared by SL monitor + agent runner + routes) ---
    from trdex.execution.default_gateway import DefaultExecutionGateway
    gateway = DefaultExecutionGateway.create()

    from trdex.api.routes import portfolio as portfolio_routes
    from trdex.api.routes import agent as agent_routes
    portfolio_routes.set_service_factory(session_factory, feed_manager)
    agent_routes.set_agent_factory(session_factory, feed_manager, gateway=gateway)

    # Subscribe WS feed for existing open positions
    async with session_factory() as _session:
        from trdex.storage.portfolio_repo import PortfolioRepository
        _repo = PortfolioRepository(_session)
        _open = await _repo.get_open_positions()
        for _sym in {p.symbol for p in _open}:
            await ws_feed.subscribe_ticker(_sym)
            logger.info("[ws] subscribed %s", _sym)

    # --- Telegram streaming ---
    # Wrapped in try/except so a failing Telethon login (e.g. missing
    # session file on a fresh container that would otherwise prompt for
    # an SMS code on stdin and raise EOFError) degrades the Telegram
    # feature without crashing the whole app. Same soft-fail pattern
    # used for Qdrant above — Telegram is optional in Phase 2.
    channels = settings.telegram_channels_list
    monitor = None
    if channels and settings.telegram_api_id:
        try:
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
        except Exception as exc:
            logger.warning(
                "[telegram] startup failed, streaming disabled: %s", exc
            )
            monitor = None
            _telegram_task = None
    else:
        logger.info("[telegram] skipped — no channels configured")

    # --- News ingestion scheduler ---
    _scheduler = IngestionScheduler(interval_seconds=settings.ingestion_interval)
    if settings.cryptocompare_api_key:
        _scheduler.register(CryptoCompareNewsSource(api_key=settings.cryptocompare_api_key))
    if settings.stockdata_api_key:
        _scheduler.register(StockDataNewsSource(api_key=settings.stockdata_api_key))
    if settings.perplexity_api_key:
        from trdex.context.news_sources.perplexity import PerplexityNewsSource
        _scheduler.register(PerplexityNewsSource(api_key=settings.perplexity_api_key))
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
        gateway=gateway,
        check_interval=settings.sl_check_interval,
        position_sl_pct=settings.sl_position_pct,
        position_tp_pct=settings.sl_take_profit_pct,
        trailing_stop_pct=settings.sl_trailing_stop_pct,
        daily_drawdown_pct=settings.sl_daily_drawdown_pct,
        max_drawdown_pct=settings.gate_max_drawdown,
    )
    risk_routes.set_monitor(sl_monitor)
    risk_routes.set_session_factory(session_factory)
    await sl_monitor.start()

    # --- Agent scheduler ---
    agent_symbols = settings.agent_scheduler_symbols_list
    if settings.agent_scheduler_enabled and agent_symbols:
        from trdex.agents.scheduler import agent_scheduler_loop

        _agent_task = asyncio.create_task(
            agent_scheduler_loop(
                session_factory,
                feed_manager,
                agent_symbols,
                settings.agent_scheduler_interval,
                gateway=gateway,
                active_hours=settings.agent_scheduler_active_hours,
            ),
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
    WARNING: running without an API key exposes all endpoints to unauthenticated access.
    """
    if not settings.api_key:
        logger.warning(
            "[security] TRDEX_API_KEY is not set — all endpoints are unauthenticated (dev mode). "
            "Set TRDEX_API_KEY in production."
        )
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

    # --- API rate limiting (per client IP) ---
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    limiter = Limiter(key_func=get_remote_address, default_limits=["60/minute"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

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
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins else [],
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["X-API-Key"],
    )

    # --- Request logging middleware ---
    import hashlib
    import time as _time
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request as StarletteRequest
    from starlette.responses import Response as StarletteResponse

    class _RequestLoggingMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: StarletteRequest, call_next) -> StarletteResponse:
            start = _time.monotonic()
            response = await call_next(request)
            latency_ms = (_time.monotonic() - start) * 1000
            api_key = request.headers.get("X-API-Key", "")
            key_hash = hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else "none"
            logger.info(
                "[api] %s %s → %d (%.0fms) key=%s",
                request.method, request.url.path, response.status_code, latency_ms, key_hash,
            )
            return response

    app.add_middleware(_RequestLoggingMiddleware)

    # --- Public endpoints (no auth) ---

    @app.get("/", include_in_schema=False)
    async def root_redirect():
        from starlette.responses import RedirectResponse
        return RedirectResponse(url="/dashboard/")

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

    @app.get("/v1/system/readiness")
    async def system_readiness(_key: str = Depends(verify_api_key)) -> dict[str, object]:
        """Check whether the system meets simulation gate criteria for live trading.

        Returns a clear READY / NOT READY verdict with details on each criterion.
        """
        from trdex.risk.readiness import evaluate_readiness
        from trdex.storage.db import get_session_factory

        sf = get_session_factory()
        async with sf() as session:
            report = await evaluate_readiness(session, settings)

        return {
            "verdict": "READY" if report.ready else "NOT READY",
            "sim_days": report.sim_days,
            "total_trades": report.total_trades,
            "win_rate": report.win_rate,
            "sharpe": report.sharpe,
            "max_drawdown_pct": report.max_drawdown_pct,
            "kill_switch_events": report.kill_switch_events,
            "criteria": report.criteria,
            "failures": report.failures,
        }

    # --- Debug endpoints ---

    @app.get("/v1/debug/balance-ledger")
    async def balance_ledger(
        limit: int = 50,
        _key: str = Depends(verify_api_key),
    ) -> dict[str, object]:
        """Return the raw balance ledger (deposits, fills, fees)."""
        from trdex.storage.balance_repo import BalanceRepository
        from trdex.storage.db import get_session_factory

        sf = get_session_factory()
        async with sf() as session:
            repo = BalanceRepository(session)
            records = await repo.history(limit=min(limit, 500))

        return {
            "entries": [
                {
                    "id": r.id,
                    "event_type": r.event_type,
                    "amount": float(r.amount),
                    "balance_after": float(r.balance_after),
                    "note": r.note or "",
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                }
                for r in records
            ],
        }

    @app.get("/v1/debug/entity-graph")
    async def entity_graph(
        subject_type: str | None = None,
        subject_id: str | None = None,
        predicate: str | None = None,
        limit: int = 50,
        _key: str = Depends(verify_api_key),
    ) -> dict[str, object]:
        """Query active facts from the entity graph."""
        from trdex.storage.entity_graph_repo import EntityGraphRepository
        from trdex.storage.db import get_session_factory

        sf = get_session_factory()
        async with sf() as session:
            repo = EntityGraphRepository(session)
            facts = await repo.get_active(
                subject_type=subject_type,
                subject_id=subject_id,
                predicate=predicate,
            )

        return {
            "facts": [
                {
                    "id": f.id,
                    "subject_type": f.subject_type,
                    "subject_id": f.subject_id,
                    "predicate": f.predicate,
                    "object_value": f.object_value,
                    "confidence": f.confidence,
                    "source": f.source,
                    "valid_from": f.valid_from.isoformat() if f.valid_from else None,
                }
                for f in facts[:limit]
            ],
        }

    return app
