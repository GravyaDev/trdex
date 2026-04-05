# Deep Audit — trdex — 2026-04-05

## Executive Summary

| Analyst | PASS | WARN | FAIL |
|---|---|---|---|
| Schema | 5 | 3 | 2 |
| Backend | 6 | 5 | 1 |
| Infrastructure | 7 | 3 | 1 |
| Security | 5 | 4 | 4 |
| Architecture | 10 | 10 | 10 |
| Frontend | 5 | 3 | 1 |
| **TOTAL** | **38** | **28** | **19** |

**Verdict**: 19 FAILs — significantly more than previous audit (4 FAILs). The platform grew substantially (Phase 4+5: feeds, agents, risk, dashboard) and brought real complexity. Most FAILs are actionable before going live. Critical blockers: unauthenticated kill-switch endpoints, session leak in portfolio routes, missing env vars in .env.example.

---

## Findings per Analyst

## Schema Analyst

### PASS
- **Migration completeness**: All 3 migrations (001–003) have corresponding ORM models (OHLCVRecord, PositionRecord, AgentRunRecord). No orphaned files.
- **Idempotency**: 001 uses UNIQUE(symbol, timeframe, timestamp) + ON CONFLICT DO NOTHING in ohlcv_repo.py. Seed script documents idempotency.
- **Indexes on critical columns**: ohlcv: (symbol, timeframe, timestamp); positions: (symbol, status), (source, status); agent_runs: symbol, ran_at DESC.
- **ORM consistency**: All 3 ORM models match their migrations precisely in column names, types, and constraints.
- **Nullable semantics**: Repositories correctly handle nullable columns (closed_at, filled_price, error).

### WARN
- **Dual DeclarativeBase**: `agent_run_models.py:13` defines its own `_Base(DeclarativeBase)` instead of importing from `db.py`. Creates two separate metadata registries — may cause Alembic introspection issues. → Import `Base` from `db.py`.
- **Missing explicit DateTime type annotations**: `models.py:29` (timestamp), `portfolio_models.py:32-33` (opened_at, closed_at) omit `DateTime` type — SQLAlchemy infers TIMESTAMP not TIMESTAMPTZ. Mismatch with migration. → Add `DateTime(timezone=True)` or `DateTime(timezone=False)` explicitly.
- **Timezone handling undocumented**: ohlcv_repo and portfolio_repo both strip tzinfo before insert (asyncpg naive UTC); pattern is correct but implicit. → Add docstrings documenting UTC convention.

### FAIL
- **No FK constraints**: No FK links between positions/agent_runs and a symbols master table. Orphaned records with misspelled symbols accumulate silently. → Add `symbols` reference table with FK constraints, OR document that symbol is a free-text label in each model.
- **No ORM defaults for required timestamps**: `portfolio_models.py:32` (opened_at) and `agent_run_models.py:30` (ran_at) are `nullable=False` without `default=` in mapped_column. Migration has `DEFAULT NOW()` but ORM doesn't reference it. A direct instantiation without setting these fields will fail silently at insert. → Add `default=lambda: datetime.now(timezone.utc)` to mapped_column declarations.

---

## Backend Analyst

### PASS
- **No broken imports**: All imports verified valid across app.py, routes, agents, config. 15+ modules correctly referenced.
- **Configuration from environment**: `config.py:22` uses pydantic_settings with `env_prefix="TRDEX_"`. All API keys loaded from settings.
- **Error handling in background tasks**: Telegram task, agent scheduler, stop-loss monitor — all catch `asyncio.CancelledError` separately from `Exception` with logging.
- **Background task lifecycle**: All asyncio tasks properly cancelled in lifespan with `asyncio.gather(..., return_exceptions=True)`.
- **Kill switch integration**: `risk_node` Gate 0 checks kill switch before any AI logic. Stop-loss monitor can activate it.
- **Rule-based safety gates**: Hard gates in risk_node: kill switch → HOLD filter → min confidence → live mode block → position sizing cap.

