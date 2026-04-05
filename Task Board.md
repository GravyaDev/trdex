# Task Board

## Priority Fix — Audit 2026-04-05 (P0)
- [ ] Add `verify_api_key` to kill-switch endpoints (`risk.py:43-56`)
- [ ] Add `verify_api_key` to `/v1/agent/run`, `/v1/agent/history`, all `/v1/context/*` state-changing endpoints
- [ ] Fix session leak in portfolio routes (`portfolio.py:32` — no context manager)
- [ ] Add 18 missing env vars to `.env.example` (TRDEX_AGENT_SCHEDULER_*, TRDEX_SL_*, TRDEX_INGESTION_*, etc.)

## This Week — Audit 2026-04-05 (P1)
- [ ] Add `asyncio.Lock` to `KillSwitch` (concurrent activate/reset race)
- [ ] Replace `stream()` queue polling with `asyncio.Queue.get()` in TelegramMonitor
- [ ] Add ORM `default=` for `opened_at`/`ran_at` timestamps (silent insert failure risk)
- [ ] Unify `DeclarativeBase` — import from `db.py` in `agent_run_models.py`
- [ ] Replace `datetime.utcnow()` with `datetime.now(tz=timezone.utc)` in `agents/state.py`
- [ ] Add healthcheck to `app` service in docker-compose
- [ ] Fix DB URL in `.env.example` (`db:5432` for Docker)
- [ ] Create `post()` wrapper in dashboard (bypasses `base_url` on POST calls)

## This Week
- [x] Add Alembic to dev dependencies (2026-04-05)
- [x] Pin TimescaleDB Docker image version → 2.17.2-pg16 (2026-04-05)
- [x] Add app service to docker-compose.yaml (2026-04-05)
- [x] Stop-loss esterno all'AI — StopLossMonitor + KillSwitch (2026-04-05)

## Phase 5 — Information Sources + Agent Loop
- [x] CryptoCompareFeed, AlphaVantageFeed, FreeCryptoAPIFeed (2026-04-05)
- [x] CryptoCompareNewsSource + StockDataNewsSource → Qdrant (2026-04-05)
- [x] IngestionScheduler — fetch periodico news → embed → Qdrant (2026-04-05)
- [x] AgentRunner — OHLCV DB → MarketSnapshot → run_agent_cycle() (2026-04-05)
- [x] AgentRunRecord ORM + migration 003 (2026-04-05)
- [x] Agent scheduler automatico (TRDEX_AGENT_SCHEDULER_ENABLED) (2026-04-05)
- [x] Telegram signals → Qdrant (source="telegram_signal") (2026-04-05)
- [x] Dashboard: Agent Decisions + Risk Monitor (2026-04-05)
- [x] API: /v1/agent/run, /v1/agent/history, /v1/risk/*, /v1/context/* (2026-04-05)

## Phase 4 — Dashboard & Portfolio
- [x] Portfolio tracker (posizioni, P&L) — PositionRecord ORM + PortfolioRepository + PortfolioService (2026-04-05)
- [x] Streamlit dashboard MVP — src/trdex/dashboard/app.py (2026-04-05)
- [x] Seed script dati storici OHLCV — scripts/seed_ohlcv.py (2026-04-05)
- [x] Feed CoinGecko + ForexRateAPI — market/feeds/coingecko.py + forex.py (2026-04-05)
- [x] WebSocket feed Binance — market/feeds/binance_ws.py, ccxt.pro (2026-04-05)

## Telegram Signal Following (live)
- [ ] Test con canali reali (credenziali my.telegram.org)
- [ ] Dashboard: whitelist/blacklist segnalatori, P&L per fonte

## Backlog
- [ ] Define `PositionSide` enum (replace plain str)
- [ ] Pass feed/strategy registries into create_app() for /status
- [ ] Add .env.example comment about db:5432 in Docker Compose
- [ ] Reject default DB creds in non-dev modes
- [ ] Wire rate limiter into PriceFeed implementations
- [ ] Implement DefaultExecutionGateway with sim/live routing + gate check
- [ ] Live executor (ordini reali, testnet first)

## Done
- [x] Onboarding + Kloudify setup (2026-04-04)
- [x] Stack decision: Python 3.12+, uv, CCXT, asyncio, Pydantic, FastAPI, PG+TimescaleDB, Redis (2026-04-04)
- [x] Architecture doc: `docs/architecture.md` (2026-04-04)
- [x] Phase 1 scaffold: 38 .py files, 20 tests passing, lint clean (2026-04-04)
- [x] Deep audit: 34 PASS / 19 WARN / 4 FAIL (2026-04-04)
- [x] Fix F1-F4: error handling, auth, API versioning, ConfigurationError (2026-04-04)
- [x] Architecture update: AI Agent System + Qdrant + Jina + polars (2026-04-04)
- [x] Phase 2: LangGraph + 4 agents + Qdrant + Jina + Binance feed (2026-04-04)
- [x] Simulator fixes: ValueError + _orders storage (2026-04-04)
- [x] Telegram: parser segnali, SignalTracker, TelegramMonitor (2026-04-04)
- [x] Phase 3: RSI/MACD/Bollinger + backtest engine (polars) (2026-04-04)
- [x] Phase 3: OHLCV persistence su TimescaleDB (2026-04-04)
- [x] Telegram live: login + fetch_recent funzionante (2026-04-05)
- [x] TelegramMonitor: context manager + telegram_channels_list (2026-04-05)
- [x] FastAPI: Telegram background stream + /v1/signals (2026-04-05)
- [x] Phase 4: Portfolio tracker + Dashboard + Feeds + WS (2026-04-05)
