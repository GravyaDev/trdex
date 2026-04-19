"""FastAPI application factory."""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Request, Security
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
_telegram_eval_task: asyncio.Task[None] | None = None
_scheduler: IngestionScheduler | None = None
_agent_task: asyncio.Task[None] | None = None


async def _ingest_signal_to_qdrant(signal) -> None:
    """Embed a Telegram signal as context document and store in Qdrant."""
    from trdex.services.runtime_config import get_config_service
    _svc = get_config_service()
    if _svc is not None and not _svc.get_typed("integrations", "qdrant_embeddings_enabled", True):
        return
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


async def _ingest_news_to_qdrant(chat_id: str, text: str, timestamp) -> None:
    """Ingest a non-signal Telegram message as news context into Qdrant."""
    from trdex.services.runtime_config import get_config_service
    _svc = get_config_service()
    if _svc is not None and not _svc.get_typed("integrations", "qdrant_embeddings_enabled", True):
        return
    try:
        from trdex.context.ingestion import ContextIngestionPipeline
        from trdex.context.vector_store import ContextDocument

        doc = ContextDocument(
            text=text,
            source=f"telegram_news:{chat_id}",
            symbol="",  # news is not symbol-specific
            sentiment=0.0,
            published_at=timestamp,
        )
        pipeline = ContextIngestionPipeline()
        await pipeline.setup()
        await pipeline.ingest([doc])
        logger.debug("[telegram] ingested news from %s into Qdrant", chat_id)
    except Exception:
        logger.exception("[telegram] Qdrant news ingestion failed for chat %s", chat_id)


async def _telegram_background(
    monitor: TelegramMonitor,
    channels: list[str],
    session_factory,
) -> None:
    """Background task: stream ALL messages from Telegram channels.

    For each message:
    1. Try parse_signal(). If it succeeds AND is not a report → record
       as observe-only signal in signal_outcomes + ingest to Qdrant.
    2. If parse_signal() returns None (not a trading signal) → ingest
       the raw text as news context into Qdrant so Scout/Analyst agents
       can read market commentary, breaking news, and macro analysis.

    This dual flow means every channel contributes either signals OR
    context — nothing is wasted.
    """
    from collections import OrderedDict
    from decimal import Decimal
    from trdex.telegram.parser import parse_signal
    from trdex.telegram.tracker import SignalOutcome

    # Dedup: skip signals with the same (source, symbol, direction)
    # within a 60-second window. Prevents a spammy channel from
    # flooding signal_outcomes with duplicate records.
    _recent_signals: OrderedDict[str, float] = OrderedDict()
    DEDUP_WINDOW_S = 60.0

    def _is_duplicate(sig) -> bool:
        import time
        key = f"{sig.source}:{sig.symbol}:{sig.direction}"
        now = time.monotonic()
        # Prune old entries
        while _recent_signals and next(iter(_recent_signals.values())) < now - DEDUP_WINDOW_S:
            _recent_signals.popitem(last=False)
        if key in _recent_signals:
            return True
        _recent_signals[key] = now
        return False

    try:
        async for msg in monitor.stream_raw(channels):
            # Try to parse as a trading signal
            signal = parse_signal(msg.text, source=msg.chat_id)

            if signal is not None:
                # Dedup: skip if same source+symbol+direction in last 60s
                if _is_duplicate(signal):
                    logger.debug(
                        "[telegram] dedup: skipping %s %s from %s",
                        signal.direction, signal.symbol, signal.source,
                    )
                    continue

                # It's a trading signal — observe-only record
                logger.info(
                    "[telegram] %s %s from %s entry=%s",
                    signal.direction, signal.symbol, signal.source, signal.entry,
                )

                if signal.entry is None:
                    logger.debug(
                        "[telegram] skipping record for %s %s: no entry price",
                        signal.direction, signal.symbol,
                    )
                else:
                    import json
                    note_payload = json.dumps({
                        "targets": signal.targets,
                        "stop_loss": signal.stop_loss,
                    })
                    outcome = SignalOutcome(
                        source=signal.source,
                        symbol=signal.symbol,
                        direction=signal.direction,
                        entry_price=Decimal(str(signal.entry)),
                        exit_price=None,
                        budget=Decimal("0"),
                        executed_at=signal.parsed_at,
                    )
                    try:
                        from trdex.storage.signal_outcome_repo import (
                            SignalOutcomeRepository,
                        )
                        async with session_factory() as session:
                            repo = SignalOutcomeRepository(session)
                            await repo.save(
                                source=outcome.source,
                                symbol=outcome.symbol,
                                direction=outcome.direction,
                                entry_price=outcome.entry_price,
                                exit_price=None,
                                budget=Decimal("0"),
                                executed_at=outcome.executed_at,
                                closed_at=None,
                                note=note_payload,
                            )
                        _tracker.record(outcome)
                    except Exception:
                        logger.exception(
                            "[telegram] failed to record observe-only signal "
                            "%s %s from %s",
                            signal.direction, signal.symbol, signal.source,
                        )

                # Also ingest the signal as context
                await _ingest_signal_to_qdrant(signal)
            else:
                # Not a signal → ingest as news context
                # Skip very short messages (emoji-only, "👍", etc.)
                if len(msg.text.strip()) > 20:
                    await _ingest_news_to_qdrant(
                        msg.chat_id, msg.text, msg.timestamp,
                    )
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("[telegram] background task crashed")


