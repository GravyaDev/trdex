# Task Board

## Today — 2026-04-07 (chiusa)
Tutto fatto, vedi sezione Done sotto.

## Tomorrow — 2026-04-08
- [ ] **PRIORITY 1**: Implementare refactor Intent enum (Opzione 2)
  - Seguire `.claude/reports/brainstorm-2026-04-07-intent-enum.md`
  - 24 decisioni numerate, ~7h focused work
  - Sequenza: Step 0 grep → enum+translator+tests → state.py → analyst → risk → runner → executor → PortfolioService atomicity → tests update → inspect_runs → smoke level 4 verify
  - NON iniziare a fine sessione: il refactor richiede focus continuativo
- [ ] **PRIORITY 2**: dopo il refactor, accendere scheduler per Phase 2 osservazione
  - Aggiungere a `.env`: `TRDEX_AGENT_SCHEDULER_ENABLED=true`, `TRDEX_AGENT_SCHEDULER_SYMBOLS=BTC/USDT,ETH/USDT`, `TRDEX_AGENT_SCHEDULER_INTERVAL=300`
  - Lanciare `uv run python -m trdex.main`
  - Lasciare girare per 3-5 giorni, monitorare con `inspect_runs`

## This Week (post-refactor)
- [ ] Phase 2 osservazione vera: 3-5 giorni di scheduler live in simulation
- [ ] Daily check con `inspect_runs --hours 24` e `--hours 72`
- [ ] Sentinella: se zero trade in 48h sul mercato corrente, capire perché (mercato lateral? bug del traduttore?)
- [ ] Sentinella: monitorare `agent_runs` count cresce ~288 al giorno per simbolo

## Backlog (consolidato)
- [ ] **Deploy trdex su VPS per Phase 2 osservazione 24/7** — task dedicato
  - **Prerequisiti già pronti** (✅ committati 2026-04-08):
    - Dockerfile fixed (README + curl per healthcheck)
    - .dockerignore creato (esclude .env, .mcp.json, .claude, tests, docs)
    - .env.example completo con tutte le variabili (incluso SL_TRAILING_STOP_PCT)
    - docker-compose.yaml: restart=unless-stopped + log rotation 10MB×3 su tutti i servizi
    - app build verificato (`docker compose build app` → trdex-app:latest)
  - **Da decidere prima di iniziare il task**:
    - VPS provider (Hostinger? DO? Hetzner?) e specs (min 2vCPU/4GB/40GB)
    - Deploy mode: solo scheduler (porta chiusa) vs API esposta dietro nginx+TLS
    - Strategy backup pgdata (cron pg_dump → object storage)
    - Monitoring esterno (uptime kuma / healthcheck.io / niente)
  - **Steps del task quando lo apriremo**:
    1. Provisioning VPS + ssh hardening + ufw/firewall + fail2ban
    2. Install docker engine + compose plugin
    3. `git clone` del repo + creare `/etc/trdex.env` (chmod 600) coi secrets
    4. `docker compose up -d` (build app + infra)
    5. `apply_migrations` + smoke_level4 di sanità
    6. Accendere `TRDEX_AGENT_SCHEDULER_ENABLED=true` + restart dell'app
    7. Verificare con `inspect_runs` da remoto via ssh tunnel
    8. (opzionale) configurare Telegram alerting su kill switch
- [ ] **Phase 3 (post-osservazione)**: iterazione sulla strategia
  - Solo dopo aver capito i numeri di Phase 2
  - Variazioni SMA cross (parametri diversi), poi RSI threshold, poi MACD divergence
  - Tutte trend-following parametriche, compatibili con il refactor Intent + close-on-signal
- [ ] Pass feed/strategy registries into create_app() for /status
- [ ] Reject default DB creds in non-dev modes
- [ ] Live executor test su Binance testnet
- [ ] Alembic migration runner nel lifespan
- [ ] Circuit breaker IngestionScheduler per Qdrant failures
- [ ] Define `PositionSide` enum (replace plain str in ORM) — minore dopo il refactor Intent
- [ ] Phase 2 6-tier: Tier 3 nominations writer extensions
- [ ] Phase 4 6-tier: Tier 4 Qdrant trade narratives uso reale (oggi solo schema)
- [ ] Forex weekend gap closure rule
- [ ] Persistent stop-loss event log
- [ ] Tier 3+4 features (kline WS stream, CoinGecko screener, hyperopt, Redis cache, Ollama LLM, Alembic auto-migration)

