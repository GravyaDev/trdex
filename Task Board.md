# Task Board

## Production status (2026-04-17)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/` — **nuova app Coolify UUID `e5tqc26vgsnm6czy8wnqpxl2`** (riconnessa oggi a GitHub App source, DB wiped — accettato).
Scheduler: 10 symbols, 5 min interval. Strategy: SMA 9/21, RSI direzionale >50/<50 + overextension >70/<30. SL 2%, TP 4%, trailing 1.5%. Gate readiness 20gg.
Tests: 359/359. Telegram monitor: 36 canali ri-inseriti manualmente (auto-classified signal/news), evaluator ogni ora. Kloudify v1.3.3.
**Auto-deploy Coolify FUNZIONA** end-to-end (GitHub App→push→rebuild→restart, confermato 2026-04-17 con commit `1fd4060`).
DB fresh — $10k seed da reconfigurare se serve.

## Next Session

- **[P1] Hot-reload integration toggles** — oggi cambiare un toggle in Runtime Config → `integrations` richiede restart container. Implementare `unregister()` su `PriceFeedManager` + `IngestionScheduler` + safe stop/start su `TelegramMonitor` per supportare hot-reload. Effort stimato: ~2-3h. File primari: `src/trdex/market/manager.py`, `src/trdex/market/ingestion.py`, `src/trdex/telegram/monitor.py`.
- **[P3] Issue #1 CoinGecko `supports_symbol` filter** — residuo di https://github.com/GravyaDev/trdex/issues/1 dopo fix Binance (2026-04-17). Implementare `supports_symbol(symbol: str) -> bool` predicate su `CoinGeckoFeed` + filter nel `PriceFeedManager._rate_limited_call` per skippare feed che non supportano il simbolo. Effort ~30 min. Low priority (pure log hygiene).
- **[P1] Osservazione post-reset** — 5-7gg con nuova strategia. Target $20-30/giorno. Verificare win rate reale su ≥20 trade chiusi. (Nota dalla sim 2026-04-16: la retro-simulation sul parametro sweep suggerisce che trailing 2.5% > trailing 1.5% — +$19.21 vs +$0.54 sui 26 trade, ma sample troppo piccolo per cambiare adesso.)
- **[P2] Auto-resolve Telegram channel names on CSV save** — quando un utente salva `telegram_channels` in Runtime Config, un endpoint `/v1/telegram/resolve-channels` chiama `client.get_entity(chat_id)` per ogni token, popola una mappa `telegram_channel_titles` (JSON runtime_config key) e il widget dashboard mostra "Nome · chat_id" invece di solo chat_id. Eager al save + lazy fallback ai messaggi in arrivo. Effort ~30-45 min.
- **[P2] Merge-forward `main` → `llm-agents`** — handoff in `docs/handoff-main-to-llm-agents-2026-04-15.md`. Sessione separata su `trdex-llm/`.
- **[P3] 58 canali mancanti** — cercare da `channels_failed_lookup.md` e aggiungere dal dashboard
- **[P3] Cleanup orphan volumes** — dismettere `w35035ypb7dl7t94flyn9c5f_{pgdata,redis,qdrant,telegram-session}` (~70MB pgdata + others) dal VPS via `docker volume rm` quando sicuro del nuovo deploy

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

- [x] **Manual open/close positions** — done 2026-04-15 (commit `a15bd84`). `POST /v1/portfolio/open` + `POST /v1/portfolio/close/{id}` + dashboard Close button + Manual Open form. Gateway-routed (fees/slippage/kill-switch applied).

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

### 🟤 CI/CD & automation

