# Memory

## Now

- **trdex è LIVE in production** su `https://trdex.gravya.it` (FastAPI) + `https://trdex.gravya.it/dashboard/` (Streamlit, basic auth `daniele`).
- **Phase 2 observation iniziata 2026-04-08 17:42 UTC**: scheduler agent attivo BTC+ETH (5min interval), oggi già 2 trade chiusi (BTC +0.73%, ETH -0.13%, net +$1.22 su seed $10k). Win rate 50%, drawdown 0%.
- **Sessione 2026-04-08 chiusa al wrap-up**: nessun lavoro tecnico aperto, niente bug blocker, sistema in osservazione passiva.
- **Prossima sessione**: NON serve rush. Quando rientri: leggi memory.md, poi `inspect_runs --hours 24` dal container app per vedere quanti trade ha fatto la notte/giornata, poi decidi cosa fare in base ai dati.

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

## Architecture (invariata da pre-deploy)

- **AI Agent Layer**: LangGraph state machine, 4 agents (Scout → Analyst → Risk → Executor)
- **Intent model**: `agents/intent.py` con StrEnum 5 valori (OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT, HOLD) + `signal_to_intent` translator
- **Risk gates**: 4 gates (KillSwitch / sizing / confidence / pyramiding-block via Gate 4 post-Intent)
- **StopLossMonitor**: tick 30s, params position_sl=5%, position_tp=10%, trailing=3%, daily_dd=10%, max_dd=20% (Bug 8 fix: max_dd realised-only)
- **Memory 6-tier**: KB / agent_memory / nominations / trade narratives / entity graph / agent_runs

## Backlog priority (vedi Task Board.md)

1. **Bug 11 (cosmetic)**: dashboard `risk_approved=❌` su tutti gli HOLD è semantica fuorviante — fix 10 min
2. **Dashboard feature**: gestione symbols watchlist add/remove + rate limit estimate live (~3-5h)
3. **Dashboard feature**: edit thresholds da UI con audit log + cooldown (~2-3h)
4. **Upgrade auth dashboard**: Cloudflare Access / Tailscale / oauth2-proxy (sostituisce basic auth) — trigger dopo 1 settimana stabile, prima di live mode
5. **Perplexity Sonar news source**: sostituisce CryptoCompare/StockData (~$20/mese, ~45-90 min effort) — trigger dopo Phase 2 baseline
6. **Phase 3**: iterazione strategia (variazioni SMA, RSI, MACD divergence) — solo dopo 7-14 giorni Phase 2 dati
7. **gravya-ops agent**: deferred fino alla decisione `pleng vs custom` (sessione dedicata)

## Known Issues (production-relevant)

- **Coolify non interpola env vars dentro Traefik labels** del compose. Workaround usato: hardcode dell'hash basicauth in `docker-compose.yaml` con single quotes. Documentato in commit `3415587`.
- **`risk_approved=❌` su righe HOLD**: cosmetic bug dashboard, in backlog come Bug 11
- **Dashboard "Run Agent Now" mostra ancora `signal` field** invece di `intent` post-refactor — minor cosmetic, in Bug 11
- **Daily drawdown check è mark-to-market** mentre max drawdown è realised-only (Bug 8 fix). Sono gate diversi con scope diverso, non bug — by design.

## Known Issues (dev locale, invariati)

- polars deve restare ==1.33.1 (lts-cpu) su Windows
- aiohttp non funziona nel venv (DLL rotta su Windows) — usiamo httpx ovunque
- telethon: pyaes si compila da source, install lento su Windows

## Scelte tecniche fisse

- RSI: Wilder smoothing (com=period-1) — allineato a TradingView
- Balance persistito su ledger account_balance
- Peak equity da DB, KillSwitch persistente DB
- Order idempotency: `agent:{run_id}` (open) o `close:{position_id}` (close), TTL 5min
- Trailing stop high-water mark 3%
- Sharpe annualization crypto-correct (365 days/year)
- Readiness gate legge da account_balance (single source of truth)
- Intent enum: 5 valori (long+short reserved), Strada B traduttore, Strada α backtest immutato
- Max drawdown realised-only (Bug 8 fix), daily drawdown mark-to-market (by design)
- **trdex VPS port**: 8500 host → 8000 container app, 8501 host → 8501 container dashboard
- **Dashboard symbols/thresholds**: gestiti via Coolify UI finché non c'è feature dashboard nativa (single source of truth = Coolify env)
