# Task Board

## Production status (2026-04-12)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/`
Scheduler: 25 symbols, 5 min interval. Strategy: SMA 5/13, RSI 40/60. Tests: 359/359.
Telegram monitor: 30 canali attivi (18 signal + 12 news), streaming=true, evaluator ogni ora.
Credentials encrypted at rest (Fernet). Kloudify v1.2.2.

## Next Session

- Monitorare dashboard "🟣 Telegram Signals" — confermare segnali e news dai 30 canali
- Cercare i 58 canali mancanti (`channels_failed_lookup.md`) e aggiungerli dal dashboard
- Manual open/close positions (backlog 🟡)

---

## Backlog — ordinato per fase di maturazione

### 🔴 Blockers per live mode (da fare PRIMA di soldi veri)

- [x] **[SEC HIGH] credentials_crypto wrong-key silent fallback** — done 2026-04-12. decrypt() now raises DecryptionError. Prevents passing ciphertext to APIs.
- [x] **[SEC HIGH] credentials_crypto passthrough su env var malformata** — done 2026-04-12. init_cipher() raises RuntimeError when key is set but invalid.
- [x] **[SEC MEDIUM] evaluator input validation** — done 2026-04-12. _parse_note + score_signal reject NaN/inf/negative/wildly-out-of-range targets/stops.
- [x] **[SEC MEDIUM] rate limiter X-Forwarded-For** — done 2026-04-12. Real client IP from XFF header behind Traefik.
- [x] **[SEC LOW] signal dedup** — done 2026-04-12. 60s window dedup in _telegram_background.
- [x] **[SEC LOW] _persist_event failure alerting** — done 2026-04-12. CRITICAL log after 3+ consecutive DB write failures.
- [x] **Lot size compliance** — GIA' IMPLEMENTATO: `market/specs.py` con `truncate_qty()` chiamato da Simulator + LiveExecutor, caricato al lifespan via CCXT `load_markets()`

- [x] **Open-side fee tracking** — GIA' IMPLEMENTATO: `fee_open` column (migration 010), salvato in `record_open_fill()`, sottratto in `record_close_fill()` P&L

- [x] **Live executor test su Binance testnet** — DONE (Ed25519 test passed, lot size compliance implementata)

- [x] **Reject default DB creds in non-dev modes** — GIA' IMPLEMENTATO: `app.py:133-139` blocca startup con creds default fuori da simulation

### 🟡 Miglioramenti Phase 2 (da fare con sistema che gira)

- [ ] **Manual open/close positions** — `POST /v1/portfolio/open` (symbol, side, amount) + `POST /v1/portfolio/close/{position_id}` + dashboard "Close" button per posizione. Permette intervento manuale senza aspettare l'agent loop o lo SL monitor.

### 🟠 Multi-asset expansion (Forex + crypto broadening)

Design approvato dal multi-agent brainstorm 2026-04-10. Decision log in
`.claude/reports/brainstorm-2026-04-10-multi-asset.md`.

**Fase 1 — Crypto expansion (zero codice)** — DONE
- [x] **Espandere a 25 crypto symbols** — defaults aggiornati in docker-compose + config (commit `612b662`). Attivazione in produzione via dashboard Settings.

**Fase 2 — Fondamenta multi-asset**
- [ ] [idea] **AssetClassRegistry + symbol normalizer** — classify() con normalizzazione (XAUUSD→XAU/USD), config-based precedence per symbol ambigui, enum AssetClass(CRYPTO, FOREX)
- [ ] [idea] **Migration 014: asset_class + leverage su positions** — default 'crypto'/1.0 su righe esistenti. Nessun NULL. (Was numbered 011 but that slot is taken by signal_outcomes_nullable_exit.sql)
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

### 🟣 Telegram Signal Integration (Zanni feasibility — 2026-04-11)

Verificato empiricamente sui segnali di Matteo Zanni (18/20 confermati reali via yfinance, +$15.64 netto su 20 trade con $10 × leva 50). Decision: NON replicare il criterio come rule engine (scalping discrezionale non è automatizzabile), MA consumare i suoi segnali via Telegram monitor e piazzare ordini nel nostro sistema. Infrastruttura al 60% già presente.

**Stato componenti**:
- [x] Parser `telegram/parser.py` — legge formati Zanni (GBPUSD SELL, BUY XAUUSD, TP1/2/3, SL)
- [x] Monitor `telegram/monitor.py` — Telethon wrapper async + backpressure queue
- [x] Tracker `telegram/tracker.py` + DB `signal_outcomes`
- [x] ForexFeed `market/feeds/forex.py` (EUR/USD, GBP/USD, XAU/USD)
- [x] Market hours gate `market/hours.py:is_market_open()` (weekend Forex closure)
- [x] Runtime Config per credenziali Telegram hot-reload

**Step 1 — Observe-only** (1h, zero capitale a rischio)