### WARN
- **Deprecated `datetime.utcnow()`**: `agents/state.py:16` uses `datetime.utcnow` (deprecated in Python 3.12+). → Replace with `datetime.now(tz=timezone.utc)`.
- **Missing error handling in portfolio routes**: All 4 portfolio endpoints call `await _get_service()` and service methods without try/except. → Add structured error responses.
- **Hardcoded DB/Redis defaults**: `config.py:30,36` have hardcoded localhost defaults. In production, misconfiguration is masked. → Change defaults to `""` and validate explicitly in non-dev modes.
- **Global mutable `_tracker`**: `app.py:38` — `SignalTracker()` module-level singleton with no lock. Concurrent Telegram signals could race. → Verify thread safety or add asyncio.Lock.
- **Private attribute access from routes**: `context.py:34,45,57` accesses `scheduler._sources`, `scheduler._symbols` directly. → Use public accessors.

### FAIL
- **Session resource leak in portfolio routes**: `api/routes/portfolio.py:32` — `_get_service()` creates AsyncSession without context manager. Session never closed. Each request leaks one DB connection; pool (max 15) exhausts under moderate traffic. → **Critical**: Refactor to `async with _session_factory() as session:` pattern, matching `agent.py:58`.

---

## Infrastructure Analyst

### PASS
- **Port consistency**: Dockerfile EXPOSE 8000 matches docker-compose 8000:8000. Config default port 8000 consistent.
- **Healthchecks for db/redis/qdrant**: TimescaleDB (pg_isready), Redis (redis-cli ping), Qdrant (curl healthz) all configured with sensible intervals.
- **No Windows paths in Docker**: All Docker paths use Linux conventions.
- **CORS safe default**: CORS allows origins only from `settings.cors_origins`; defaults to empty list (no origins allowed).
- **Volume persistence**: trdex_pgdata, trdex_redis, trdex_qdrant, trdex_telegram.session all correctly mounted.
- **CI pipeline**: `.github/workflows/ci.yaml` runs ruff, mypy, pytest on push/PR.
- **API key framework**: `verify_api_key` respects TRDEX_API_KEY; dev mode when unset.

### WARN
- **DB URL inconsistency**: `.env.example` shows `localhost:5432`; Docker Compose internal DNS should be `db:5432`. → Update `.env.example` to use `db:5432` for containerized deployments; document localhost-only for bare-metal dev.
- **No healthcheck for app service**: db/redis/qdrant have healthchecks; the `app` service does not. → Add `CMD curl -f http://localhost:8000/v1/health` healthcheck.
- **Migration strategy undefined**: migrations/ has raw SQL files; Alembic is in deps but unconfigured. No automated apply on startup. → Either configure `alembic upgrade head` in Dockerfile CMD, or add migration runner in lifespan.

### FAIL
- **18 env vars missing from .env.example**: Phase 4+5 added many new settings never documented. Missing: `TRDEX_AGENT_SCHEDULER_ENABLED`, `TRDEX_AGENT_SCHEDULER_INTERVAL`, `TRDEX_AGENT_SCHEDULER_SYMBOLS`, `TRDEX_ALPHAVANTAGE_API_KEY`, `TRDEX_CRYPTOCOMPARE_API_KEY`, `TRDEX_FREECRYPTOAPI_KEY`, `TRDEX_GATE_MIN_DAYS`, `TRDEX_GATE_MIN_SHARPE`, `TRDEX_GATE_MAX_DRAWDOWN`, `TRDEX_GATE_MIN_WIN_RATE`, `TRDEX_INGESTION_INTERVAL`, `TRDEX_INGESTION_SYMBOLS`, `TRDEX_MAX_POSITION_PCT`, `TRDEX_SL_CHECK_INTERVAL`, `TRDEX_SL_POSITION_PCT`, `TRDEX_SL_TAKE_PROFIT_PCT`, `TRDEX_SL_DAILY_DRAWDOWN_PCT`, `TRDEX_STOCKDATA_API_KEY`. → Add all to `.env.example` with defaults and descriptions.

---

