# Task Board

## ⚠️ Branch `llm-agents` (worktree `trdex-llm/`)

Rifacimento Phase 2 con LLM veri dentro Scout/Analyst/Risk/Executor.
Design doc: `.claude/reports/llm-agents-design-2026-04-08.md`
Workflow: fix su main → merge forward nel branch. Mai il contrario.

---

## Production status (2026-04-10)

**trdex LIVE** su `https://trdex.gravya.it` + dashboard `/dashboard/`
Scheduler: 25 symbols (aggressive tuning mergiato oggi), 5 min interval
Runtime Config: DB-backed, editable da dashboard (migration 012)
Auth: GitHub OAuth via oauth2-proxy

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

---

## 🔴 Blockers per live mode (tutti risolti su main, mergiati in llm-agents)

✅ Tutti i blocker originali sono stati risolti su main e mergiati in llm-agents:
- Lot size compliance (`market/specs.py` + `truncate_qty()`)
- Open-side fee tracking (migration 010 + `fee_open` column)
- Reject default DB creds (guard in `app.py` lifespan)
- Live executor test (Ed25519 testnet passed)

---

## 🛡️ Security corrective tasks (da security scan 2026-04-10)

- [ ] **[HIGH] Harden verify_api_key** — refuse startup se `settings.mode != SIMULATION` e `api_key` vuoto. Oggi l'API cade in dev-mode silenzioso con TUTTI gli endpoint esposti (incluso `/v1/debug/*`). Mirror del pattern default-DB-creds guard in `app.py:137-143`. **Effort**: ~30 min
- [ ] **[MEDIUM] Sanitize memory snapshot text prima dell'iniezione LLM** — `memory_text` in `prompt_builder.py:111-113` e `state.memory_snapshots[agent]` vanno passati per `sanitize_rag_content()` per defense-in-depth. Oggi tutto il contenuto è interno, ma il pattern è un vettore di prompt-injection diretto nell'Analyst. **Effort**: ~20 min
- [ ] **[LOW] CLI input validation** su `backfill_ohlcv.py` e `generate_episodes.py` — regex su `symbol` (`^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$`), cap `--days` a 3650, validate `window > 0` e `stride > 0`. **Effort**: ~15 min

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

Aperti:
- [ ] Alembic migration runner (sostituisce script custom)
- [ ] Persistent stop-loss event log (oggi in-memory, perso al restart)
- [ ] `fill_reconciliation` table per riconciliazione DB ↔ exchange (live mode)
- [ ] Tier 3+4 features (kline WS stream, CoinGecko screener, hyperopt, Redis cache, Ollama LLM)

---

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
