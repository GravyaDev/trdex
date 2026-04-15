# Task Board

## ⚠️ Branch `llm-agents` (worktree `trdex-llm/`)

Rifacimento Phase 2 con LLM veri dentro Scout/Analyst/Risk/Executor.
Design doc: `.claude/reports/llm-agents-design-2026-04-08.md`
Workflow: fix su main → merge forward nel branch. Mai il contrario.

---

## Production status (2026-04-15)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/`
Scheduler: 10 symbols liquidi (post-tuning 2026-04-15), 5 min interval
Strategy: SMA 9/21, RSI direzionale (>50 BUY / <50 SELL, filtri 30/70). SL 2% / TP 4% / trailing 1.5%.
Runtime Config: DB-backed, editable da dashboard. `gate_min_days=20`.
Telegram monitor: 30 canali (18 signal + 12 news), evaluator ogni ora.
Auth: GitHub OAuth via oauth2-proxy.

---

## 🟢 Historical Market Episode RAG — ✅ COMPLETE

8 step completati in sessione 2026-04-10. Pipeline end-to-end:
1. Helpers estratti in `backtest/indicators.py`
2. `scripts/backfill_ohlcv.py` — paginazione Binance + upsert TimescaleDB
3. `memory/market_episodes.py` — detect regime changes + Qdrant store/service
4. `scripts/generate_episodes.py` — batch OHLCV → episodes → Qdrant
5. `memory/context.py` — Tier 4b field + loader wiring + prompt rendering
6. `api/app.py` lifespan — `MemoryContextLoader` con `MarketEpisodeService` + analyst propaga closes/volumes
7. `memory/market_brief.py` — sezione 0 prompt + KB block `HEUR-ANALYST-RAG-001`
8. 32 test (24 episodes + 9 brief), 344/344 totali pass

**Da fare per attivarlo in produzione**:
- Deploy su Coolify trdex-llm (quando vuoi)
- Eseguire `python -m trdex.scripts.backfill_ohlcv SYMBOL --days 365` per ogni symbol
- Eseguire `python -m trdex.scripts.generate_episodes --all` per popolare Qdrant
- Configurare Jina/Qdrant env var

---

## 🟡 Pending — llm-agents branch

- [ ] **Deploy trdex-llm on Coolify** — see `docs/deploy-llm-instance.md`
  - DNS `trdex-llm.gravya.it` created
  - Needs: Coolify app setup, ANTHROPIC_API_KEY, OAuth callback URL

- [ ] **Task 8: Evaluation framework** (deferred — needs live data)
  - 50 golden scenarios, LLM vs rule engine A/B, directional consistency tests

- [x] **Active hours mode** — già implementato (scheduler.py `_parse_active_hours` + `_is_active_now`, config via RuntimeConfig)

- [x] **Manual open/close positions** — mergiato da main 2026-04-15. `POST /v1/portfolio/open` + `POST /v1/portfolio/close/{id}` + dashboard button.

### 🟣 Telegram Signal Step 2 — Auto-execute (mergiato da main, pending implementazione)

- [ ] [telegram] **2.1 Symbol router** — `execution/symbol_router.py` → `(PriceFeed, ExecutionGateway)` in base a `is_forex(symbol)`.
- [ ] [telegram] **2.2 TelegramSignalExecutor** — `execution/telegram_executor.py`: flow route → market hours → risk gates → fetch price → qty = budget/price → place order con `source="telegram"` → memorizza TP/SL in `position.note`.
- [ ] [telegram] **2.3 TG risk gates** — budget `settings.telegram_signal_budget`, max 3 open per asset class, reliability gate (win_rate < 0.5 dopo 20 signal → skip).
- [ ] [telegram] **2.4 SL adattato a TP/SL del segnale** — `stop_loss.py` legge TP/SL da `position.note` se `source=="telegram"`.
- [ ] [telegram] **2.5 Wire up in lifespan** — `_telegram_background` → `telegram_executor.execute(signal, budget)`.
- [ ] [telegram] **2.6 Dashboard TG positions panel** — positions `source='telegram'` con entry/current/TP/SL/pnl% + "close now".
- [ ] [telegram] **2.7 Test simulation mode** — `TRDEX_MODE=simulation` + budget simbolico $10 prima di live.

Go-live gate: Step 1 positivo + OandaExecutor + review manuale primi 5 segnali.

### 🟠 Multi-asset (Forex + crypto) — mergiato da main, design approvato

- [ ] AssetClassRegistry + symbol normalizer (XAUUSD→XAU/USD)
- [ ] Migration 014: asset_class + leverage su `positions`
- [ ] RiskProfile per asset class (sizing separato, drawdown unificato)
- [ ] Kill switch unrealised per Forex leveraged
- [ ] OandaFeed + OandaExecutor (pricing stream + market orders + SL nativo)
- [ ] Gateway routing per asset class (Binance vs OANDA)
- [ ] Dashboard split crypto/forex + landing unificata + Last Signals widget

### ⚪ Nuovi feed (mergiati da main 2026-04-15)

- [x] **YFinanceFeed** — forex/commodity/index OHLCV + price parity (commit `ffb22a7`).
- [ ] **TwelveDataFeed** — feed forex prioritario (800 req/day free) con yfinance come fallback. API key già nel Runtime Config.
- [ ] **Binance Square signals feed** — terza fonte segnali (dopo Telegram + news API).

---

## 🔴 Blockers per live mode (tutti risolti su main, mergiati in llm-agents)

✅ Tutti i blocker originali sono stati risolti su main e mergiati in llm-agents:
- Lot size compliance (`market/specs.py` + `truncate_qty()`)
- Open-side fee tracking (migration 010 + `fee_open` column)
- Reject default DB creds (guard in `app.py` lifespan)
- Live executor test (Ed25519 testnet passed)

