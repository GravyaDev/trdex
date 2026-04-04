# Task Board

## Priority — Phase 2: AI Agent System (IMMEDIATA)
- [ ] Aggiungere dipendenze: langgraph, qdrant-client, jina SDK, polars
- [ ] Docker compose: aggiungere Qdrant
- [ ] Context Ingestion: Jina embeddings + Qdrant vector store
- [ ] LangGraph state machine: Scout → Analyst → Risk → Executor
- [ ] Scout Agent: news/sentiment monitoring
- [ ] Analyst Agent: technicals + LLM reasoning con RAG
- [ ] Risk Manager Agent: drawdown, stop-loss, block execution
- [ ] Executor Agent: order routing (sim/live)
- [ ] Implementare Binance REST feed (CCXT)
- [ ] End-to-end test: data → agents → simulated order

## This Week
- [ ] Simulator: raise ValueError when market order has no price
- [ ] Simulator: store orders in `_orders` on execute() so cancel() works
- [ ] Add Alembic to dev dependencies
- [ ] Pin TimescaleDB Docker image version
- [ ] Add app service to docker-compose.yaml
- [ ] Stop-loss hardware/software esterno all'AI

## Backlog — Telegram Signal Following
- [ ] TelegramMonitor: Telethon client, lettura messaggi gruppi pubblici
- [ ] Signal parser: estrai simbolo, direzione (BUY/SELL), target, stop-loss dal testo
- [ ] SignalTracker: budget fisso per segnalatore, P&L tracking per fonte
- [ ] Ingest segnali in Qdrant (source="telegram_signal") per contesto Scout
- [ ] Dashboard: whitelist/blacklist segnalatori, P&L per fonte

## Backlog
- [ ] Define `PositionSide` enum (replace plain str)
- [ ] Pass feed/strategy registries into create_app() for /status
- [ ] Add .env.example comment about db:5432 in Docker Compose
- [ ] Reject default DB creds in non-dev modes
- [ ] Wire rate limiter into PriceFeed implementations
- [ ] Implement DefaultExecutionGateway with sim/live routing + gate check
- [ ] Document simulator logging convention for live gateway
- [ ] Indicatori tecnici (RSI, MACD, Bollinger)
- [ ] Portfolio tracker (posizioni, P&L)
- [ ] Persistenza OHLCV su TimescaleDB
- [ ] Backtest engine + performance report
- [ ] Seed script dati storici
- [ ] Feed CoinGecko + ForexRateAPI
- [ ] FastAPI dashboard completa
- [ ] WebSocket feed Binance
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