Attiva il monitor, parsea i segnali in arrivo, salva in `signal_outcomes` SENZA aprire posizioni. Dopo 1 settimana avremo il tasso di successo reale misurato sui NOSTRI prezzi (non sul broker di Zanni).

- [ ] [telegram] **1.1 Credenziali Telegram** — creare API ID/Hash su https://my.telegram.org. Via dashboard Runtime Config → Settings → API Keys, inserire `telegram_api_id`, `telegram_api_hash`, `telegram_phone`, `telegram_channels` (CSV dei canali Zanni)
- [ ] [telegram] **1.2 Login one-time** — da container app via `docker exec`: `/app/.venv/bin/python scripts/telegram_login.py`. Crea `trdex_telegram.session`. Volume mount necessario per persistenza restart (vedi docker-compose `volumes:` del container app)
- [ ] [telegram] **1.3 Abilitare monitor in lifespan** — già pronto in `api/app.py:199-227`: instanzia `TelegramMonitor` se `telegram_api_id != 0`. Basta settare le credenziali al punto 1.1 + Coolify restart
- [x] [telegram] **1.4 Observe-only handler** — done 2026-04-11 (commit `bd4fb70`). `_telegram_background()` persiste ogni signal con exit_price=NULL, budget=0, note=json(targets, stop_loss). Migration 011 rende exit_price nullable.
- [x] [telegram] **1.5 Dashboard signals viewer** — done 2026-04-11 (commit `bd4fb70`). Expander 🟣 Telegram Signals con 4 metric + tabella per-source (win_rate, roi_pct) + tabella recent 50. `/v1/signals` arricchito con report + recent.
- [x] [telegram] **1.6 Post-fatto TP/SL evaluation job** — done 2026-04-11 (commit `bd4fb70`). Nuovo `telegram/evaluator.py`: `score_signal()` puro (first-touch, ambiguous→SL), `evaluator_loop()` schedulato ogni 3600s, timeframe auto (5m/15m/1h). Signals >24h → stale.

**Observation gate**: dopo 7 giorni di observe-only, se `signal_tracker.stats(source).win_rate >= 0.6` e `roi_pct >= 5%` su almeno 20 segnali, procedi con Step 2. Altrimenti blacklist il canale e ferma.

**Step 2 — Auto-execute** (2-3h, dopo Step 1 confermato)

Aggiungere esecuzione reale dei segnali validati, con budget fisso e risk gates.

- [ ] [telegram] **2.1 Symbol router** — `execution/symbol_router.py` nuovo modulo: funzione `route_for_symbol(symbol: str) -> tuple[PriceFeed, ExecutionGateway]`. Logica: se `is_forex(symbol)` → ForexFeed + OandaExecutor (da implementare), altrimenti BinanceFeed + LiveExecutor/Simulator. Discriminatore usa `market/hours.py:is_forex()` già esistente
- [ ] [telegram] **2.2 TelegramSignalExecutor** — nuovo modulo `execution/telegram_executor.py`. API: `async execute(signal: TelegramSignal, budget: Decimal) -> Position | None`. Flow: (a) route symbol → feed+gateway, (b) check market hours, (c) check risk gates (max open TG positions, reliability gate, kill switch), (d) fetch current price via feed, (e) calcola qty = budget / current_price, (f) place order via gateway con `source="telegram"`, (g) memorizza TP/SL dal signal in `position.note` JSON per stop_loss_monitor
- [ ] [telegram] **2.3 TG risk gates** — in TelegramSignalExecutor, prima del place():
  - Budget: usa `settings.telegram_signal_budget` ($100 default)
  - Max open positions per asset class: query DB `positions WHERE status='open' AND source='telegram'` — blocca se > 3 per asset class
  - Reliability gate: se `tracker.stats(signal.source).win_rate < 0.5 AND total_signals >= 20` → skip con log
  - Kill switch (globale) check, market hours check già disponibili
- [ ] [telegram] **2.4 Stop-loss adattato a TP/SL del segnale** — estendere `stop_loss.py` per leggere TP/SL dalla `position.note` JSON se `source=="telegram"`; invece della formula adaptive CV, usa i target del signal. Chiudi al tocco TP1 (o dynamic: TP2/TP3 con trailing). Su SL touch → close + record outcome negativo
- [ ] [telegram] **2.5 Wire up in lifespan** — in `_telegram_background()` sostituire il record-only handler con: `await telegram_executor.execute(signal, budget=settings.telegram_signal_budget)` seguito dal tracking
- [ ] [telegram] **2.6 Dashboard TG positions panel** — nuovo expander dashboard: positions dove `source='telegram'`, con entry/current/TP/SL/pnl%, pulsante "close now" per emergency exit
- [ ] [telegram] **2.7 Test isolato simulation mode** — prima di live: settare `TRDEX_MODE=simulation` + `telegram_signal_budget=10` (dollaro simbolico) per verificare che il pipeline funzioni end-to-end senza capitale reale