---

## 🛡️ Security corrective tasks (da security scan 2026-04-10)

- [x] **[HIGH] Harden verify_api_key** — FIXED 2026-04-11 (commit `d4fff2b`).
- [x] **[MEDIUM] credentials_crypto fail-closed** — FIXED via merge da main (`38b2906`). `init_cipher()` raise `RuntimeError` su key invalid, `decrypt()` raise `DecryptionError` su wrong-key.
- [x] **[MEDIUM] Rate limiter X-Forwarded-For** — FIXED via merge da main (`220d81a`). `_real_client_ip()` legge `X-Forwarded-For`, fallback a `get_remote_address`.
- [x] **[MEDIUM] Telegram evaluator NaN/inf** — FIXED via merge da main (`38b2906`). `_parse_note()` rifiuta NaN/inf/negativi/zero.
- [x] **[MEDIUM] Sanitize memory snapshot text** — FIXED 2026-04-12 (commit `edb796b`). `sanitize_rag_content()` wrappa `memory_text` in entrambi `build_analyst_messages` e `build_scout_messages`.
- [x] **[LOW] CLI input validation** — FIXED 2026-04-12 (commit `edb796b`). Symbol regex, --days cap 3650, window/stride > 0.
- [x] **[LOW] Mode gate su `/v1/debug/*`** — FIXED via merge da main (`d737386`). Debug endpoints return 403 outside simulation.
- [x] **[LOW] Lifespan boot-guard regression test** — FIXED 2026-04-12 (commit `edb796b`). 3 test condizionali guard logic.

---

## 🔵 Phase 3 (post-osservazione, 7-14+ giorni dati)

- [ ] Iterazione strategia (variazioni SMA cross, RSI threshold, MACD divergence)
- [ ] Multi-timeframe confirmation (1h confermato da 4h)
- [ ] Multi-symbol portfolio rotation (ranking momentum, allocazione dinamica)
- [ ] ExitPolicy (Opzione 4): strategie diverse (mean reversion, breakout, scalping)

---

## ⚪ Tech debt / minor

Risolti via merge da main oggi:
- [x] `/status` endpoint con feed/strategy registries (via `app.state`)
- [x] `PositionSide` enum in ORM
- [x] Forex weekend gap closure rule (`market/hours.py` + risk gate 4b)
- [x] Circuit breaker IngestionScheduler per Qdrant failures

Risolti via merge da main 2026-04-11:
- [x] Persistent stop-loss event log (migration 013 + `StopLossEventRepository` + hydrate da DB)
- [x] Runtime config credentials encrypted at rest (Fernet, migration `credentials_crypto.py`)
- [x] Stale ticker detection (Binance feed raises `StaleTickerError` dopo 5 min)

Aperti:
- [ ] Alembic migration runner (sostituisce script custom)
- [ ] `fill_reconciliation` table per riconciliazione DB ↔ exchange (live mode)
- [ ] Tier 3+4 features (kline WS stream, CoinGecko screener, hyperopt, Redis cache, Ollama LLM)

---

## Done — 2026-04-11

- [x] **Dep vuln patch**: cryptography 46.0.6→46.0.7, langchain-core 1.2.24→1.2.28, uv 0.11.3→0.11.6, orphan fastmcp removed
- [x] **Kloudify upgrade v1.1.2→v1.2.2** (commit `fd659f1`): 11 infra files + install.sh replaced + new `check-quality-gate.sh` hook
- [x] **Merge forward #3** from main (commit `c022062`): 9 commits — StaleTickerError, gate_min_days 30→25, Telegram Step 1 observe-only, encrypted credentials (Fernet), persistent stop_loss events, /v1/status extended, numeric chat_id, compose wiring
- [x] **Security HIGH closed**: verify_api_key fail-open fixed (commit `d4fff2b`) — two-layer fix (lifespan guard + runtime 503), 6 regression tests
- [x] 372/372 test pass (was 344)

## Done — 2026-04-10

- [x] **Merge forward #1** `origin/main` → `llm-agents` (Runtime Config + aggressive tuning, 0 conflitti)
- [x] **Historical Market Episode RAG pipeline COMPLETE** (Step 1-8): backfill, episodes, generate, context integration, scheduler wiring, market brief, 33 test (commit `0431781`)
- [x] **Merge forward #2** `origin/main` → `llm-agents` (tech debt fixes: /status, PositionSide, forex hours, circuit breaker, StopLoss Binance pin), `app.py` auto-merge pulito, Task Board preservato (commit `0121bc6`)
- [x] 344/344 test pass dopo entrambi i merge
- [x] Push `llm-agents` su origin

## Done — 2026-04-09

- [x] LLM agents Task 1-7 ALL COMPLETE (provider abstraction, Analyst/Scout LLM, dashboard config, budget guardrails, risk annotation)
- [x] Deploy guide `docs/deploy-llm-instance.md`
- [x] Design doc Rev 1 (23 objections reviewed)
- [x] OAuth2-proxy GitHub auth
- [x] Ed25519 testnet test passed — LiveExecutor production-ready
- [x] Perplexity Sonar news source
- [x] Multi-source price aggregation (user-selectable feeds)
- [x] SL/TP/trailing adattivo a CV
- [x] Per-symbol config + fee propagation P&L
- [x] Dashboard symbols management + thresholds edit + rate limit estimate

## Done — 2026-04-08

- [x] Intent enum refactor (312 test pass)
- [x] VPS hardening + Kloud user + deploy Coolify (5 container)
- [x] Phase 2 observation started (BTC+ETH → 9 symbols → 25 symbols)
- [x] Commit identity fix
