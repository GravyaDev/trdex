# Memory

## Now

- **trdex LIVE in production**: `https://trdex.gravya.it` (FastAPI) + `https://trdex.gravya.it/dashboard/` (Streamlit, now GitHub OAuth via oauth2-proxy)
- **Phase 2 observation**: 9 symbols, ~15 trade chiusi in 24h, $10k+ equity, 53.8% win rate
- **Sessione 2026-04-09 chiusa**: 4 task completati (OAuth, testnet Ed25519, Perplexity, aggregation) + adaptive SL + lot size + fees + dashboard features. Tutti pushati, Redeploy pending per ultimi 2 task.

## ⚠️ Sister branch LLM dev — `llm-agents`

- **Branch**: `llm-agents` (pushato su `origin/llm-agents`)
- **Worktree locale**: `C:\Users\Daniele\Antigravity\trdex-llm\` (sister directory di questa, creata via `git worktree add` il 2026-04-08)
- **Motivo**: rifacimento di Phase 2 con LLM veri dentro gli agent (Scout/Analyst/Risk/Executor). Il `main` attuale usa rule engine deterministico — non è l'AI promessa dal pitch. Il branch `llm-agents` trasforma questo.
- **Decisioni di design (già prese)**:
  1. **Provider**: LangChain abstractions (Anthropic + OpenAI + Google Gemini tutti supportati, swap-able)
  2. **Dashboard**: 4 pagine config (una per agente) con prompt editabili + parametri (temperature, max_tokens, ecc) + LLM model selector. Default pre-popolati
  3. **Active hours**: scheduler skippa fuori da fascia oraria configurable (default 8-22 UTC)
  4. **Reflection memory**: ogni agent legge la propria storia di trade dal day 1
  5. **Multi-agent reale**: 4 LLM call separate (non un monolith), day 1
- **Design doc**: **DA SCRIVERE nella prossima sessione** aprendo Claude Code su `trdex-llm/` (non qui). Path: `trdex-llm/.claude/reports/llm-agents-design-2026-04-08.md`
- **Workflow fix**: i bug di production scoperti su `main` vanno fixati qui, poi merged forward nel branch (`cd ../trdex-llm && git merge origin/main`). MAI il contrario.
- **Da QUESTA sessione (main) NON modificare `../trdex-llm/`**: usa sessione separata.

## Prossima sessione (due vie possibili)

**Via A — Continuare su main (production/rule-engine)**:
- Leggi `inspect_runs --hours 24` per vedere trade della notte, Bug 11 cosmetic, o feature dashboard backlog
- Lavora su questa directory `trdex/`

**Via B — Iniziare il lavoro LLM**:
- Apri Claude Code in `C:\Users\Daniele\Antigravity\trdex-llm\` (nuova sessione, fresca)
- Scrivi il design doc completo `llm-agents-design-2026-04-08.md` dal contesto delle 5 decisioni sopra
- Solo DOPO il design, inizia a toccare codice agenti

## Project: trdex

- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 2 observation LIVE in production (simulation mode, scheduler 5min, 2 symbols)
- **Stack**: Python 3.12+, LangGraph, Qdrant 1.13, Jina, CCXT, FastAPI, asyncpg, PG+TimescaleDB, polars==1.33.1, telethon (disabilitato), Streamlit+plotly (dashboard)
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)
- **Tests**: 312/312 passing (308 + 4 nuovi Bug 8 regression)
- **Identity for commits**: `Author: GravyaDev <dev@gravya.it>`, trailer `Co-Authored-By: Kloud <kloud@gravya.it>`. **Mai usare Claude trailer** (regola hard KB).

## Production state (2026-04-08 wrap-up)

- **Domain**: `https://trdex.gravya.it` (Traefik + Let's Encrypt via Coolify)
- **Containers** (5/5 healthy su VPS srv.gravya.it):
  - `db` — TimescaleDB 2.17.2-pg16, migrations 001-008 applied (Bug 5 fix)
  - `redis` — 7.x
  - `qdrant` — 1.13.0, collection `trdex_context` ensured
  - `app` — FastAPI uvicorn :8000, scheduler ON, last commit `3415587`
  - `dashboard` — Streamlit :8501, served at `/dashboard/` (Bug "deploy dashboard" fix)
- **Auth**:
  - API: `TRDEX_API_KEY` set in Coolify env, X-API-Key header required
  - Dashboard: Traefik basic-auth middleware, hash hardcoded in `docker-compose.yaml` (Coolify non interpola env vars dentro labels — vedi commit `3415587`)
- **Scheduler config (Coolify env)**:
  - `TRDEX_AGENT_SCHEDULER_ENABLED=true`
  - `TRDEX_AGENT_SCHEDULER_INTERVAL=300` (5 min)
  - `TRDEX_AGENT_SCHEDULER_SYMBOLS=BTC/USDT,ETH/USDT` (utente cambia da Coolify UI quando vuole più symbols, max ~20 prima di rate limit Binance)
  - `TRDEX_INGESTION_SYMBOLS=BTC/USDT,ETH/USDT`
- **News sources attive**: CryptoCompare + StockData (chiavi in Coolify env, ingestion ogni 5 min)
- **Telegram disabilitato**: `TRDEX_TELEGRAM_API_ID=0`
- **Trade fatti oggi**: 2 (BTC apertura 16:37 chiusura 18:03 +0.73%, ETH apertura 17:42 chiusura 18:03 -0.13%). Entrambi chiusi da SELL signal SMA cross sincrono. Net P&L +$1.22.

## Architecture (snapshot)

- LangGraph state machine (Scout→Analyst→Risk→Executor), oggi rule-engine deterministico (non LLM, vedi branch `llm-agents`)
- Intent enum 5 valori + `signal_to_intent` translator, Risk Gate 4 blocca pyramiding
- StopLossMonitor tick 30s (sl=5% tp=10% trail=3% dd_daily=10% dd_max=20% realised-only)
- Memory 6-tier: KB / agent_memory / nominations / trade narratives / entity graph / agent_runs

## Completed today (2026-04-09) — vedi Task Board Done per dettagli

All 4 planned tasks + 9 additional improvements deployed. Remaining:
- Phase 3 strategy iteration — dopo 7-14 giorni dati
- LLM agents — branch `llm-agents` (design doc scritto, codice in corso nell'altra sessione)
- Auth upgrade: ✅ DONE (OAuth2-proxy GitHub)
- Perplexity: ✅ DONE (testato live)
- Multi-source aggregation: ✅ DONE (user-selectable feeds)

## Known Issues

- **Coolify non interpola env vars dentro Traefik labels** → basicauth hash hardcoded in compose (commit `3415587`)
- `risk_approved=❌` su HOLD: Bug 11 cosmetic
- Dashboard "Run Agent Now" mostra `signal` invece di `intent` (Bug 11)
- Daily dd mtm vs max dd realised-only: by design, non bug
- **Dev locale**: polars==1.33.1 obbligatorio Windows, aiohttp rotto usa httpx, telethon pyaes compile-from-source

## Scelte tecniche fisse

- RSI Wilder smoothing, SMA cross 50/200, Sharpe 365 days/year
- Balance ledger source of truth, idempotency `agent:{run_id}` / `close:{pos_id}`
- Intent enum con short reserved, backtest immutato, readiness gate legge da ledger
- Commits: `Author: GravyaDev <dev@gravya.it>`, trailer `Co-Authored-By: Kloud <kloud@gravya.it>`, MAI Claude
- VPS ports: 8500→8000 (app), 8501→8501 (dashboard)
- Symbols/thresholds config via Coolify UI (single source of truth) fino a dashboard native feature