## Security Analyst

### PASS
- **Auth on portfolio endpoints**: `verify_api_key` applied to all 4 portfolio routes.
- **Constant-time key comparison**: `secrets.compare_digest()` prevents timing attacks (`app.py:234`).
- **Parameterized SQL**: SQLAlchemy ORM throughout; `portfolio_repo.py` raw text() uses bound parameters.
- **API keys from environment only**: All keys via `settings` object, never hardcoded.
- **Rate limiter implemented**: `market/rate_limiter.py` exists with adaptive throttling and circuit breaker.

### WARN
- **Rate limiter not wired into routes**: RateLimiter implemented but never applied to HTTP endpoints. → Add as middleware or per-endpoint dependency.
- **Input validation gaps**: `agent_history(limit: int)` no bounds check; `add_symbol(symbol: str)` no format validation; `pnl_history(days: int)` no bounds check. → Use `Field(gt=0, le=1000)` constraints.
- **Telegram credentials sensitivity**: `telegram_api_id`, `telegram_api_hash`, `telegram_phone` in env — if `.env` leaks, account compromise. → Consider separate secret management for production.
- **Generic error messages leak architecture hints**: "Agent runner not initialised." etc. → Use opaque errors in production; log details server-side.

### FAIL
- **Kill-switch endpoints completely unauthenticated**: `POST /v1/risk/kill-switch/activate` and `/reset` (`risk.py:43-56`) have zero auth. Any network-accessible caller can halt or resume all trading. → **Critical**: Add `_key: str = Depends(verify_api_key)` to both immediately.
- **Agent execution endpoint unauthenticated**: `POST /v1/agent/run` (`agent.py:46`) — any caller can trigger live agent cycles and influence trading. → Add `verify_api_key`.
- **Context management endpoints unauthenticated**: `POST /v1/context/symbols`, `DELETE /v1/context/symbols/{symbol}` — unauthenticated watchlist modification, DoS vector. → Add `verify_api_key` to all state-changing context endpoints.
- **Agent history endpoint unauthenticated**: `GET /v1/agent/history` exposes trade decisions and signal history without auth. → Add `verify_api_key`.

---

## Architecture Analyst

### PASS
- **Background task failure isolation**: Telegram, news scheduler, agent scheduler — each task wraps its loop in try/except; failures are logged without cascading.
- **Qdrant degradation — Scout graceful fallback**: `agents/scout.py:44` catches all exceptions, returns neutral SentimentContext. Agent cycles continue with empty context.
- **Execution gateway abstraction**: Clean ABC in `execution/gateway.py`; `simulator.py` implements it correctly.
- **Agent state per-run isolation**: Each `run_agent_cycle()` creates a new AgentState instance. No shared state across concurrent runs.
- **LangGraph lazy init safety**: `_get_compiled()` in `graph.py:45-53` creates compiled graph once. Thread-safe.
- **No circular imports**: Clean import chains throughout. No circular dependency paths detected.
- **Database session safety**: `db.py` creates async_sessionmaker once; each request gets a fresh scoped session.
- **Ingestion scheduler per-source isolation**: Failures in one news source don't halt others; each fetch wrapped individually.
- **Kill switch cross-cutting**: `risk_node` Gate 0 + `_agent_scheduler_loop` both check kill switch before acting.
- **LangGraph state deserialization**: `_dict_to_state` in `graph.py:56-76` filters by field names; functional though fragile.

