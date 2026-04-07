# Memory

## Now
- Sessione 2026-04-06 completa. Tier 1 + Tier 2 hardening implementati, 165/165 test passing.
- Multi-agent brainstorming approvato con 13 revisioni applicate.
- 3 report comparativi prodotti (repo riferimento, API, trading vs HFT).
- Trading Knowledge Base agent-ready in `Riferimenti/agents/` (5 file: scout, analyst, risk_manager, executor, stop_loss_monitor + INDEX).
- Piano 6-tier persistent memory architettato — DA INIZIARE domani con Phase 1.
- Prossima sessione: implementare Phase 1 del modello a 6 tier (Tier 1 loader + Tier 6 repo + Tier 2 schema/repo).

## Project: trdex
- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 2+3+4+5 completati. Audit fixes 2026-04-05 applicati.
- **Stack**: Python 3.12+, LangGraph, Qdrant, Jina (httpx), CCXT, asyncio, Pydantic v2, FastAPI, PG+TimescaleDB, polars==1.33.1 (lts-cpu), telethon
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)
- **Tests**: 140/140 passing

## Architecture
- **AI Agent Layer**: LangGraph state machine, 4 agents (Scout, Analyst, Risk, Executor)
- **Context Ingestion**: News/social → Jina embeddings (httpx, 1024d COSINE) → Qdrant (Docker v1.9.2)
- **Data Layer**: Binance REST/WS (CCXT) + rate limiter
- **Backtest Engine**: polars vectorised, RSI Wilder/MACD/Bollinger, Sharpe/drawdown/win rate
- **Storage**: TimescaleDB OHLCV hypertable + positions + agent_runs + account_balance + signal_outcomes + entity_graph
- **Telegram**: parser (IT+EN), SignalTracker (persistito su DB), TelegramMonitor (asyncio.Queue)
- **Risk**: StopLossMonitor + KillSwitch (asyncio.Lock) + PortfolioContext nel ciclo agente
- **Execution**: Simulator (paper, sizing reale su equity) + Live (gated Phase 5)

## Key Files
- `src/trdex/agents/graph.py` — LangGraph state machine (lazy init thread-safe)
- `src/trdex/agents/risk.py` — 5 gate: kill switch, HOLD, confidence, drawdown, no-pyramiding
- `src/trdex/agents/runner.py` — carica PortfolioContext reale dal DB prima del ciclo
- `src/trdex/backtest/indicators.py` — RSI Wilder (com=period-1), MACD, Bollinger
- `src/trdex/storage/` — ORM models + repo per positions, balance, signal_outcomes, entity_graph
- `migrations/001–006` — schema completo
- `tests/test_audit_fixes.py` — 92 test sui fix audit (140 totali)

## Migrations
- 001: OHLCV (TimescaleDB hypertable)
- 002: positions
- 003: agent_runs
- 004: account_balance (ledger con balance_after e peak)
- 005: signal_outcomes (SignalTracker persistito)
- 006: trdex_entity_graph (Tier 5 — fatti strutturati con temporalità)
- 007: kill_switch_state (KillSwitch persistente, sopravvive ai restart)
- 008: trdex_agent_memory (PIANIFICATO, Phase 1 6-tier model)

## Known Issues
- polars deve restare ==1.33.1 (lts-cpu) su Windows — polars>=1.35 ha cpu_check bloccato da antivirus
- aiohttp non funziona nel venv (DLL rotta su Windows) — usiamo httpx ovunque
- telethon: pyaes si compila da source, install lento su Windows (lock uv)

## Scelte tecniche fisse
- RSI: Wilder smoothing (com=period-1) — allineato a TradingView/Bloomberg
- EWM standard (span) era più reattivo ma divergeva da piattaforme professionali
- Balance persistito su ledger account_balance (non in memoria)
- Peak equity letto da DB al primo check StopLossMonitor (non resettato al riavvio)
- KillSwitch persistente su DB (sopravvive ai restart) — migration 007
- API rate limiting con slowapi (60/min default, 10/min agent/run, 5/min kill-switch)
- Order idempotency: key `agent:{run_id}` o `close:{position_id}`, TTL 5min
- Trailing stop high-water mark con retracement default 3%
- Trading KB agent-ready: 5 file autosufficienti per agente in `Riferimenti/agents/`
- Modello 6-tier memoria: Tier 1 = .md files (NO DB), Tier 2 = nuovo, Tier 3 = Kloudify nominations, Tier 4 = Qdrant, Tier 5+6 = già esistenti