# Agent scheduler loop is now defined in trdex.agents.scheduler so it can
# be imported by smoke_level4 (and future tests) without spinning up the
# full FastAPI lifespan. The lifespan below imports it on demand.


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _telegram_task, _telegram_eval_task, _scheduler, _agent_task

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

    # --- Runtime config: seed from env, then DB is source of truth ---
    from trdex.services.runtime_config import init_config_service, get_config_service
    config_svc = await init_config_service(session_factory, settings)
    # Seed the integration toggles on first boot (idempotent).
    # Default: components without API-key requirement → true;
    # components with API-key requirement → true iff a key is present.
    await config_svc.seed_integration_defaults(settings)

    def _enabled(component: str) -> bool:
        """Read an integration toggle. Defaults to True on a fresh DB
        (seed above has already run) so this is purely cosmetic; but
        kept defensive in case the seed was skipped for some reason."""
        return config_svc.get_typed("integrations", f"{component}_enabled", True)

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
    # Each feed is gated by an integration toggle from Runtime Config.
    # A feed that requires an API key needs BOTH the toggle on AND the
    # key present; key-less feeds only need the toggle.
    feed_manager = PriceFeedManager()
    if _enabled("binance_feed"):
        feed_manager.register(BinanceFeed())
    if _enabled("coingecko_feed"):
        feed_manager.register(CoinGeckoFeed(api_key=settings.coingecko_api_key))
    if _enabled("forex_feed") and settings.forex_api_key:
        feed_manager.register(ForexFeed(api_key=settings.forex_api_key))
    if _enabled("cryptocompare_feed") and settings.cryptocompare_api_key:
        feed_manager.register(CryptoCompareFeed(api_key=settings.cryptocompare_api_key))
    if _enabled("alphavantage_feed") and settings.alphavantage_api_key:
        feed_manager.register(AlphaVantageFeed(api_key=settings.alphavantage_api_key))
    # TwelveData: primary Forex/commodity feed. Key lives in Runtime
    # Config (credentials.twelve_data_api_key), dashboard-editable.
    twelve_data_key = config_svc.get("credentials", "twelve_data_api_key", "")
    if _enabled("twelvedata_feed") and twelve_data_key:
        from trdex.market.feeds.twelvedata import TwelveDataFeed
        feed_manager.register(TwelveDataFeed(api_key=twelve_data_key))
    # YFinance: free fallback for forex, commodities, and indices.
    if _enabled("yfinance_feed"):
        from trdex.market.feeds.yfinance import YFinanceFeed
        feed_manager.register(YFinanceFeed())
    if _enabled("freecryptoapi_feed") and settings.freecryptoapi_key:
        feed_manager.register(FreeCryptoAPIFeed(api_key=settings.freecryptoapi_key))
    ws_feed = None
    if _enabled("binance_ws_feed"):
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
    portfolio_routes.set_service_factory(session_factory, feed_manager, gateway=gateway)
    agent_routes.set_agent_factory(session_factory, feed_manager, gateway=gateway)

    # Subscribe WS feed for existing open positions (only when the WS
    # feed is enabled — otherwise we skip pre-subscription and fall back
    # to REST polling via BinanceFeed).
    if ws_feed is not None:
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
    # Read channels from RuntimeConfig (DB, dashboard-editable) with
    # fallback to the env var for backward compatibility.
    _tg_channels_csv = config_svc.get("telegram", "telegram_channels") or settings.telegram_channels
    channels = [c.strip() for c in _tg_channels_csv.split(",") if c.strip()] if _tg_channels_csv else []
    monitor = None
    if _enabled("telegram_monitor") and channels and settings.telegram_api_id:
        try:
            monitor = TelegramMonitor(
                api_id=settings.telegram_api_id,
                api_hash=settings.telegram_api_hash,
                phone=settings.telegram_phone,
            )
            await monitor.start()
            _telegram_task = asyncio.create_task(
                _telegram_background(monitor, channels, session_factory),
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

    # --- Telegram post-hoc TP/SL evaluator ---
    # Always-on background loop: scores open observe-only signals
    # against historical OHLCV every hour. Runs even when the monitor
    # is disabled so a restart can still resolve signals recorded in
    # earlier sessions. Cheap when there are no open rows.
    from trdex.telegram.evaluator import evaluator_loop
    _tg_eval_interval = config_svc.get_typed(
        "scheduler", "telegram_eval_interval", 3600,
    )
    _telegram_eval_task = asyncio.create_task(
        evaluator_loop(session_factory, feed_manager, _tg_eval_interval),
        name="telegram-evaluator",
    )
    logger.info(
        "[tg-eval] scheduled — interval=%ds", _tg_eval_interval,
    )

    # --- News ingestion scheduler ---
    # Read API keys and symbols from RuntimeConfig (DB-backed, dashboard-editable)
    _cc_key = config_svc.get("credentials", "cryptocompare_api_key")
    _sd_key = config_svc.get("credentials", "stockdata_api_key")
    _px_key = config_svc.get("credentials", "perplexity_api_key")
    _ing_syms_csv = config_svc.get("symbols", "ingestion_symbols")
    _ing_syms = [s.strip() for s in _ing_syms_csv.split(",") if s.strip()] if _ing_syms_csv else []
    _scheduler = IngestionScheduler(interval_seconds=config_svc.get_typed("scheduler", "ingestion_interval", settings.ingestion_interval))
    if _enabled("cryptocompare_news") and _cc_key:
        _scheduler.register(CryptoCompareNewsSource(api_key=_cc_key))
    if _enabled("stockdata_news") and _sd_key:
        _scheduler.register(StockDataNewsSource(api_key=_sd_key))
    if _enabled("perplexity_news") and _px_key:
        from trdex.context.news_sources.perplexity import PerplexityNewsSource
        _scheduler.register(PerplexityNewsSource(api_key=_px_key))
    _scheduler.set_symbols(_ing_syms)
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
        check_interval=config_svc.get_typed("scheduler", "sl_check_interval", settings.sl_check_interval),
        position_sl_pct=config_svc.get_typed("thresholds", "sl_position_pct", settings.sl_position_pct),
        position_tp_pct=config_svc.get_typed("thresholds", "sl_take_profit_pct", settings.sl_take_profit_pct),
        trailing_stop_pct=config_svc.get_typed("thresholds", "sl_trailing_stop_pct", settings.sl_trailing_stop_pct),
        daily_drawdown_pct=config_svc.get_typed("thresholds", "sl_daily_drawdown_pct", settings.sl_daily_drawdown_pct),
        max_drawdown_pct=config_svc.get_typed("thresholds", "gate_max_drawdown", settings.gate_max_drawdown),
    )
    risk_routes.set_monitor(sl_monitor)
    risk_routes.set_session_factory(session_factory)
    await sl_monitor.start()

    # --- Hot-reload listeners ---
    # When config changes via dashboard/API, update running components immediately.
    def _on_thresholds_change(key: str, value: str) -> None:
        attr_map = {
            "sl_position_pct": "_sl_pct",
            "sl_take_profit_pct": "_tp_pct",
            "sl_trailing_stop_pct": "_trailing_pct",
            "sl_daily_drawdown_pct": "_daily_dd_pct",
            "gate_max_drawdown": "_max_dd_pct",
        }
        if attr := attr_map.get(key):
            setattr(sl_monitor, attr, float(value))
            logger.info("[hot-reload] threshold %s → %s", key, value)

    def _on_symbols_change(key: str, value: str) -> None:
        from trdex.agents.scheduler import set_runtime_symbols
        sym_list = [s.strip() for s in value.split(",") if s.strip()]
        if key == "agent_scheduler_symbols":
            set_runtime_symbols(sym_list)
            logger.info("[hot-reload] agent symbols → %d symbols", len(sym_list))
        elif key == "ingestion_symbols":
            if _scheduler:
                _scheduler.set_symbols(sym_list)
            logger.info("[hot-reload] ingestion symbols → %d symbols", len(sym_list))

    def _on_feeds_change(key: str, value: str) -> None:
        from trdex.market.manager import set_selected_feeds
        if key == "selected_feeds":
            feed_list = [f.strip() for f in value.split(",") if f.strip()] if value else None
            set_selected_feeds(feed_list or [])
            logger.info("[hot-reload] selected feeds → %s", feed_list or "ALL")

    async def _resolve_and_store_titles(ch_list: list[str]) -> None:
        """Resolve each channel id/username to a human title and persist the
        map into runtime_config `telegram_channel_titles` (JSON). Best-effort
        — failures are logged but do not block the monitor hot-swap."""
        import json as _json
        try:
            titles = await monitor.resolve_titles(ch_list)
            await config_svc.put(
                "telegram", "telegram_channel_titles", _json.dumps(titles),
            )
            logger.info(
                "[hot-reload] telegram channel titles resolved — %d/%d",
                len(titles), len(ch_list),
            )
        except Exception:
            logger.exception("[hot-reload] failed to resolve telegram channel titles")

    def _on_telegram_change(key: str, value: str) -> None:
        if key == "telegram_channels" and monitor:
            ch_list = [c.strip() for c in value.split(",") if c.strip()]
            import asyncio as _aio
            try:
                loop = _aio.get_running_loop()
                loop.create_task(monitor.update_channels(ch_list))
                loop.create_task(_resolve_and_store_titles(ch_list))
                logger.info("[hot-reload] telegram channels → %d channels", len(ch_list))
            except RuntimeError:
                logger.warning("[hot-reload] no running loop for telegram update")

    # Integration toggles — hot-reload a feed/news source/telegram monitor
    # without a container restart. The listener is sync, so async work
    # (feed.close, monitor.start) is scheduled on the running loop via
    # create_task. A missing API key keeps the component off even when
    # the toggle flips to true — symmetric with the startup logic above.
    nonlocal_state = {"monitor": monitor, "ws_feed": ws_feed}

    def _on_integrations_change(key: str, value: str) -> None:
        if not key.endswith("_enabled"):
            return
        component = key[: -len("_enabled")]
        enabled = str(value).lower() in ("true", "1", "yes")
        import asyncio as _aio

        # ── Price feeds ──
        feed_registered_as = {
            "binance_feed": ("binance", lambda: BinanceFeed(), None),
            "coingecko_feed": (
                "coingecko",
                lambda: CoinGeckoFeed(api_key=settings.coingecko_api_key),
                None,
            ),
            "forex_feed": (
                "forex",
                lambda: ForexFeed(api_key=settings.forex_api_key),
                lambda: settings.forex_api_key,
            ),
            "cryptocompare_feed": (
                "cryptocompare",
                lambda: CryptoCompareFeed(api_key=settings.cryptocompare_api_key),
                lambda: settings.cryptocompare_api_key,
            ),
            "alphavantage_feed": (
                "alphavantage",
                lambda: AlphaVantageFeed(api_key=settings.alphavantage_api_key),
                lambda: settings.alphavantage_api_key,
            ),
            "twelvedata_feed": (
                "twelvedata",
                lambda: __import__(
                    "trdex.market.feeds.twelvedata", fromlist=["TwelveDataFeed"]
                ).TwelveDataFeed(
                    api_key=config_svc.get("credentials", "twelve_data_api_key", "")
                ),
                lambda: config_svc.get("credentials", "twelve_data_api_key", ""),
            ),
            "yfinance_feed": (
                "yfinance",
                lambda: __import__(
                    "trdex.market.feeds.yfinance", fromlist=["YFinanceFeed"]
                ).YFinanceFeed(),
                None,
            ),
            "freecryptoapi_feed": (
                "freecryptoapi",
                lambda: FreeCryptoAPIFeed(api_key=settings.freecryptoapi_key),
                lambda: settings.freecryptoapi_key,
            ),
        }
        if component in feed_registered_as:
            feed_name, builder, key_check = feed_registered_as[component]
            if enabled:
                if key_check is not None and not key_check():
                    logger.warning(
                        "[hot-reload] %s toggled on but API key empty — skipping",
                        component,
                    )
                    return
                if feed_name in feed_manager.feeds:
                    return
                try:
                    feed_manager.register(builder())
                    logger.info("[hot-reload] feed registered: %s", feed_name)
                except Exception:
                    logger.exception(
                        "[hot-reload] failed to register feed %s", feed_name
                    )
            else:
                feed_manager.unregister(feed_name)
            return

        # ── Binance WebSocket feed (special: tracks ws_feed for resubscribe) ──
        if component == "binance_ws_feed":
            if enabled:
                if "binance_ws" in feed_manager.feeds:
                    return
                try:
                    new_ws = BinanceWSFeed()
                    feed_manager.register(new_ws)
                    nonlocal_state["ws_feed"] = new_ws
                    logger.info("[hot-reload] feed registered: binance_ws")
                except Exception:
                    logger.exception("[hot-reload] failed to register binance_ws")
            else:
                feed_manager.unregister("binance_ws")
                nonlocal_state["ws_feed"] = None
            return

        # ── News sources ──
        news_map = {
            "cryptocompare_news": (
                "cryptocompare_news",
                lambda: CryptoCompareNewsSource(
                    api_key=config_svc.get("credentials", "cryptocompare_api_key", "")
                ),
                lambda: config_svc.get("credentials", "cryptocompare_api_key", ""),
            ),
            "stockdata_news": (
                "stockdata_news",
                lambda: StockDataNewsSource(
                    api_key=config_svc.get("credentials", "stockdata_api_key", "")
                ),
                lambda: config_svc.get("credentials", "stockdata_api_key", ""),
            ),
            "perplexity_news": (
                "perplexity_sonar",
                lambda: __import__(
                    "trdex.context.news_sources.perplexity",
                    fromlist=["PerplexityNewsSource"],
                ).PerplexityNewsSource(
                    api_key=config_svc.get("credentials", "perplexity_api_key", "")
                ),
                lambda: config_svc.get("credentials", "perplexity_api_key", ""),
            ),
        }
        if component in news_map:
            source_name, builder, key_check = news_map[component]
            if enabled:
                if key_check is not None and not key_check():
                    logger.warning(
                        "[hot-reload] %s toggled on but API key empty — skipping",
                        component,
                    )
                    return
                if any(s.name == source_name for s in _scheduler._sources):
                    return
                try:
                    _scheduler.register(builder())
                    if not _scheduler._running:
                        try:
                            loop = _aio.get_running_loop()
                            loop.create_task(_scheduler.start())
                        except RuntimeError:
                            logger.warning(
                                "[hot-reload] no running loop to start scheduler"
                            )
                    logger.info("[hot-reload] news source registered: %s", source_name)
                except Exception:
                    logger.exception(
                        "[hot-reload] failed to register news source %s", source_name
                    )
            else:
                _scheduler.unregister(source_name)
            return

        # ── Telegram monitor ──
        # Guards rapid-fire on/off toggles that would otherwise spawn a
        # second MTProto session before the first has finished shutting
        # down. nonlocal_state["monitor"] has four states:
        #   None          — not running
        #   "starting"    — start_monitor() scheduled, Telethon handshake in flight
        #   <Monitor obj> — running
        #   "stopping"    — stop() awaiting Telethon disconnect
        if component == "telegram_monitor":
            current = nonlocal_state.get("monitor")
            if enabled:
                if current is not None:
                    # Already running, starting, or stopping — in any non-None
                    # state a new start is unsafe. "stopping" in particular
                    # must wait for the disconnect to clear nonlocal_state.
                    return
                if not settings.telegram_api_id:
                    logger.warning(
                        "[hot-reload] telegram_monitor toggled on but telegram_api_id not set"
                    )
                    return
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    logger.warning(
                        "[hot-reload] no running loop for telegram monitor start"
                    )
                    return

                nonlocal_state["monitor"] = "starting"

                async def _start_monitor() -> None:
                    try:
                        m = TelegramMonitor(
                            api_id=settings.telegram_api_id,
                            api_hash=settings.telegram_api_hash,
                            phone=settings.telegram_phone,
                        )
                        await m.start()
                        # If a concurrent toggle-off flipped us to "stopping"
                        # or back to None during the handshake, tear the new
                        # monitor down instead of leaking a second session.
                        if nonlocal_state.get("monitor") != "starting":
                            await m.stop()
                            logger.info(
                                "[hot-reload] telegram monitor aborted post-start "
                                "(concurrent toggle-off)"
                            )
                            return
                        nonlocal_state["monitor"] = m
                        logger.info("[hot-reload] telegram monitor started")
                    except Exception:
                        nonlocal_state["monitor"] = None
                        logger.exception(
                            "[hot-reload] telegram monitor start failed"
                        )

                loop.create_task(_start_monitor())
            else:
                # Not a real instance → nothing to stop.
                if current is None or isinstance(current, str):
                    # "starting" → flip to None so the in-flight start sees
                    # the abort signal. "stopping" → already stopping.
                    if current == "starting":
                        nonlocal_state["monitor"] = None
                    return
                try:
                    loop = _aio.get_running_loop()
                except RuntimeError:
                    logger.warning(
                        "[hot-reload] no running loop to stop telegram monitor"
                    )
                    return
                nonlocal_state["monitor"] = "stopping"

                async def _stop_monitor(m: TelegramMonitor) -> None:
                    try:
                        await m.stop()
                        logger.info("[hot-reload] telegram monitor stopped")
                    except Exception:
                        logger.exception(
                            "[hot-reload] telegram monitor stop failed"
                        )
                    finally:
                        # Clear the sentinel only after disconnect completes
                        # — this is what lets a subsequent toggle-on proceed.
                        if nonlocal_state.get("monitor") == "stopping":
                            nonlocal_state["monitor"] = None

                loop.create_task(_stop_monitor(current))
            return

    config_svc.register_listener("thresholds", _on_thresholds_change)
    config_svc.register_listener("symbols", _on_symbols_change)
    config_svc.register_listener("feeds", _on_feeds_change)
    config_svc.register_listener("telegram", _on_telegram_change)
    config_svc.register_listener("integrations", _on_integrations_change)

    # --- Agent scheduler ---
    _sched_syms_csv = config_svc.get("symbols", "agent_scheduler_symbols")
    agent_symbols = [s.strip() for s in _sched_syms_csv.split(",") if s.strip()] if _sched_syms_csv else settings.agent_scheduler_symbols_list
    _sched_enabled = config_svc.get_typed("scheduler", "agent_scheduler_enabled", settings.agent_scheduler_enabled)
    if _sched_enabled and agent_symbols:
        from trdex.agents.scheduler import agent_scheduler_loop

        _sched_interval = config_svc.get_typed("scheduler", "agent_scheduler_interval", settings.agent_scheduler_interval)
        _sched_hours = config_svc.get("scheduler", "agent_scheduler_active_hours") or settings.agent_scheduler_active_hours
        _agent_task = asyncio.create_task(
            agent_scheduler_loop(
                session_factory,
                feed_manager,
                agent_symbols,
                _sched_interval,
                gateway=gateway,
                active_hours=_sched_hours,
            ),
            name="agent-scheduler",
        )
        logger.info("[AgentScheduler] started — symbols=%s interval=%ds", agent_symbols, _sched_interval)
    else:
        logger.info("[AgentScheduler] disabled — set TRDEX_AGENT_SCHEDULER_ENABLED=true to enable")

    # Expose lifespan-scoped objects to endpoints via app.state
    _app.state.feed_manager = feed_manager
    _app.state.agent_symbols = agent_symbols if _sched_enabled else []
    _app.state.telegram_channels = channels

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
    if _telegram_eval_task:
        _telegram_eval_task.cancel()
        await asyncio.gather(_telegram_eval_task, return_exceptions=True)
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

    # --- API rate limiting (per real client IP) ---
    from slowapi import Limiter, _rate_limit_exceeded_handler
    from slowapi.util import get_remote_address
    from slowapi.errors import RateLimitExceeded

    def _real_client_ip(request) -> str:
        """Read the real client IP from X-Forwarded-For (set by Traefik).

        Behind a reverse proxy, get_remote_address returns the proxy IP
        so all clients share one bucket — effectively no rate limiting.
        """
        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()
        return get_remote_address(request)

    limiter = Limiter(key_func=_real_client_ip, default_limits=["60/minute"])
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    from trdex.api.routes.portfolio import router as portfolio_router
    from trdex.api.routes.context import router as context_router
    from trdex.api.routes.agent import router as agent_router
    from trdex.api.routes.risk import router as risk_router
    from trdex.api.routes.settings import router as settings_router
    app.include_router(portfolio_router)
    app.include_router(context_router)
    app.include_router(agent_router)
    app.include_router(risk_router)
    app.include_router(settings_router)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()] if settings.cors_origins else [],
        allow_methods=["GET", "POST", "PUT", "DELETE"],
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
    async def status(request: Request, _key: str = Depends(verify_api_key)) -> dict[str, object]:
        _fm = getattr(request.app.state, "feed_manager", None)
        _as = getattr(request.app.state, "agent_symbols", [])
        return {
            "mode": settings.mode.value,
            "version": __version__,
            "timestamp": datetime.now(UTC).isoformat(),
            "feeds": {name: type(feed).__name__ for name, feed in _fm.feeds.items()} if _fm else {},
            "ingestion": {
                "active": _scheduler is not None and _scheduler._running,
                "sources": [type(s).__name__ for s in _scheduler._sources] if _scheduler else [],
                "symbols": _scheduler._symbols if _scheduler else [],
            },
            "agent_scheduler": {
                "active": _agent_task is not None and not _agent_task.done(),
                "symbols": _as,
            },
            "telegram": {
                "streaming": _telegram_task is not None and not _telegram_task.done(),
                "channels": getattr(request.app.state, "telegram_channels", []),
                "signals_tracked": len(_tracker._outcomes),
                "evaluator_running": (
                    _telegram_eval_task is not None
                    and not _telegram_eval_task.done()
                ),
            },
        }

    @app.get("/v1/signals")
    async def signals(_key: str = Depends(verify_api_key)) -> dict[str, object]:
        """Signal tracker report + recent outcomes for the dashboard.

        Response shape:
          {
            "report": [{source, total_signals, open_signals,
                        closed_signals, wins, losses, total_pnl,
                        budget_allocated, win_rate, roi_pct}, ...],
            "recent": [{id, source, symbol, direction, entry_price,
                        exit_price, budget, executed_at, closed_at,
                        status}, ...]
          }
        `recent` is the last 50 outcomes from the DB, ordered by
        executed_at desc. `status` is "open" | "tp" | "sl" | "stale"
        — derived from exit_price presence and the note payload.
        """
        report_rows: list[dict[str, object]] = []
        for stats in _tracker.report():
            report_rows.append({
                "source": stats.source,
                "total_signals": stats.total_signals,
                "open_signals": stats.open_signals,
                "closed_signals": stats.closed_signals,
                "wins": stats.wins,
                "losses": stats.losses,
                "total_pnl": float(stats.total_pnl),
                "budget_allocated": float(stats.budget_allocated),
                "win_rate": round(stats.win_rate, 4),
                "roi_pct": float(stats.roi_pct),
            })

        recent: list[dict[str, object]] = []
        try:
            import json as _json
            from trdex.storage.signal_outcome_repo import SignalOutcomeRepository
            sf = get_session_factory()
            async with sf() as session:
                repo = SignalOutcomeRepository(session)
                records = await repo.all(limit=50)
            for r in reversed(records):  # newest first
                status = "open"
                if r.exit_price is not None:
                    try:
                        note_payload = _json.loads(r.note) if r.note else {}
                        status = note_payload.get("resolution", "closed")
                    except (ValueError, TypeError):
                        status = "closed"
                recent.append({
                    "id": r.id,
                    "source": r.source,
                    "symbol": r.symbol,
                    "direction": r.direction,
                    "entry_price": float(r.entry_price),
                    "exit_price": float(r.exit_price) if r.exit_price is not None else None,
                    "budget": float(r.budget) if r.budget is not None else 0.0,
                    "executed_at": r.executed_at.isoformat() if r.executed_at else None,
                    "closed_at": r.closed_at.isoformat() if r.closed_at else None,
                    "status": status,
                })
        except Exception:
            logger.exception("[/v1/signals] failed to load recent outcomes")

        return {"report": report_rows, "recent": recent}

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
        if settings.mode != TrdexMode.SIMULATION:
            raise HTTPException(status_code=403, detail="Debug endpoints disabled outside simulation mode")
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
        if settings.mode != TrdexMode.SIMULATION:
            raise HTTPException(status_code=403, detail="Debug endpoints disabled outside simulation mode")
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
