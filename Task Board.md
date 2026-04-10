# Task Board

## Production status (2026-04-09 mattina)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/`
Scheduler: 9 symbols, 5 min interval, 1334 agent_runs in 24h
Trade chiusi: 12 (6W/6L, net +$9.65, win rate 50%)
Balance: $10,009.65 / peak $10,032.37
Fix deployato oggi: SL adattivo a CV + per-symbol config + fee nel P&L

---

## Backlog — ordinato per fase di maturazione

### 🔴 Blockers per live mode (da fare PRIMA di soldi veri)

- [x] **Lot size compliance** — GIA' IMPLEMENTATO: `market/specs.py` con `truncate_qty()` chiamato da Simulator + LiveExecutor, caricato al lifespan via CCXT `load_markets()`

- [x] **Open-side fee tracking** — GIA' IMPLEMENTATO: `fee_open` column (migration 010), salvato in `record_open_fill()`, sottratto in `record_close_fill()` P&L

- [x] **Live executor test su Binance testnet** — DONE (Ed25519 test passed, lot size compliance implementata)

- [x] **Reject default DB creds in non-dev modes** — GIA' IMPLEMENTATO: `app.py:133-139` blocca startup con creds default fuori da simulation

### 🟡 Miglioramenti Phase 2 (da fare con sistema che gira)

(nessun task aperto — symbols watchlist, thresholds edit, active hours tutti implementati da Runtime Config)

### 🟠 Multi-asset expansion (Forex + crypto broadening)

Design approvato dal multi-agent brainstorm 2026-04-10. Decision log in
`.claude/reports/brainstorm-2026-04-10-multi-asset.md`.

**Fase 1 — Crypto expansion (zero codice)** — DONE
- [x] **Espandere a 25 crypto symbols** — defaults aggiornati in docker-compose + config (commit `612b662`). Attivazione in produzione via dashboard Settings.

**Fase 2 — Fondamenta multi-asset**
- [ ] [idea] **AssetClassRegistry + symbol normalizer** — classify() con normalizzazione (XAUUSD→XAU/USD), config-based precedence per symbol ambigui, enum AssetClass(CRYPTO, FOREX)
- [ ] [idea] **Migration 011: asset_class + leverage su positions** — default 'crypto'/1.0 su righe esistenti. Nessun NULL.
- [ ] [idea] **RiskProfile per asset class** — dataclass con max_position_fraction, max_leverage, max_notional, max_positions. Equity separata per sizing, unificata per drawdown/kill switch.
- [ ] [idea] **Kill switch unrealised per Forex** — estendere drawdown check per includere MTM unrealised su posizioni leveraged.

**Fase 3 — OANDA integration**
- [ ] [idea] **OandaFeed** — implementa PriceFeed ABC, pricing stream OANDA v20 API
- [ ] [idea] **OandaExecutor** — implementa ExecutionGateway ABC, market orders + SL nativo floor + spread check pre-order
- [ ] [idea] **Gateway routing per asset class** — DefaultExecutionGateway ruota Binance vs OANDA in base a AssetClassRegistry
- [ ] [idea] **Telegram signal auto-routing** — attivazione monitor Telegram in produzione + routing segnali a executor corretto

**Fase 4 — Dashboard + UX**
- [ ] [idea] **Dashboard landing unificata** — `/dashboard/` overview (equity totale, P&L per asset class, posizioni aperte, status executor)
- [ ] [idea] **Dashboard split crypto/forex** — `/dashboard/crypto` e `/dashboard/forex` multi-page Streamlit, componenti condivise
- [ ] [idea] **Last Signals widget** — timestamp, symbol, direction, fill price, lot size, P&L corrente per segnali Telegram eseguiti
- [ ] [idea] **Config Health checklist** — tab dashboard con stato credenziali (OANDA, Binance, Telegram, DB) in plain language

### 🔵 Phase 3 (post-osservazione, quando hai 7-14+ giorni di dati)

- [ ] **Iterazione strategia**: variazioni SMA cross (parametri diversi), RSI threshold, MACD divergence
- [ ] **Multi-timeframe confirmation**: segnale 1h confermato da 4h
- [ ] **Multi-symbol portfolio rotation**: ranking dei symbol per momentum, allocazione dinamica
- [ ] **ExitPolicy** (Opzione 4): per strategie diverse (mean reversion, breakout, scalping)

### ⚪ Tech debt / minor

