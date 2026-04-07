# Task Board

## Today — 2026-04-06 (Tomorrow's priorities)
- [x] Wire EntityGraphRepository nel ciclo agente: analyst scrive `volatility_regime`, risk scrive `last_signal`
- [x] Test Telegram con canali reali — completato 2026-04-05
- [x] Wilder RSI implementato, soglie 30/70 confermate (best practice settore)

## Tomorrow — 2026-04-07
- [ ] Phase 1 modello 6-tier memoria: Tier 1 loader (parser .md) + Tier 6 repo + Migration 008 + Tier 2 ORM/repo
- [ ] Test della Phase 1 (loader, repo, integration)

## This Week
- [x] Implement DefaultExecutionGateway con sim/live routing + gate check
- [x] Tier 1 hardening: RateLimiter wired, KillSwitch persistente, SL auto-close, slowapi, idempotenza ordini
- [x] Tier 2 hardening: Input validation, request logging, staleness check, trailing stop, simulation gate, readiness endpoint
- [x] Dashboard: readiness widget, trailing stop, symbol watchlist, debug panels
- [x] Trading KB agent-ready in Riferimenti/agents/ (5 file autosufficienti)
- [x] Piano modello 6-tier persistent memory architettato
- [ ] Phase 2 6-tier: Tier 3 nominations + Tier 5 writers extension
- [ ] Phase 3 6-tier: MemoryContext aggregator + analyst migration
- [ ] Phase 4 6-tier: Tier 4 Qdrant trade narratives
- [ ] Phase 5 6-tier: Rollout in Risk/Executor/Scout
- [ ] Define `PositionSide` enum (replace plain str in ORM)

## Backlog
- [ ] Pass feed/strategy registries into create_app() for /status
- [ ] Reject default DB creds in non-dev modes
- [ ] Live executor test su Binance testnet
- [ ] Alembic migration runner nel lifespan
- [ ] Circuit breaker IngestionScheduler per Qdrant failures

## Done — 2026-04-06
- [x] Wire EntityGraphRepository nel ciclo agente (analyst volatility_regime, risk last_signal)
- [x] DefaultExecutionGateway con sim/live routing + kill switch gate
- [x] 3 report comparativi (repo riferimento, indicazioni API, trading vs HFT)
- [x] Multi-agent brainstorming strutturato — APPROVED con 13 revisioni
- [x] Tier 1 — RateLimiter wired ai 7 feed con RPM verificati online
- [x] Tier 1 — KillSwitch persistente su DB (migration 007)
- [x] Tier 1 — StopLossMonitor auto-close via gateway iniettato
- [x] Tier 1 — slowapi API rate limiting (10/min agent, 5/min kill-switch)
- [x] Tier 1 — Order idempotency (key+TTL 5min)
- [x] Tier 2 — Input validation Pydantic (regex symbol, bounds limit/days)
- [x] Tier 2 — Request logging middleware (method/path/status/latency/key hash)
- [x] Tier 2 — Staleness check SL (refetch >60s)
- [x] Tier 2 — Trailing stop (high-water mark, 3% retracement)
- [x] Tier 2 — Simulation gate dinamico (sostituito Gate 5 hardcoded)
- [x] Tier 2 — `GET /v1/system/readiness` endpoint
- [x] Dashboard — readiness widget, trailing stop, symbol watchlist, debug panels
- [x] Trading KB agent-ready in `Riferimenti/agents/` (scout, analyst, risk_manager, executor, stop_loss_monitor, INDEX)
- [x] Piano modello 6-tier persistent memory architettato

## Done — 2026-04-05
- [x] Audit esterno processato — tutti i P0/P1 applicati
- [x] MED-7 CORS: split comma-separated origins
- [x] SEC-4: assert → raise RuntimeError in embeddings.py
- [x] MED-3: ingestion.py usa self._embedder (no dead code)
- [x] MED-1: dead code rimosso da engine.py
- [x] MED-8: graph lazy init thread-safe con asyncio.Lock
- [x] SEC-1: warning startup + per-request se api_key vuota
- [x] MED-2: RSI unificato — analyst usa rsi_from_list da indicators.py
- [x] RSI → Wilder smoothing (com=period-1), allineato a TradingView
- [x] ARCH: PortfolioContext iniettato nel ciclo agente
- [x] Risk Manager: gate drawdown + gate no-pyramiding su posizioni reali
- [x] account_balance: ORM + repo + migration 004 (ledger persistente)
- [x] Executor: sizing reale (equity × position_size / price)
- [x] StopLossMonitor: _peak_equity inizializzato da DB
- [x] SignalTracker: persistito su DB (migration 005 + repo + load_from_db al boot)
- [x] OrderResult: stato `pending` aggiunto
- [x] Entity Graph (Tier 5): ORM + repo + migration 006

## Done — storico
- [x] Onboarding + Kloudify setup (2026-04-04)
- [x] Stack decision + architecture doc (2026-04-04)
- [x] Phase 1 scaffold: 38 .py files, 20 test passing (2026-04-04)
- [x] Deep audit + fix F1-F4 (2026-04-04)
- [x] Phase 2: LangGraph + 4 agents + Qdrant + Jina (2026-04-04)
- [x] Phase 3: RSI/MACD/Bollinger + backtest engine polars (2026-04-04)
- [x] Phase 3: OHLCV persistence TimescaleDB (2026-04-04)
- [x] Phase 4: Portfolio tracker + Streamlit dashboard + Feeds WS (2026-04-05)
- [x] Phase 5: Agent scheduler + news ingestion + risk monitor (2026-04-05)
- [x] Audit 2026-04-05 P0+P1: auth su 11 endpoint, session leak, env.example (2026-04-05)
- [x] 140/140 test passing (2026-04-05)
