# Task Board

## Today — 2026-04-08 (chiusa ~15:30 UTC, deploy WIP)

Tutta la giornata su refactor Intent enum + deploy trdex su VPS. Deploy bloccato da bug 4+5 scoperti nel secondo deploy attempt. Sessione chiusa per context saturation. **Dettagli completi in `.claude/reports/session-handoff-2026-04-08-deploy-wip.md`.**

Lavoro completato:
- Refactor Intent enum: 24 decisioni del brainstorming applicate, 308/308 test verde (+28 test nuovi)
- VPS hardening completo: swap 4GB, fail2ban, UFW informative, sshd drop-in
- User `kloud` creato su VPS con sudoers scoped + SSH key-only
- `/opt/gravya/services/coolify-trdex/` files + first commit come Kloud (`dffe2fb`)
- Docker compose Coolify-ready + override dev-only file
- 13 commit pushati su `origin/main`
- Coolify Project `trdex` configurato con Application da GitHub + env vars + dominio
- Deploy attempt 1 FAILED: qdrant healthcheck curl mancante → fix `5dc584a`
- Deploy attempt 2 FAILED: app crash su DB vuoto (bugs 4+5 scoperti)

## Next Session — PRIORITY 1 (deploy unblock)

- [ ] **Fix bug 4**: Dockerfile aggiungere `COPY migrations/ migrations/` dopo linea 24
- [ ] **Fix bug 5**: FastAPI lifespan in `src/trdex/api/app.py` chiamare `apply_migrations` come primo step di startup (Option C del handoff)
- [ ] **Fix bug 6** (preventivo): init Qdrant collection `trdex_context` nel lifespan dopo migrations
- [ ] Commit + push 3 fix insieme
- [ ] Coolify Redeploy (3° attempt)
- [ ] Verify: 4 container healthy, app logs `[lifespan] migrations applied`, nessun restart loop
- [ ] Post-deploy: smoke_level4 dal container, inspect_runs --hours 1
- [ ] Enable scheduler: Coolify env `TRDEX_AGENT_SCHEDULER_ENABLED=true` + Restart
- [ ] Monitor primi tick via `inspect_runs --hours 1`
- [ ] Write `/opt/gravya/backup/trdex/backup.sh` + add to `backup-all.sh` + commit come Kloud

**Stima**: 45-90 min di focus fresco. **NON iniziare a fine sessione di altre attività.**

## This Week (post-deploy success)

- [ ] Phase 2 osservazione vera: 3-5 giorni di scheduler live in simulation sul VPS
- [ ] Daily check con `inspect_runs --hours 24` e `--hours 72` (via SSH come kloud)
- [ ] Sentinella: se zero trade in 48h sul mercato corrente, capire perché (mercato lateral? bug del traduttore?)
- [ ] Sentinella: monitorare `agent_runs` count cresce ~288 al giorno per simbolo