### WARN
- **Route module-level globals set late**: `_session_factory`, `_feed_manager`, `_scheduler`, `_monitor` populated in lifespan; routes guard with if-None checks but no lock. Fast startup race possible.
- **KillSwitch no async lock**: `risk/stop_loss.py:47-90` — mutable state (_active, _reason) mutated without asyncio.Lock. Concurrent agent cycles could race on activate/check. → Add `asyncio.Lock`.
- **TelegramMonitor event handler accumulation**: If `stream()` called multiple times, event handlers accumulate without deregistration. → Document single-stream constraint or add cleanup.
- **SPOF — Jina embeddings**: Single embedding provider. Ingest fails when Jina is down; scout degrades gracefully. → Implement local fallback (sentence-transformers).
- **SPOF — Single Qdrant instance**: No retry or health check around `QdrantClient`. → Add circuit breaker.
- **SPOF — DB connection pool hardcoded**: Pool size 5/max_overflow 10 — may exhaust under concurrent agent+portfolio+monitor load. → Make configurable.
- **Portfolio session leak (architecture angle)**: `portfolio.py _get_service()` — sessions not closed (see Backend). Architecture risk: exhaustion under load.
- **_peak_equity initialized as None**: `risk/stop_loss.py:127` — max drawdown never triggers if monitor crashes on first check. → Initialize from portfolio opening equity in `start()`.
- **LangGraph state coercion fragile**: `_dict_to_state` silently drops unknown keys on AgentState changes. → Add validation/logging on key mismatches.
- **No request-scoped portfolio session cleanup**: Portfolio service holds session reference — scope violation risk if used across tasks.

### FAIL
- **Execution gateway is stub — never wired**: `agents/executor.py` always returns simulated results; live mode hard-blocked. Gateway exists but not injected into executor. → Wire ExecutionGateway; add integration tests for order path.
- **Agent state in-place mutation unsafe on crash**: Nodes mutate state fields directly. Mid-node crash leaves partial state. → Nodes should return new state dict; add pre-node snapshots.
- **Routes have no startup validation**: `create_app()` includes routers before lifespan populates globals. Race condition on startup. → Add startup order validation; test endpoints before lifespan completes.
- **StopLossMonitor session not scoped per check**: Session factory stored as instance variable; `check_now()` may reuse or share sessions across concurrent checks. → Use fresh session per check.
- **TelegramMonitor `stream()` uses blocking `queue.pop()` loop**: 0.5s sleep polling instead of `asyncio.Queue.get()`. Blocks coroutine; exceptions in event handler swallowed by Telethon. → Replace with async queue; add handler exception logging.
- **IngestionScheduler no circuit breaker for Qdrant**: Failed ingest docs silently dropped, no backoff, no dead-letter queue. → Add circuit breaker after 3 consecutive failures.
- **Agent persistence doesn't validate position FK**: `runner.py:_persist()` records agent run without checking if referenced positions exist. Orphaned records on external position close. → Wrap in transaction with FK check.
- **Kill switch activation doesn't interrupt in-flight agents**: Running agent cycles complete even after kill switch activates. Order may execute just before Gate 0 check. → Add abort mechanism to AgentRunner.
- **SignalTracker mutable unscoped state**: `app.py:38` — in-memory list without lock or DB persistence. Reset on restart. → Persist to DB; add asyncio.Lock.
- **No per-request portfolio session cleanup**: Sessions created in `_get_service()` without context manager. → Full fix required (see Backend FAIL).

---

## Frontend Analyst

### PASS
- **Base URL used for all GET calls**: `get()` wrapper at `app.py:43-44` uses `base_url` from sidebar for all GET requests.
- **Error states handled on data sections**: All major sections have `st.info()` or `st.error()` fallbacks.
- **API key masked**: `type="password"` on sidebar input. Not logged or exposed.
- **No business logic in dashboard**: Pure presentation + API calls throughout.
- **All 16 backend endpoints exist**: Every URL called from the dashboard has a matching route in FastAPI. ✅

### WARN
- **Cache TTL (30s) > default auto-refresh (15s)**: Stale data served for up to 30s while refresh fires every 15s. → Align TTL with minimum refresh interval (5s) or set default refresh to 30s.
- **Agent history section lacks error state**: `get(f"/v1/agent/history?limit=20")` at line 178 — if API returns None (error), `st.info("No agent runs yet.")` shown, conflating API failure with empty state.
- **`time.sleep()` blocks Streamlit thread**: Lines 288-291 — acceptable for prototype but causes UI freeze. → Consider `st.experimental_rerun` with session state timer for production.

