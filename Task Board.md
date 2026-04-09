# Task Board

## ⚠️ Sister branch — `llm-agents` (worktree `trdex-llm/`)

Rifacimento Phase 2 con LLM veri dentro Scout/Analyst/Risk/Executor.
Design doc da scrivere nella prossima sessione su `trdex-llm/`.
5 decisioni prese: LangChain abstractions, dashboard config pages,
active hours, reflection memory day 1, multi-agent reale day 1.
Workflow: fix su main → merge forward nel branch. Mai il contrario.

---

## Production status (2026-04-09 mattina)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/`
Scheduler: 9 symbols, 5 min interval, 1334 agent_runs in 24h
Trade chiusi: 12 (6W/6L, net +$9.65, win rate 50%)
Balance: $10,009.65 / peak $10,032.37
Fix deployato oggi: SL adattivo a CV + per-symbol config + fee nel P&L

---

## Backlog — ordinato per fase di maturazione

### 🔴 Blockers per live mode (da fare PRIMA di soldi veri)

- [ ] **Lot size compliance** — Il Simulator non rispetta i lot size / step size di Binance (es. ENJ ha lot size = 1 intero, ma il sistema calcola 6407.7529 token frazionali). In simulation mode non è un blocco ma i numeri P&L sono leggermente falsi. In live mode gli ordini verrebbero **rifiutati** dall'exchange. Fix: query `exchange.load_markets()` via CCXT al lifespan, cache dei min/step per symbol, truncare qty prima dell'ordine.
  - **Effort**: ~2-3h (lifespan markets load + executor qty truncation + test)
  - **Dove**: Simulator + LiveExecutor + lifespan

- [ ] **Open-side fee tracking** — Oggi solo la fee di close è sottratta dal P&L. La fee di open (0.1% Binance taker) non è tracciata nel PositionRecord → P&L gonfiato di ~0.1% per trade. Fix: aggiungere colonna `fee_open` a positions table (migration 010), scriverla in `record_open_fill`, sottrarre nel P&L di `record_close_fill`.
  - **Effort**: ~1h (migration + model + service + test)

- [ ] **Upgrade auth dashboard** — basic auth Traefik (popup browser) fa schifo, UX povera, no MFA, no lockout brute-force. Accettato per Phase 2 ma **non per live mode con soldi veri**.
  - **Opzioni**: (1) Cloudflare Tunnel + Access, (2) Tailscale VPN, (3) oauth2-proxy + GitHub OAuth
  - **Effort**: ~3-5h a seconda dell'opzione
  - **Trigger**: prima di live mode, dopo 1+ settimana Phase 2 stabile

- [ ] **Live executor test su Binance testnet** — il LiveExecutor esiste come scaffold ma non è mai stato testato con un exchange reale. Servono: account testnet Binance, API key testnet, test end-to-end (open + close + fee verification + lot size compliance).
  - **Effort**: ~3-4h

- [ ] **Reject default DB creds in non-dev modes** — la password DB è `trdex` in dev. Non deve essere accettata in production/live mode.
  - **Effort**: ~30 min

### 🟡 Miglioramenti Phase 2 (da fare con sistema che gira)

- [ ] **Dashboard: gestione symbols watchlist** (add/remove + rate limit estimate live)
  - Oggi: cambi symbols via Coolify UI env var + Restart
  - Target: sezione dashboard con add/remove + barra budget RPM
  - Backend: endpoint `POST /v1/agent/scheduler/symbols` + persistenza DB + hot-reload scheduler loop
  - **Effort**: ~3-5h

- [ ] **Dashboard: edit thresholds globali** (SL base / TP base / trailing base / daily DD / max DD / position sizing)
  - Oggi: env var Coolify + Restart
  - Target: form nel dashboard con sanity check + audit log
  - Backend: endpoint `POST /v1/risk/thresholds` + persistenza + hot-reload StopLossMonitor
  - **Effort**: ~2-3h

