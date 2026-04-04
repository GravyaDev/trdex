# Memory

## Now
- Phase 2 + Phase 3 completi, 48 test passing, tutto pushato
- Prossimo: Phase 4 (Portfolio tracker, dashboard) o Telegram live testing

## Project: trdex
- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 2 (AI Agents) + Phase 3 (Backtest) completati
- **Stack**: Python 3.12+, LangGraph, Qdrant, Jina (httpx), CCXT, asyncio, Pydantic v2, FastAPI, PG+TimescaleDB, Redis, polars==1.33.1 (lts-cpu), telethon
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)

## Architecture
- **AI Agent Layer**: LangGraph state machine, 4 agents (Scout, Analyst, Risk, Executor)
- **Context Ingestion**: News/social → Jina embeddings (httpx, 1024d COSINE) → Qdrant (self-hosted Docker v1.9.2)
- **Data Layer**: Binance REST (CCXT) + rate limiter convesso
- **Backtest Engine**: polars vectorised, RSI/MACD/Bollinger, Sharpe/drawdown/win rate
- **Storage**: TimescaleDB OHLCV hypertable, OHLCVRepository (upsert + fetch_polars)
- **Telegram**: parser segnali (IT+EN), SignalTracker P&L per fonte, TelegramMonitor (Telethon)
- **Execution**: Simulator (paper) + Live (gated Phase 5)

## Key Files
- `docs/architecture.md` — architettura completa
- `src/trdex/agents/graph.py` — LangGraph state machine
- `src/trdex/backtest/engine.py` — backtest vectorised
- `src/trdex/storage/ohlcv_repo.py` — OHLCV persistence
- `src/trdex/telegram/` — signal following
- `migrations/001_create_ohlcv.sql` — TimescaleDB migration

## Known Issues
- polars deve restare ==1.33.1 (lts-cpu) su Windows — polars>=1.35 ha cpu_check che fa VirtualAlloc bloccato da antivirus
- aiohttp non funziona nel venv (DLL rotta su Windows) — usiamo httpx ovunque
- telethon: pyaes si compila da source, install lento su Windows (lock uv)

## Backlog prioritario
- Phase 4: Portfolio tracker (posizioni, P&L), Streamlit dashboard MVP
- Telegram live: test con canali reali, whitelist/blacklist
- Seed script dati storici OHLCV
- Add app service to docker-compose.yaml
- Stop-loss hardware/software esterno all'AI