- [x] Pass feed/strategy registries into /v1/status endpoint (via app.state)
- [x] Define `PositionSide` StrEnum (replace plain str comment in ORM)
- [x] Forex weekend gap closure rule (market/hours.py + risk gate 4b)
- [x] Circuit breaker IngestionScheduler per Qdrant failures (exponential backoff)
- [ ] Alembic migration runner (sostituisce lo script custom `apply_migrations.py`)
- [ ] Persistent stop-loss event log (oggi in-memory, perso al restart)
- [ ] `fill_reconciliation` table per riconciliazione local DB ↔ exchange (live mode)
- [ ] Tier 3+4 features (kline WS stream, CoinGecko screener, hyperopt, Redis cache, Ollama LLM, Alembic auto-migration)

---

## Done — 2026-04-10

- [x] **Runtime Config feature** — DB-backed settings editable from dashboard (migration 012, service, API routes, 5 UI expanders, hot-reload)
- [x] Dashboard: symbols watchlist add/remove + rate limit budget bar (via Runtime Config)
- [x] Dashboard: edit thresholds globali SL/TP/trailing/DD/sizing (via Runtime Config)
- [x] Active hours mode — scheduler skips cycles outside configurable window (via Runtime Config)
- [x] Security: cryptography 46.0.6→46.0.7 (CVE-2026-39892), langchain-core 1.2.26→1.2.28 (CVE-2026-40087)
- [x] Bug 11 fix: dashboard "Run Agent Now" + history table show "intent" (OPEN LONG / CLOSE LONG / HOLD) instead of legacy "signal" labels
- [x] Telegram parser: supporto coppie Forex (USDCAD, XAUUSD, major) + inline entry fallback (SELL 1.38350)
- [x] .gitignore: aggiunto *.session (token auth Telethon)
- [x] Strategy aggressive tuning: SMA 5/13, RSI 40/60, confidence 0.3, position 5%, SL/TP 3%/5%
- [x] Crypto expansion Fase 1: default symbols da 2 a 25 (majors, L1, DeFi, L2, AI, Gaming, Meme)
- [x] Tech debt: /v1/status feeds+scheduler info, PositionSide enum, forex weekend gate, circuit breaker ingestion

## Done — 2026-04-09

- [x] SL/TP/trailing adattivo a CV (stop_loss.py) — formula `max(base, multiplier × CV)`, multiplier SL=2.5x, TP=5x, trail=1.5x
- [x] Per-symbol config table (migration 009 + model + repo + API CRUD + dashboard UI expander)
- [x] Fee propagation nel P&L (OrderResult.fee + runner + stop_loss auto_close)
- [x] API regex validator widened (case-insensitive, hyphens, underscores)
- [x] Bug 11 fix (HOLD risk_approved "—" instead of "❌")
- [x] Dashboard Open Positions decimali prezzi (%.8g per microcap)
- [x] Valutazione pleng → verdict "non adottare" (collisione Coolify + LLM lock-in + backup scope)
- [x] Handoff gravya-ops scritto (566 righe, da spostare a gravya-platform/)
- [x] git worktree trdex-llm + branch llm-agents creato e pushato

## Done — 2026-04-08

- [x] Intent enum refactor (24 decisioni, 308→312 test, commit 9ec41be)
- [x] VPS hardening (swap, fail2ban, UFW, sshd drop-in)
- [x] Kloud user + scoped sudoers + SSH key-only
- [x] Deploy trdex su Coolify (5 container, Bug 4-7 fixati, 3° attempt success)
- [x] Bug 8 fix: max drawdown realised-only (stop false KillSwitch 98%)
- [x] Bug 9 fix: pnl_history asyncpg interval make_interval()
- [x] Bug 10a/b: dashboard Ingest Now + error message unwrap
- [x] Dashboard deploy Streamlit su /dashboard/ con basic auth Traefik
- [x] Coolify env var label workaround (hardcoded hash, single quotes)
- [x] KillSwitch reset + scheduler production started
- [x] Phase 2 observation iniziata (BTC+ETH, poi +7 altcoin)
- [x] Commit identity fix (force-push rewrite Claude→Kloud trailer)

## Done — 2026-04-07 e precedenti

(vedi Daily Notes per dettagli storici)
- [x] Smoke level 1-4, migration runner, backtest engine, readiness gate v2
- [x] Agent scheduler extraction, PortfolioService write path, inspect_runs dashboard
- [x] Intent enum brainstorming (24 decisioni in decision log)
- [x] Tier 1+2 hardening, KillSwitch persistente, idempotency
- [x] Account balance ledger, Entity Graph Tier 5, SignalTracker
- [x] Onboarding + Phase 1-5 scaffold (2026-04-04/05)