- [ ] **Active hours mode** — scheduler skippa cicli fuori fascia configurable (default 8-22 UTC)
  - Motivazione: ridurre rumore notturno (basso volume, segnali erratici)
  - Opzione A: skip in-process (~30 min). Opzione B: filter a lettura (~10 min)
  - **Trigger**: dopo 7 giorni di osservazione H24, valutare se i trade notturni hanno edge negativo

- [ ] **Perplexity Sonar come news source** — sostituisce CryptoCompare/StockData con ricerca LLM-native più densa in signal
  - Costo: ~$20/mese con sonar base
  - **Effort**: ~45-90 min
  - **Trigger**: dopo Phase 2 baseline, quando vuoi attivare il context AI nel decision engine

- [ ] **Multi-source price aggregation** — oggi il FeedManager usa solo Binance (failover chain, non aggregation). Per prezzo più robusto: interrogare N feed in parallelo, scartare outlier, ritornare mediana
  - **Effort**: ~2-3h
  - **Trigger**: non urgente per Phase 2, utile per live mode

- [ ] **Monitoring esterno VPS** — uptime kuma / healthcheck.io / Telegram alert
  - Copre: `/v1/health` uptime, disco, RAM, KillSwitch activation, scheduler tick drift
  - **Effort**: ~2h setup
  - **Trigger**: quando gravya-ops è attivo

### 🟢 Branch `llm-agents` (sessione separata su `trdex-llm/`)

- [x] **Design doc Rev 1** — `.claude/reports/llm-agents-design-2026-04-08.md` (8 sezioni + review log)
  - Multi-agent brainstorming: 23 objections, 18 accepted, 3 deferred, 1 rejected
  - 4 critical revisions applied: prompt heuristics removed, conditional calling redesigned, LLMCaller injection, RAG sanitization day-1

- [x] **Task 1-7: ALL COMPLETE** — committed `d294159`, `a4d2dcb`, `4af323a`. Pushed.
  - Provider abstraction + LLMCaller + 3 migrations + structured output schemas
  - LLM Analyst (dual path + prompt builder + RAG sanitizer)
  - LLM Scout (dual path + sentiment calibration)
  - Dashboard config pages (4 agents + cost forecast + fallback banner + restore default)
  - Reflection memory (wired in Task 2)
  - Redis cost guardrails (LLMBudgetTracker)
  - Risk annotation (optional Haiku)

- [ ] **Deploy trdex-llm on Coolify** — see `docs/deploy-llm-instance.md`
  - DNS `trdex-llm.gravya.it` created
  - Needs: Coolify app setup, ANTHROPIC_API_KEY, OAuth callback URL

- [ ] **Task 8: Evaluation framework** (deferred — needs live data from deployed instance)
  - 50 golden scenarios, LLM vs rule engine A/B, directional consistency tests

### 🔵 Phase 3 (post-osservazione, quando hai 7-14+ giorni di dati)

- [ ] **Iterazione strategia**: variazioni SMA cross (parametri diversi), RSI threshold, MACD divergence
- [ ] **Multi-timeframe confirmation**: segnale 1h confermato da 4h
- [ ] **Multi-symbol portfolio rotation**: ranking dei symbol per momentum, allocazione dinamica
- [ ] **ExitPolicy** (Opzione 4): per strategie diverse (mean reversion, breakout, scalping)

### ⚪ Tech debt / minor

- [ ] Pass feed/strategy registries into create_app() for /status endpoint
- [ ] Alembic migration runner (sostituisce lo script custom `apply_migrations.py`)
- [ ] Circuit breaker IngestionScheduler per Qdrant failures
- [ ] Define `PositionSide` enum (replace plain str in ORM)
- [ ] Forex weekend gap closure rule
- [ ] Persistent stop-loss event log (oggi in-memory, perso al restart)
- [ ] `fill_reconciliation` table per riconciliazione local DB ↔ exchange (live mode)
- [ ] Tier 3+4 features (kline WS stream, CoinGecko screener, hyperopt, Redis cache, Ollama LLM, Alembic auto-migration)

---

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
