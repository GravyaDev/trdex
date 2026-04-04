# Task Board

## This Week
- [ ] Add Alembic to dev dependencies
- [ ] Pin TimescaleDB Docker image version
- [ ] Add app service to docker-compose.yaml
- [ ] Stop-loss hardware/software esterno all'AI

## Phase 4 — Dashboard & Portfolio
- [ ] Portfolio tracker (posizioni, P&L)
- [ ] Streamlit dashboard MVP
- [ ] Seed script dati storici OHLCV
- [ ] Feed CoinGecko + ForexRateAPI
- [ ] WebSocket feed Binance

## Telegram Signal Following (live)
- [ ] Test con canali reali (credenziali my.telegram.org)
- [ ] Ingest segnali in Qdrant (source="telegram_signal") per contesto Scout
- [ ] Dashboard: whitelist/blacklist segnalatori, P&L per fonte

## Backlog
- [ ] Define `PositionSide` enum (replace plain str)
- [ ] Pass feed/strategy registries into create_app() for /status
- [ ] Add .env.example comment about db:5432 in Docker Compose
- [ ] Reject default DB creds in non-dev modes
- [ ] Wire rate limiter into PriceFeed implementations
- [ ] Implement DefaultExecutionGateway with sim/live routing + gate check
- [ ] FastAPI dashboard completa
- [ ] Risk manager (position sizing, drawdown limits)
- [ ] Live executor (ordini reali, testnet first)
- [ ] Safety gates (max loss, kill switch)

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