- [ ] **Auto-redeploy su push via Coolify GitHub App** — oggi ogni deploy richiede click manuale su Coolify "Redeploy". Diagnostica 2026-04-16: il checkbox "Auto Deploy" in Coolify è sempre stato ✓ ma **nessun webhook è registrato su GitHub** (`gh api repos/GravyaDev/trdex/hooks` → `[]`). Il flag è decorativo senza canale di ingresso degli eventi push.
  - **Step 1 — install Coolify GitHub App**:
    - Coolify UI → **Sources** → **GitHub** → **+ New** → **GitHub App**
    - Segui il flow di autorizzazione, installa la App sull'org `GravyaDev`
    - Seleziona i repo: minimo `trdex`, considera tutti i futuri (gravya-platform, gravya-ops, trdex-llm)
  - **Step 2 — ri-connetti l'app `trdex`** in Coolify alla nuova sorgente "GitHub App" (se attualmente è su "Public Repository"). Questo fa creare automaticamente il webhook su GitHub.
  - **Step 3 — verifica**:
    - `gh api repos/GravyaDev/trdex/hooks` → deve mostrare un webhook verso `coolify.gravya.it`
    - Fai un commit di smoke (es. `docs: test auto-deploy`) e push → controlla log Coolify e deliveries del webhook GitHub (Settings → Webhooks → Recent Deliveries)
  - **Step 4 — Actions granulari separate** (divisione responsabilità):
    - La GitHub App fa **solo** il redeploy Coolify
    - Le Actions in `.github/workflows/` fanno **solo** le azioni custom (pull su folder VPS non gestita da Coolify, notifiche Telegram/Slack, lint/test pre-push check, migrations)
    - Se un workflow esistente include uno step `curl -X POST .../coolify/.../deploy`, **rimuoverlo** — è ridondante dopo l'install della App
  - **Step 5 — race condition awareness**: se le Actions granulari contengono post-deploy actions (es. smoke test endpoint), aggiungere polling health check (`curl --retry 30 --retry-delay 2 $ENDPOINT/health`) perché App e Actions partono in parallelo su `on: push`, non in sequenza.
  - **Step 6 — coerenza multi-repo**: dopo trdex, replicare su `gravya-platform`, `gravya-ops`, `trdex-llm`. Un solo install App = tutti i repo coperti.
  - **Perché ora**: il fix evaluator Telegram (commit `632f084`) sarebbe stato già in produzione senza intervento manuale.

- [ ] **Guida LLM: setup auto-deploy Coolify + Actions granulari** — creare playbook riutilizzabile per adottare la stessa soluzione su tutti i progetti Gravya. Modellato sul pattern di `.claude/reports/guida-ssh-progetto.md` (che documenta il setup SSH key-per-project). Destinatario: agenti LLM (Claude/altri) che aprono una sessione su un nuovo progetto e devono implementare auto-deploy.
  - **Location**: `docs/playbook-coolify-autodeploy.md` (in `docs/` perché committato e findable cross-session, non in `.claude/` che è gitignored)
  - **Struttura**:
    1. Quando usare questa soluzione (signal: "Coolify deploy è manuale, Auto Deploy ✓ ma non fa nulla")
    2. Check pre-requisiti (`gh api repos/ORG/REPO/hooks` → se `[]` allora serve setup)
    3. Install GitHub App step-by-step (UI Coolify, selezione repo, verify)
    4. Pattern divisione responsabilità App vs Actions (con esempio concreto workflow granulare)
    5. Race condition handling (health check polling snippet pronto da copiare)
    6. Diagnostica: cosa guardare se deploys non partono (webhook deliveries, Coolify app logs, branch filter, path filter)
    7. Template workflow `.github/workflows/post-deploy.yml` con steps granulari comuni (git pull su folder, notifica Telegram)
  - **Invariant**: il playbook NON deve includere credenziali o token — tutto via GitHub Secrets + Coolify env.
  - **Quando**: dopo aver completato il setup su trdex (task sopra) e averlo verificato funzionante. Scrivere il playbook dall'esperienza vissuta invece che a priori.

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

## Done — 2026-04-17

