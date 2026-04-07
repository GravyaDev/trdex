# Memory

## Now
- Sessione 2026-04-07 chiusa con 3 commit (commit-fatto, Phase 1 testabilita, WIP fix portfolio).
- Tutte e tre le fasi del piano "osservare prima di iterare" completate: Task 1 (readiness v2), Task 2 (sharpe annualization), Task 3 (scheduler smoke).
- BUG ARCHITETTURALE CRITICO scoperto a fine giornata: il runner long-only / signal-vs-close paradox. WIP commit `815614d` ha il PortfolioService corretto ma la calling logic dell'AgentRunner non lo esercita mai.
- Multi-agent brainstorming completato: design APPROVED per Opzione 2 (Intent enum). 24 decisioni nel decision log, salvato in `.claude/reports/brainstorm-2026-04-07-intent-enum.md`.
- Prossima sessione: implementare il refactor Intent enum (~7h focused work). Il refactor sblocca la Phase 2 di osservazione vera.

## Project: trdex
- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 1+2+3+4+5 + smoke level 1-4 + readiness v2 + WIP fill persistence. Brainstorming Intent enum APPROVED.
- **Stack**: Python 3.12+, LangGraph, Qdrant 1.13, Jina (httpx), CCXT, asyncio, Pydantic v2, FastAPI, PG+TimescaleDB, polars==1.33.1, telethon
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)
- **Tests**: 280/280 passing

## Architecture
- **AI Agent Layer**: LangGraph state machine, 4 agents (Scout, Analyst, Risk, Executor)
- **Context Ingestion**: News/social → Jina embeddings → Qdrant 1.13 (`trdex_context`)
- **Data Layer**: Binance REST/WS (CCXT) + rate limiter; `since` param ora wired through
- **Backtest Engine**: polars vectorised, RSI Wilder/MACD/Bollinger, Sharpe annualizzato per timeframe
- **Storage**: TimescaleDB OHLCV + positions + agent_runs + account_balance + signal_outcomes + entity_graph + agent_memory
- **Risk**: StopLossMonitor + KillSwitch persistente + readiness gate v2 (legge ledger)
- **Execution**: Simulator + DefaultExecutionGateway + LiveExecutor scaffold + idempotency keys
- **Memory 6-tier**: Tier 1 KB loader, Tier 2 agent_memory, Tier 3 nominations, Tier 4 trade narratives, Tier 5 entity graph, Tier 6 agent_runs narrative — all wired in 4 agents via memory_helpers
- **Portfolio (WIP)**: PortfolioService.record_open_fill / record_close_fill — write path corretto ma non ancora chiamato correttamente dal runner

## Key Files (post-fixes)
- `src/trdex/agents/scheduler.py` — agent_scheduler_loop estratto da app.py, usabile da test
- `src/trdex/risk/readiness.py` — v2: legge da account_balance, sharpe annualizzato
- `src/trdex/backtest/engine.py` — sharpe parametrizzato, _BARS_PER_YEAR per 13 timeframe
- `src/trdex/portfolio/service.py` — WIP fill persistence (long-only, write path)
- `src/trdex/scripts/smoke_level1..4.py` — smoke test sequenziali
- `src/trdex/scripts/inspect_runs.py` — read-only observability dashboard, 8 sezioni
- `src/trdex/scripts/apply_migrations.py` — runner SQL idempotente con dollar-quote splitter
- `.claude/reports/brainstorm-2026-04-07-intent-enum.md` — decision log Intent refactor

## Migrations
- 001-008: tutte applicate, idempotenti

## Known Issues
- polars deve restare ==1.33.1 (lts-cpu) su Windows
- aiohttp non funziona nel venv (DLL rotta su Windows) — usiamo httpx ovunque
- telethon: pyaes si compila da source, install lento su Windows
- Runner long-only / signal-vs-close paradox: WIP commit ha mezzo fix, refactor Intent prossima sessione

## Scelte tecniche fisse
- RSI: Wilder smoothing (com=period-1) — allineato a TradingView
- Balance persistito su ledger account_balance
- Peak equity da DB
- KillSwitch persistente DB
- API rate limiting con slowapi
- Order idempotency: `agent:{run_id}` o `close:{position_id}`, TTL 5min
- Trailing stop high-water mark 3%
- Trading KB agent-ready: 5 file in `Riferimenti/agents/`
- Memoria 6-tier: Tier 1 = .md, Tier 2 = trdex_agent_memory, Tier 3 = nominations file, Tier 4 = Qdrant, Tier 5+6 = già esistenti
- Sharpe annualization crypto-correct (365 days/year, no 252 trading-day adjustment)
- Readiness gate legge da account_balance (single source of truth) non da agent_runs
- Refactor Intent enum approvato: 5 valori (long+short), Strada B traduttore, Strada α backtest immutato

## Next Session
- Implementare refactor Intent enum seguendo le 24 decisioni in `.claude/reports/brainstorm-2026-04-07-intent-enum.md`
- Step 0: grep .signal call sites
- Sequenza: enum + traduttore + tests → state.py → analyst → risk → runner → executor → PortfolioService atomicity → tests update → inspect_runs → smoke level 4 verify
- Stima ~7h focused work
- DOPO il refactor: accendere scheduler in .env per Phase 2 osservazione vera
