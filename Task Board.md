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

- [ ] **Active hours mode** — scheduler skippa cicli fuori fascia configurable
  - Infrastruttura RuntimeConfig già presente (migration 012), serve solo la logica scheduler

---

## 🔴 Blockers per live mode (da fare PRIMA di soldi veri)

- [ ] **Lot size compliance** — Simulator non rispetta lot/step size Binance. Live orders verrebbero rifiutati.
  - Fix: `exchange.load_markets()` al lifespan, cache min/step, truncare qty
  - **Effort**: ~2-3h

- [ ] **Open-side fee tracking** — Solo close fee sottratta. P&L gonfiato ~0.1%/trade.
  - Fix: colonna `fee_open`, migration, scrivere in `record_open_fill`
  - **Effort**: ~1h

- [ ] **Reject default DB creds in non-dev modes**
  - **Effort**: ~30 min

---

## 🔵 Phase 3 (post-osservazione, 7-14+ giorni dati)

- [ ] Iterazione strategia (variazioni SMA cross, RSI threshold, MACD divergence)
- [ ] Multi-timeframe confirmation (1h confermato da 4h)
- [ ] Multi-symbol portfolio rotation (ranking momentum, allocazione dinamica)
- [ ] ExitPolicy (Opzione 4): strategie diverse (mean reversion, breakout, scalping)

---

## ⚪ Tech debt / minor

- [ ] Pass feed/strategy registries into create_app() for /status endpoint
- [ ] Alembic migration runner (sostituisce script custom)
- [ ] Circuit breaker IngestionScheduler per Qdrant failures
- [ ] Define `PositionSide` enum (replace plain str in ORM)
- [ ] Forex weekend gap closure rule
- [ ] Persistent stop-loss event log (oggi in-memory)
- [ ] `fill_reconciliation` table per riconciliazione DB ↔ exchange (live mode)

---

## Done — 2026-04-10

- [x] Merge forward `origin/main` → `llm-agents` (Runtime Config + aggressive tuning, 0 conflitti)
- [x] Commit Step 1 RAG pipeline (indicators extraction)
- [x] **Historical Market Episode RAG pipeline COMPLETE** (Step 1-8): backfill, episodes, generate, context integration, scheduler wiring, market brief, 32 test

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
