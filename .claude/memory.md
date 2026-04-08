# Memory

## Now

- Sessione 2026-04-08 chiusa alle ~15:30 UTC con deploy trdex su VPS **IN PROGRESS, bloccato da 2 bug** (4+5). VPS hardening completato, Kloud user creato, Coolify configurato, secondo deploy attempt fallito per bug app lifespan.
- **Non iniziare nessun altro lavoro prima di aver letto `.claude/reports/session-handoff-2026-04-08-deploy-wip.md`** — contiene lo stato completo, i bug aperti con fix plan dettagliato, la cleanup checklist, e le lessons learned.
- Prossima sessione: open fresh Claude Code, leggi memory.md → handoff file → esegui "Next session — resume plan" dal handoff. Stima: 45-90 min di focus fresco.

## Project: trdex
- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 1+2+3+4+5 + Intent refactor completato + deploy VPS WIP (bloccato bug 4+5)
- **Stack**: Python 3.12+, LangGraph, Qdrant 1.13, Jina (httpx), CCXT, asyncio, Pydantic v2, FastAPI, PG+TimescaleDB, polars==1.33.1, telethon
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)
- **Tests**: 308/308 passing (era 280, +28 dal refactor Intent)

## Architecture
- **AI Agent Layer**: LangGraph state machine, 4 agents (Scout, Analyst, Risk, Executor)
- **Context Ingestion**: News/social → Jina embeddings → Qdrant 1.13 (`trdex_context`)
- **Data Layer**: Binance REST/WS (CCXT) + rate limiter
- **Backtest Engine**: polars vectorised, RSI Wilder/MACD/Bollinger, Sharpe annualizzato per timeframe
- **Storage**: TimescaleDB OHLCV + positions + agent_runs + account_balance + signal_outcomes + entity_graph + agent_memory
- **Risk**: StopLossMonitor + KillSwitch persistente + readiness gate v2 (legge ledger)
- **Execution**: Simulator + DefaultExecutionGateway + LiveExecutor scaffold + idempotency keys
- **Memory 6-tier**: Tier 1 KB loader, Tier 2 agent_memory, Tier 3 nominations, Tier 4 trade narratives, Tier 5 entity graph, Tier 6 agent_runs narrative
- **Intent model**: `agents/intent.py` con StrEnum 5 valori (OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT, HOLD) + `signal_to_intent` translator. Risolve il runner long-only / signal-vs-close paradox di ieri.
- **Portfolio**: `PortfolioService.record_close_fill` atomic single-commit (D17), `closed_by` tag (D20)

## VPS Deploy Target (NEW 2026-04-08)

- **VPS**: Hostinger KVM 2 (id 1495221), `srv.gravya.it`, Ubuntu 24.04 + Coolify
- **IP**: `187.124.166.189` (v4), `2a02:4780:79:e9b8::1` (v6)
- **Hardening**: swap 4GB + swappiness 10, fail2ban aggressive sshd, UFW informative, sshd PermitRootLogin prohibit-password + Match User kloud
- **User `kloud`**: uid 1002, locked password, groups dev+docker, sudoers scoped, SSH key-only (trdex_deploy)
- **Git identity su VPS**: `Kloud <kloud@gravya.it>`, primo commit `dffe2fb` in `/opt/gravya/`
- **Coolify Project**: `trdex` con Application da `github.com/GravyaDev/trdex.git`, dominio `https://trdex.gravya.it`, port host 8500 → container 8000
- **Deploy status**: ❌ BLOCCATO dal bug 4+5 (vedi handoff file)

## Key Files (post refactor + deploy prep)
- `src/trdex/agents/intent.py` — Intent enum + signal_to_intent translator (NEW, commit 9ec41be)
- `src/trdex/agents/state.py, analyst.py, risk.py, executor.py, runner.py` — refactored per Intent
- `src/trdex/portfolio/service.py` — record_close_fill atomic + closed_by
- `src/trdex/scripts/inspect_runs.py` — Intent distribution + closed_by breakdown (D22)
- `docker-compose.yaml` — Coolify-compliant (commit 1fa0dca) + qdrant bash /dev/tcp healthcheck (commit 5dc584a)
- `docker-compose.override.yaml` — dev-only host port bindings
- `.dockerignore` — esclude .env, .mcp.json, .claude, tests, docs
- `Dockerfile` — README + curl (commit c42c641) **MANCA COPY migrations/ (bug 4)**
- `.claude/reports/session-handoff-2026-04-08-deploy-wip.md` — **LEGGI QUESTO PRIMO**
- `.claude/reports/brainstorm-2026-04-07-intent-enum.md` — decision log Intent refactor

## Migrations
- 001-008: tutte applicate (dev locale), in VPS db fresco NON ancora applicate (bug 5)

## Known Issues
- polars deve restare ==1.33.1 (lts-cpu) su Windows
- aiohttp non funziona nel venv (DLL rotta su Windows) — usiamo httpx ovunque
- telethon: pyaes si compila da source, install lento su Windows
- **BUG 4 (deploy)**: Dockerfile non copia `migrations/` — fix: aggiungi `COPY migrations/ migrations/` dopo linea 24
- **BUG 5 (deploy)**: FastAPI lifespan non applica migrations → app crash su DB fresco — fix Option C: chiama `apply_migrations.run_migrations()` all'inizio del lifespan
- **BUG 6 (speculative)**: Qdrant collection `trdex_context` probabilmente non creata al primo boot — fix preventivo: init in lifespan dopo migrations

## Scelte tecniche fisse
- RSI: Wilder smoothing (com=period-1) — allineato a TradingView
- Balance persistito su ledger account_balance
- Peak equity da DB, KillSwitch persistente DB
- API rate limiting con slowapi
- Order idempotency: `agent:{run_id}` (open) o `close:{position_id}` (close), TTL 5min
- Trailing stop high-water mark 3%
- Sharpe annualization crypto-correct (365 days/year)
- Readiness gate legge da account_balance (single source of truth)
- Intent enum: 5 valori (long+short reserved), Strada B traduttore, Strada α backtest immutato
- **trdex VPS port**: 8500 host → 8000 container (per evitare collision con Coolify UI su 8000)
- **Kloud identity on VPS**: modello B (key-per-context), chiave corrente `trdex-deploy-2026-04-08`, altre chiavi (gravya-ops, ecc.) verranno aggiunte in futuro come righe supplementari in `/home/kloud/.ssh/authorized_keys`

## Next Session (priority order)

1. **Fix bug 4+5+6** seguendo il "Next session — resume plan" nel handoff file. Commit + push + Coolify redeploy.
2. **Verify deploy success**: tutti i 4 container healthy, `inspect_runs --hours 1` dal container mostra lo scheduler disattivo, 0 trade.
3. **Enable scheduler**: flip `TRDEX_AGENT_SCHEDULER_ENABLED=true` in Coolify UI, restart, monitora primi tick.
4. **Write backup script**: `/opt/gravya/backup/trdex/backup.sh` mirror di `n8n-postgres/backup.sh`, aggiungere a `backup-all.sh`, commit come Kloud.
5. **Cleanup**: vedere checklist nel handoff file (elimina `.trdex-secrets-DELETE-AFTER-USE.env`, clean `/etc/*.bak.*`, etc.)
6. **Decision task**: valutare `pleng` vs custom gravya-ops agent (vedi handoff sezione dedicata). Fare in sessione fresca dedicata, NON oggi.
7. **Handoff gravya-ops**: il design del custom agent è SOSPESO fino alla decisione pleng-vs-custom.
