# Task Board

## ⚠️ Branch `llm-agents` (worktree `trdex-llm/`)

Rifacimento Phase 2 con LLM veri dentro Scout/Analyst/Risk/Executor.
Design doc: `.claude/reports/llm-agents-design-2026-04-08.md`
Workflow: fix su main → merge forward nel branch. Mai il contrario.

---

## Production status (2026-04-17, merged 2026-04-18)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/` — **nuova app Coolify UUID `e5tqc26vgsnm6czy8wnqpxl2`** (riconnessa 2026-04-17 a GitHub App source, DB wiped — accettato).
Scheduler: 10 symbols, 5 min interval. Strategy: SMA 9/21, RSI direzionale >50/<50 + overextension >70/<30. SL 2%, TP 4%, trailing 1.5%. Gate readiness 20gg.
Tests: 359/359. Telegram monitor: 36 canali ri-inseriti manualmente (auto-classified signal/news), evaluator ogni ora. Kloudify v1.4.4.
**Auto-deploy Coolify FUNZIONA** end-to-end (GitHub App→push→rebuild→restart, confermato 2026-04-17 con commit `1fd4060`).
DB fresh — $10k seed da reconfigurare se serve.

## Next Session (inherited from main 2026-04-17)

- [x] **[P1] Hot-reload integration toggles** — done 2026-04-18 (merge forward #8, commit `f3fea47` / main `f590fd5`). `unregister()` su `PriceFeedManager`, `supports_symbol` predicate sui feed, scheduler hot-reload in `api/app.py` + `context/scheduler.py`. Bonus da main: `6ef4281` preparatorio (base feed + coingecko supports_symbol) + `e8f88c9` telegram ROI direction-aware.
- **[P3] Issue #1 CoinGecko `supports_symbol` filter** — residuo di https://github.com/GravyaDev/trdex/issues/1 dopo fix Binance (2026-04-17). Implementare `supports_symbol(symbol: str) -> bool` predicate su `CoinGeckoFeed` + filter nel `PriceFeedManager._rate_limited_call` per skippare feed che non supportano il simbolo. Effort ~30 min. Low priority (pure log hygiene).
- **[P1] Osservazione post-reset** — 5-7gg con nuova strategia. Target $20-30/giorno. Verificare win rate reale su ≥20 trade chiusi. (Nota dalla sim 2026-04-16: la retro-simulation sul parametro sweep suggerisce che trailing 2.5% > trailing 1.5% — +$19.21 vs +$0.54 sui 26 trade, ma sample troppo piccolo per cambiare adesso.)
- **[P2] Auto-resolve Telegram channel names on CSV save** — quando un utente salva `telegram_channels` in Runtime Config, un endpoint `/v1/telegram/resolve-channels` chiama `client.get_entity(chat_id)` per ogni token, popola una mappa `telegram_channel_titles` (JSON runtime_config key) e il widget dashboard mostra "Nome · chat_id" invece di solo chat_id. Eager al save + lazy fallback ai messaggi in arrivo. Effort ~30-45 min.
- **[P3] 58 canali mancanti** — cercare da `channels_failed_lookup.md` e aggiungere dal dashboard
- **[P3] Cleanup orphan volumes** — dismettere `w35035ypb7dl7t94flyn9c5f_{pgdata,redis,qdrant,telegram-session}` (~70MB pgdata + others) dal VPS via `docker volume rm` quando sicuro del nuovo deploy

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

- [ ] **Deploy trdex-llm on Coolify** — runbook `docs/deploy-trdex-llm-runbook.md` (auto-deploy via GitHub App, no manual webhook). Pre-flight verified 2026-04-18: DNS OK, branch `llm-agents` pushed, GitHub App already installed org-wide (2026-04-17), OAuth App for trdex-llm created, all 3 LLM provider keys available.
  - [ ] Step 1 (UI): create Coolify application — Private Repo (GitHub App source), branch `llm-agents`, Docker Compose, Auto Deploy ON
  - [ ] Step 2 (UI): env vars — 5 groups: secrets (POSTGRES_PASSWORD / TRDEX_API_KEY / OAUTH2_PROXY_COOKIE_SECRET / TRDEX_CONFIG_ENCRYPTION_KEY) + OAuth + 3 LLM providers + operational (TRDEX_MODE=simulation, scheduler off) + defaults
  - [ ] Step 3 (VPS): `mkdir -p /opt/trdex-llm/session && chown 1000:1000`
  - [ ] Step 4 (UI + CLI): first deploy + `gh api repos/GravyaDev/trdex/hooks` verify + health checks on `/v1/health` and `/dashboard/` + empty-commit push smoke test
  - [ ] Step 5 (dashboard): enable LLM per agent + (optional) RAG Tier 4b populate via `backfill_ohlcv` + `generate_episodes` scripts inside container
  - [ ] Step 6: 48h cost watch, compare vs trdex prod rule-engine signals

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

### 🟤 CI/CD & automation (from main 2026-04-16 — Coolify auto-deploy ora FUNZIONA, vedi Done 2026-04-17)

- [x] **Auto-redeploy su push via Coolify GitHub App** — done 2026-04-17 (vedi playbook `docs/playbook-coolify-autodeploy.md`). GitHub App installata, trdex riconnessa, auto-deploy verificato end-to-end.
- [x] **Guida LLM: setup auto-deploy Coolify** — done 2026-04-17 (commit `7272fa6`), playbook in `docs/playbook-coolify-autodeploy.md`.

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

## Done — 2026-04-18

- [x] **Kloudify upgrade v1.3.2 → v1.4.4** (commit `c720f0e`) — 11 `.kloudify-new` conflict files reviewed and adopted. Universal-rules +2 entries (GitHub Apps webhooks false-negative, BetterAuth nanoid IDs). New `wrap-up-digest.sh` hook for Step 7b deterministic digest. `settings.json` adopted despite cozempic hook loss (reinstalled from scratch after sync).
- [x] **Merge forward #7** (commit `7850117`) — 10 commits from main: 2 security patches (langsmith/pytest/python-multipart + mako CVE), TwelveDataFeed, per-component enable toggles, yfinance dep, simulated P&L telegram dashboard. 3 conflicts resolved (uv.lock→theirs, playbook→theirs, Task Board→manual).
- [x] **Runbook deploy trdex-llm** (commit `98e69e3`) — `docs/deploy-trdex-llm-runbook.md`: 6-step operational checklist for fresh Coolify app creation via GitHub App source. Section 1.5 of playbook (data-wipe risk) explicitly NOT applicable — new app, not Source-type conversion.
- [x] **Merge forward #8** (commit `f3fea47`) — 3 commits from main: `6ef4281` supports_symbol predicate + feed unregister (infra), `f590fd5` **P1 hot-reload integration toggles** (+205 lines in api/app.py, +20 in context/scheduler.py), `e8f88c9` telegram win/loss direction-aware ROI. Zero conflicts. 400/400 tests. 0 vulns.
- [x] **Cozempic reinstalled globally** — via uv tool (standalone, outside project venv). 1.8.0 working.

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