## Backlog (consolidato)
- [ ] **Creare agente Claude Code "gravya-ops" dedicato alla gestione VPS** — task dedicato in sessione separata
  - **Trigger**: attivare quando trdex su VPS è stabile (2-5 giorni dopo l'inizio di Phase 2 osservazione)
  - **Home**: `C:\Users\Daniele\Antigravity\gravya-platform\` (repo esistente) — NON dentro trdex
  - **Pattern**: Pattern A (agente dedicato, scope infra-only, hard rule di non toccare codice applicativo dei servizi)
  - **Scope**: orchestrazione di TUTTI i servizi Coolify su `srv.gravya.it` (oggi 8+ servizi incluso trdex), backup, monitoring, patch Ubuntu, cleanup, incident response
  - **Autonomia iniziale**: read-only, escalation a write-sicuro dopo 2 settimane di uso affidabile
  - **MCP**: Hostinger API (già configurato a livello sistema Windows tramite variabile d'ambiente)
  - **SSH**: chiave dedicata separata da `trdex_deploy` (es. `gravya_ops_deploy`), non riuso cross-agente
  - **Hard rule corollaria**: "gravya-ops NON modifica il codice applicativo dei servizi. Tocca solo infra/compose/secrets/backup/monitoring. Se serve una modifica al codice di un servizio, output è `HANDOFF: <servizio>` e stop"
  - **Skill da progettare**: `audit-vps`, `run-backup-all`, `audit-coolify`, `diagnose-container`, `monitor-disk-ram`, `patch-ubuntu`, `cleanup-logs`
  - **Audit trail**: ogni azione loggata in `/opt/gravya/ops-audit/YYYY-MM-DD.log` sul VPS
  - **First use case**: audit del deploy trdex di oggi + verifica che tutto sia a posto (scheduler, backup funzionante, coerenza compose vs /opt/gravya/services/coolify-trdex/)
  - **Modalità di esecuzione del task**:
    - Daniele NON vuole costruire l'agente dentro questa sessione
    - La sessione CORRENTE (trdex) produrrà a fine deploy un **handoff plan completo e autonomo** in un file dedicato (es. `.claude/reports/handoff-gravya-ops-<data>.md`)
    - Il plan deve includere: snapshot dello stato reale del VPS al momento del deploy, elenco skill da creare con template, CLAUDE.md draft, profilo memoria iniziale, convenzioni, SOP
    - Un'altra istanza Claude Code (non questa) aprirà una sessione dedicata in `gravya-platform/` e userà quel file come input per costruire l'agente
    - Zero interazione tra le due sessioni, zero contaminazione
- [ ] **Setup monitoring esterno del deploy VPS** — dopo che gravya-ops è attivo (diventa un caso d'uso di gravya-ops)
  - Opzioni: uptime kuma self-hosted su VPS stesso, healthcheck.io, o alert Telegram via app stesso
  - Deve coprire: `/v1/health` uptime, disco VPS, RAM, kill-switch activation, scheduler tick drift
- [ ] **Valutare Perplexity Sonar come news source principale** (sostituisce o affianca CryptoCompare/StockData)
  - **Motivazione**: Perplexity Sonar è un search engine LLM-native che restituisce sintesi narrative contestualizzate invece di liste cronologiche di titoli. Il vector store Qdrant + Scout agent funzionano meglio con testo denso in signal rispetto a titoli spezzettati. È un win architetturale, non solo di source.
  - **Trigger**: dopo Phase 2 observation baseline (almeno 7 giorni con scheduler attivo + zero news sources o solo CryptoCompare). Quando vuoi passare da "SMA cross puro" a "SMA + context AI" nel setup agent.
  - **Effort**: ~45-90 min di coding per scrivere `PerplexityNewsSource(NewsSource)` che traduce output narrativo Perplexity → ContextDocument list. Registrazione nel lifespan IngestionScheduler. Test end-to-end.
  - **Costo**: sonar base ~$20/mese con tick ogni 5 min (288 query/giorno, ~500+1000 token/query). Accettabile per personal use. Sonar-pro ~$65/mese è overkill per questo use case.
  - **Scope incluso**:
    1. Signup Perplexity API key → add env var `TRDEX_PERPLEXITY_API_KEY`
    2. New module `src/trdex/context/news_sources/perplexity.py` che implementa `NewsSource` interface (method `fetch(symbols)` → list[ContextDocument])
    3. Query template: "What are the most significant news for {symbol} in the last {interval} minutes? Focus on price-impacting events, regulation, macro trends." — iterare sul prompt per quality
    4. Mapping paragrafo principale + citations → 1+N ContextDocument con URL, text, published_at=now
    5. Sentiment: lasciare None in prima iterazione (è complicato senza un altro LLM call)
    6. Registrazione nel lifespan: `if settings.perplexity_api_key: _scheduler.register(PerplexityNewsSource(...))`
    7. Test unit del parser + integration contro API reale (marked `@pytest.mark.integration`)
  - **Scope escluso**:
    - Multi-LLM evaluation (sonar vs sonar-pro vs altri provider) — si decide in session dedicata
    - Rimozione di CryptoCompare/StockData — lasciale come fallback
    - Sentiment analysis del paragrafo — future work
  - **Decisione di design da prendere**: usare Perplexity come **sostituzione** di CryptoCompare/StockData (semplice, meno duplicazione in Qdrant) o come **aggiunta** (difesa in profondità, più source diversità)? Raccomandazione: sostituzione o fallback-only.
- [ ] **Upgrade auth dashboard da basic auth a soluzione migliore** — dopo che Phase 2 gira stabile
  - **Motivazione**: basic auth Traefik è funzionale ma UX/ergonomia povera (popup browser, no MFA, no session revoke, no audit log accessi, no lockout brute-force). Accettato in Phase 2 come trade-off per velocità di deploy, da sostituire appena il dashboard è stabile in produzione.
  - **Opzioni in ordine di preferenza**:
    1. **Cloudflare Tunnel + Cloudflare Access** (zero-trust SSO via email magic-link/GitHub/Google, MFA nativo, audit log, gratis per <50 utenti). Richiede migrare zona DNS a Cloudflare, installare `cloudflared` sul VPS, configurare policy.
    2. **Tailscale VPN**: rimuovi exposure pubblica, dashboard accessibile solo su IP privato Tailscale. Zero password, zero attack surface esterna. Richiede client Tailscale su ogni device.
    3. **oauth2-proxy + GitHub OAuth**: middleware Traefik che richiede login GitHub prima di proxy. Delega MFA a GitHub. Aggiunge 1 container al compose.
  - **Scope**: rimuovere `traefik.http.middlewares.trdex-dashboard-auth.basicauth.*` labels dal compose, sostituire con la nuova catena di middleware, rimuovere `TRDEX_DASHBOARD_BASICAUTH` env var, aggiornare doc deploy.
  - **Trigger**: dopo almeno 1 settimana di Phase 2 observation stabile, prima di eventuali passaggi su dati reali / live mode.
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