- [x] **Telegram evaluator fix verified in prod** — Coolify rebuild (Force Rebuild required, normal "Redeploy" riusa cache layers) deploys commit `632f084` (yfinance in pyproject). yfinance 1.3.0 installato nel container, cascade feed cryptocompare→alphavantage→yfinance funzionante. Primo signal risolto: `BUY XAU/USD id=5 → tp @ 4821.0`.
- [x] **Dashboard simulated P&L per Telegram signals** (commit `161f179`) — widget 🟣 Telegram Signals ora calcola ROI% reale + $100/signal sim P&L on-the-fly da `entry_price`/`exit_price` dei `recent_rows`. Zero backend change. 5 metric header (Signals, Open, Closed, Win rate, Sim P&L) + per-source table + enriched recent table.
- [x] **TwelveDataFeed impl** (commit `fd90dfa`) — `market/feeds/twelvedata.py` primary Forex/commodity feed, 800 req/day free tier, native symbol format (XAU/USD, EUR/USD — no mapping). Registrato in manager prima di yfinance (che resta fallback), gated da `config_svc.get("credentials", "twelve_data_api_key")`. Doc fetched da api.twelvedata.com via Jina Reader.
- [x] **Mako security pin** (commit `1fd4060`) — mako 1.3.10 → 1.3.11 per GHSA-v92g-xgxw-vvmm (path traversal alembic transitive). pyproject pin + uv lock. Dependabot alert #5 chiuso.
- [x] **Coolify auto-redeploy setup** — GitHub App installata su org `GravyaDev` con Webhooks Read&Write. App trdex riconnessa a GitHub App source → Coolify ha ricreato nuova applicazione UUID `e5tqc26v...` (DB volumes wiped — accettato). Save su Configuration→Source + push di test → rebuild automatico partito entro secondi, container deployed in ~2 min. **FUNZIONA end-to-end**. Nota: `gh api repos/.../hooks` ritorna `[]` con GitHub App source (comportamento normale — l'App riceve eventi via proprio endpoint interno, NON registra webhook classici). Test empirico = vedere deploy partire.
- [x] **Playbook Coolify auto-deploy** (commit `7272fa6`) — `docs/playbook-coolify-autodeploy.md` riutilizzabile per tutti i repo Gravya. 8 sezioni + Section 1.5 "⚠️ CRITICAL: Source type change recreates the app" aggiunta dopo l'incidente di oggi (data wipe su trdex). Documenta il pattern App vs Actions, race conditions, diagnostica, multi-repo rollout.
- [x] **Commit identity fix** — local git config era `GravyaDev <dev@gravya.it>` (mailbox inesistente), corretto a `Daniele <daniele@gravya.it>` via `-c user.email=...` inline per ogni commit. `.claude/memory.md` allineata a KB. Feedback memoria `feedback_commit_identity.md` salvata.
- [x] **Recovery 36 canali Telegram post-wipe** — lista recuperata via `scripts/telegram_list_channels.py` nel container (Telethon session era bind mount `/opt/trdex/session/`, sopravvissuta al DB wipe). CSV ri-inserita in Runtime Config. Discovered: parser auto-classifica signal vs news da una singola key `telegram_channels` — conferma da `api/app.py:201` + `dashboard/app.py:652`.

## Done — 2026-04-16

- [x] **Security: 3 CVE patched** (commit `dafa56c`) — langsmith 0.7.25→0.7.32 (GHSA-rr7j-v2q5-chgv), python-multipart 0.0.22→0.0.26 (CVE-2026-40347), pytest 9.0.2→9.0.3 (CVE-2025-71176). Transitives pinned in pyproject. pip-audit 3→0.
- [x] **Telegram evaluator bug fix: yfinance dep** (commit `632f084`) — scoperto che tutti i 15 segnali Forex aperti erano stuck con `exit_price=NULL` perché `yfinance` feed era registrato nel manager ma il modulo non era in pyproject. All feeds failing. Aggiunto `yfinance>=0.2`. **Pending Coolify rebuild** per attivarsi in prod.
- [x] **Trading results verification (2026-04-16)** — cross-check 26 trade chiusi via query DB + Binance klines. Ledger quadra al centesimo (+$38.21 realised). Math spot-check 4/6 OK, 2/6 sub-0.2% discrepancy (simulator slippage, non bug). Nessun phantom gain. Script `scripts/verify_today_trades.py`.
- [x] **Retro-simulation TP/trailing sweep (2026-04-16)** — replay dei 26 trade su candele Binance 1min reali, 9 combo TP×trail. Baseline SL 2%/TP 4%/trail 1.5% = +$0.54. **Best = SL 2%/TP 4%/trail 2.5% = +$19.21**. Insight: trailing troppo stretto, NON TP sbagliato. Sample size insufficiente per cambio subito. Script `scripts/sim_tp_trail_variants.py`.
- [x] **Task Board expansion** — 4 nuovi P0/P0-tech per domani: verify evaluator post-rebuild, TwelveDataFeed impl, AlphaVantage feed registration, Coolify GitHub App setup + playbook LLM.

## Done — 2026-04-15

- [x] **DB reset produzione** — TRUNCATE positions/balance/signal_outcomes/agent_runs/stop_loss_events + reseed $10k.
- [x] **Gate readiness 25→20 giorni** (commit `ac6217b`) — default in `config.py` + esposto via Runtime Config con fallback.
- [x] **Strategy tuning** (commit `5725a3d`) — RSI 40/60 zona neutrale → momentum direzionale (>50 BUY / <50 SELL) + overextension (>70 SELL / <30 BUY). SMA 5/13 → 9/21. SL 3%→2%, TP 5%→4%, trailing 2%→1.5%. Symbols 25 → 10 liquidi. Basato su consensus analysis Perplexity/Claude/Gemini (`docs/Risposte LLM Strategia/`).
- [x] **Manual open/close positions** (commit `a15bd84`) — endpoint API + UI dashboard. Gateway-routed con tutti i gate (fees/slippage/kill-switch/lot-size).
- [x] **gate_min_days in Runtime Config** (commit `a15bd84`) — editabile da dashboard senza redeploy.
- [x] **Handoff doc llm-agents** — `docs/handoff-main-to-llm-agents-2026-04-15.md`. 3 commit principali da mergiare forward.

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