**Go-live gate**: Step 2 parte solo dopo: (1) Step 1 dati positivi, (2) OandaExecutor implementato (vedi Multi-asset expansion Fase 3), (3) review manuale dei primi 5 segnali eseguiti in simulation

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
- [x] Persistent stop-loss event log — done 2026-04-11. Migration 013 crea `stop_loss_events`, ORM + repo nuovi, `StopLossMonitor._persist_event()` scrive best-effort, `_hydrate_events_from_db()` ricarica gli ultimi 50 + counter cumulativo all'avvio. `/v1/risk/status.events_fired` ora è persistente.
- [ ] `fill_reconciliation` table per riconciliazione local DB ↔ exchange (live mode)
- [ ] Tier 3+4 features (kline WS stream, CoinGecko screener, hyperopt, Redis cache, Ollama LLM, Alembic auto-migration)
- [ ] **Binance Square signals feed** — `https://www.binance.com/en/square/hashtag/signals` come terza fonte di segnali (accanto a Telegram + news API). Richiede API pubblica o RSS/Atom feed (scraping è contro ToS). Segnali da trader verificati con track record. Valutare quando disponibile.
- [ ] **TwelveDataFeed** — feed forex/commodity OHLCV via Twelve Data API (800 req/day free, più veloce e affidabile di yfinance). API key già nel Runtime Config (`twelve_data_api_key`). Implementare come feed prioritario con yfinance come fallback.

---

## Done — 2026-04-11

- [x] **StaleTickerError + delisted symbol swap** (commit `bd3e8bf`) — `BinanceFeed.get_ticker()` rigetta tickers > 5 min di età, fix phantom gain +$1721 da RNDR/MATIC delisted. Symbol defaults: RNDR→RENDER, MATIC→POL.
- [x] **Gate readiness 30→25 days** (commits `496b4d1` config.py + `9fe0b63` compose) — accorciare Phase 2 sim time dopo nuclear DB reset.
- [x] **Nuclear DB reset produzione** — TRUNCATE positions/balance/agent_runs/signal_outcomes + re-seed balance $10k (19 righe corrotte pulite).
- [x] **Zanni signals historical verification** — 18/20 confermati via yfinance, +$15.64 P&L simulato $10×50 leverage, win rate 94.7%. Decision: consumare segnali via Telegram monitor, NON ricostruire rule engine.
- [x] **Telegram Step 1 observe-only** (commit `bd4fb70`) — sub-task 1.4 (observe handler + migration 011 exit_price nullable), 1.5 (dashboard expander + `/v1/signals` arricchito), 1.6 (evaluator.py score_signal + evaluator_loop schedulato ogni 3600s). 315→328 test.
- [x] **`/v1/status` extended telegram visibility** (commit `47c0531`) — aggiunge `signals_tracked` + `evaluator_running` per verifica post-deploy.
- [x] **Telegram numeric chat_id + discovery scripts** (commit `fbcc9e6`) — `_normalize_channels()` coerces digit strings to int per supporto canali privati. Nuovi `scripts/telegram_list_channels.py` + `scripts/telegram_join_channel.py`.
- [x] **Security HIGH: credentials_crypto Fernet encryption** (commits `efefabb` + `d5372f9`) — runtime_config.credentials cifrati at-rest con Fernet, key da `TRDEX_CONFIG_ENCRYPTION_KEY` env var, migrate_plaintext_credentials() idempotente, compose wiring completo, 13 nuovi test.
- [x] **Persistent stop-loss event log** (commit `ada5930`) — migration 013, ORM `StopLossEventRecord`, repository, `_hydrate_events_from_db()` + `_persist_event()` best-effort, `status.events_fired` è ora counter cumulativo persistente. 5 nuovi test. 328→334 test.
- [x] **Kloudify upgrade v1.1.2 → v1.2.0** — install.sh upgrade, 2 nuovi hook `check-quality-gate.sh` applicati, 6 conflict file risolti (settings.json sovrascritto integralmente), backup `.claude.pre-upgrade-20260411-183957/`.
- [x] **llm-agents merge-forward handoff** (`docs/handoff-main-to-llm-agents-2026-04-11.md`) — documenta 9 commit con aree di conflitto e step di merge per il worktree sister `trdex-llm/`.
- [x] **`.claude/reports/` cleanup** — 6 file obsoleti rimossi (2 deep-audit ormai chiusi, brainstorm-intent-enum completato, 2 changeset runtime-config/multi-asset coordination superati, session-handoff-04-08-deploy-wip risolto), 2 mantenuti (brainstorm-multi-asset design decisions, guida-ssh runbook).

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
- [x] Bug fix: StopLoss price pinned to Binance — prevents cross-feed P&L distortion (MATIC +49%, RNDR +40% phantom gains)
- [x] Telegram signals standalone extraction (telegram-signals/ — parser, monitor, tracker, DB, tests, README)

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
