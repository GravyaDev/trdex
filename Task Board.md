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

- [x] **[HIGH] Harden verify_api_key** — FIXED 2026-04-11 (commit `d4fff2b`).
- [ ] **[MEDIUM] credentials_crypto fail-closed outside SIMULATION** — `init_cipher()` oggi fa passthrough silenzioso a plaintext se `TRDEX_CONFIG_ENCRYPTION_KEY` unset/invalid. In `live`/`paper` deve raise `RuntimeError` come il pattern `verify_api_key`. `services/credentials_crypto.py:94-136`. **Effort**: ~20 min
- [ ] **[MEDIUM] Rate limiter X-Forwarded-For behind proxy** — SlowAPI usa `get_remote_address()` che dietro Coolify/Traefik ritorna il peer del proxy → tutti i client condividono un bucket (effectively 60/min globali). Fix: `key_func=lambda req: req.headers.get("x-forwarded-for", ...).split(",")[0].strip()`. `app.py:523`. **Effort**: ~5 min, HIGH impact
- [ ] **[MEDIUM] Telegram evaluator NaN/inf sanitization** — `_parse_note()` accetta qualsiasi float da Telegram user content. NaN/inf fa si che SL/TP non triggerino mai. Observe-only oggi, critico quando passa a live. Fix: `math.isnan`/`isinf` + sanity bounds `0 < t < 1e9`. `telegram/evaluator.py:127-138`. **Effort**: ~15 min
- [ ] **[MEDIUM] Sanitize memory snapshot text prima dell'iniezione LLM** — `memory_text` in `prompt_builder.py:111-113` e `state.memory_snapshots[agent]` vanno passati per `sanitize_rag_content()`. **Effort**: ~20 min
- [ ] **[LOW] CLI input validation** su `backfill_ohlcv.py` e `generate_episodes.py`. **Effort**: ~15 min
- [ ] **[LOW] Mode gate su `/v1/debug/*`** — aggiungere check `settings.mode == SIMULATION` così anche una leaked key in production non può dumpare balance ledger / entity graph. **Effort**: ~10 min
- [ ] **[LOW] Lifespan boot-guard regression test** — nessun test oggi asserisce il `RuntimeError` nel `_lifespan` quando mode != SIMULATION e api_key vuoto. Aggiungere `test_lifespan_refuses_unset_key_outside_simulation`. **Effort**: ~15 min

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