### FAIL
- **POST calls bypass `base_url` wrapper**: Lines 159, 207, 230, 241, 271 — all POST requests use `f"{base_url}/v1/..."` directly via `httpx.post()` without a shared `post()` helper. If sidebar URL changes after page load, POST calls still use the captured closure. → Create a `post(path, **kwargs)` wrapper mirroring `get()` and refactor all POST calls through it.

---

## Prioritized Fixes

### P0 — Critical (correctness/security blockers)

1. **[Security] Add `verify_api_key` to kill-switch endpoints** — `risk.py:43-56` — unauthenticated kill-switch is a trading halt vulnerability
2. **[Security] Add `verify_api_key` to `/v1/agent/run`, `/v1/agent/history`** — unauthenticated agent execution
3. **[Security] Add `verify_api_key` to all `/v1/context/*` state-changing endpoints**
4. **[Backend] Fix session leak in portfolio routes** — `portfolio.py:32` — production connection pool exhaustion within hours
5. **[Infrastructure] Add 18 missing env vars to `.env.example`** — operators cannot configure new Phase 4+5 features

### P1 — Warning (reliability/correctness)

6. **[Architecture] Add `asyncio.Lock` to `KillSwitch`** — concurrent activate/reset race condition
7. **[Architecture] Replace `stream()` queue polling with `asyncio.Queue.get()`** in TelegramMonitor
8. **[Architecture] Add circuit breaker to IngestionScheduler** for Qdrant failures
9. **[Schema] Add ORM `default=` for `opened_at` / `ran_at` timestamps** — silent insert failure risk
10. **[Schema] Unify DeclarativeBase** — import from `db.py` in `agent_run_models.py`
11. **[Backend] Replace `datetime.utcnow()`** with `datetime.now(tz=timezone.utc)` in `state.py`
12. **[Infrastructure] Add healthcheck to app service** in docker-compose
13. **[Infrastructure] Fix DB URL in `.env.example`** — `db:5432` for Docker, document localhost for bare-metal
14. **[Frontend] Create `post()` wrapper in dashboard** — bypass base_url bug on POST calls
15. **[Architecture] Initialize `_peak_equity` from portfolio equity on StopLossMonitor.start()**

### P2 — Improvements (not urgent)

16. **[Architecture] Wire ExecutionGateway into executor_node** — live trading path
17. **[Schema] Add FK constraints or document symbol as free-text** in models
18. **[Architecture] Add startup validation** for route module globals
19. **[Architecture] Persist SignalTracker** to DB; add asyncio.Lock
20. **[Backend] Add input bounds validation** (`limit`, `days`, `symbol` params)
21. **[Infrastructure] Configure Alembic** or add migration runner to lifespan
22. **[Frontend] Align cache TTL** with auto-refresh interval

---

## Comparison with Previous Audit (2026-04-04)

| Metric | 2026-04-04 | 2026-04-05 | Delta |
|--------|-----------|-----------|-------|
| PASS | 34 | 38 | +4 |
| WARN | 19 | 28 | +9 |
| FAIL | 4 | 19 | +15 |

**Regressions (new FAILs since last audit):**
- Auth missing on 8+ new endpoints (Phase 5 routes added without auth)
- Session leak introduced in portfolio routes (new _get_service() pattern)
- .env.example not updated after 18 new config vars added
- TelegramMonitor stream() blocking pattern (new code)
- IngestionScheduler no circuit breaker (new code)
- AgentRunRecord with separate DeclarativeBase (new ORM)

**PASS → still passing:** Core infrastructure, CI pipeline, import integrity, kill switch logic, background task isolation.

**Previous FAILs (2026-04-04) — all resolved:** F1 error handling, F2 auth, F3 API versioning, F4 ConfigurationError — all confirmed fixed.

**Root cause of regression:** Phase 4+5 added ~20 new files rapidly. New routes, new background tasks, and new ORM models were added without applying the auth pattern, session management pattern, or .env.example discipline that was established in Phase 1-3. The platform grew 3x in surface area; hardening needs to catch up.