## Future / Long-term
- [ ] Opzione 4 (ExitPolicy) — solo se vorrai strategie di famiglie strutturalmente diverse (mean reversion, breakout, scalping)
- [ ] `fill_reconciliation` table per riconciliazione local DB ↔ exchange (live mode)
- [ ] Fast brain / WebSocket Binance ticker live
- [ ] Multi-symbol portfolio rotation
- [ ] Multi-timeframe confirmation rules

## Done — 2026-04-07
### Mattina/pomeriggio (commit 5d1ff2c, 54 file)
- [x] Smoke level 1 — infrastructure sanity check (9 check)
- [x] Smoke level 2 — single agent cycle on BTC/USDT live
- [x] Smoke level 3 — backtest end-to-end (90gg × 1h) + ledger replay + readiness + coherence
- [x] Migration runner `apply_migrations.py` con dollar-quote/comment-aware splitter
- [x] Fix migration 001 (TimescaleDB compression) + migration 008 (index predicate immutable)
- [x] Fix Qdrant client v1.13 (server up + check_compatibility=False) + query_points migration
- [x] Fix Decimal precision nel simulator log
- [x] BacktestSMACross strategy + 7 unit test
- [x] Fix engine PnL semantics (sum(pnl) == final_capital - initial_capital)
- [x] Fix engine entry_idx/exit_idx per replay timestamping
- [x] BinanceFeed since param + propagation through PriceFeedManager + 6 feed signature update

### Pomeriggio (commit aaae052, 11 file)
- [x] Task 1 — Readiness gate v2: win_rate vero da PnL, sharpe da EoD ledger sqrt(252), 19 unit test
- [x] Task 2 — Backtest engine timeframe-aware sharpe annualization, _BARS_PER_YEAR mapping, 12 unit test
- [x] Task 2.5 — Smoke level 3 flag --position-size con validazione + sourcetrack
- [x] Task 3a — agent_scheduler_loop estratto da app.py in agents/scheduler.py
- [x] Task 3b — app.py importa il loop invece di definirlo inline
- [x] Task 3c — Smoke level 4 (scheduler bounded smoke), 4 assertion verde
- [x] .gitignore aggiunge .mcp.json + remove from index (token Hostinger)

### Sera (commit 815614d, WIP)
- [x] Discovery: PortfolioService write path mai chiamato — agent_runs cresce ma positions/account_balance vuoti
- [x] PortfolioService.record_open_fill (long-only, refusa SELL)
- [x] PortfolioService.record_close_fill (chiude + scrive PnL ledger)
- [x] AgentRunner._persist_open_fill wired (best-effort)
- [x] StopLossMonitor wired post auto-close
- [x] inspect_runs.py — read-only 8-section observability dashboard
- [x] 6 unit test PortfolioService write path
- [x] Manual end-to-end verifica del fill persistence (apertura+chiusura, +1.93 USDT in ledger)

### Sera tarda (no commit, da implementare prossima sessione)
- [x] Multi-agent brainstorming per il refactor Intent enum: Phase 0+1+2+3 completate
- [x] Decision log brainstorming salvato in `.claude/reports/brainstorm-2026-04-07-intent-enum.md`
- [x] Memory + Task Board + Daily Note aggiornati per wrap-up

## Done — 2026-04-06 (precedente)
- [x] Tier 1 + Tier 2 hardening (RateLimiter, KillSwitch persistente, slowapi, idempotency)
- [x] Trading KB agent-ready in `Riferimenti/agents/`
- [x] Piano modello 6-tier persistent memory architettato
- [x] Phase 1 6-tier model (Tier 1 loader, Tier 6 narrative_context)

## Done — 2026-04-05
- [x] Audit esterno processato, fix P0/P1
- [x] Account_balance ledger persistente
- [x] Entity Graph (Tier 5) implementato
- [x] SignalTracker persistito su DB

## Done — storico
- [x] Onboarding + Kloudify setup (2026-04-04)
- [x] Phase 1 scaffold (2026-04-04)
- [x] Phase 2 LangGraph + 4 agents + Qdrant + Jina (2026-04-04)
- [x] Phase 3 RSI/MACD/Bollinger + backtest engine polars (2026-04-04)
- [x] Phase 4 Portfolio tracker + Streamlit dashboard + Feeds WS (2026-04-05)
- [x] Phase 5 Agent scheduler + news ingestion + risk monitor (2026-04-05)
