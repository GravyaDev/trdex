# Deep Audit — trdex — 2026-04-04

## Executive Summary

| Analyst | PASS | WARN | FAIL |
|---|---|---|---|
| Schema | 7 | 4 | 0 |
| Backend | 6 | 4 | 1 |
| Infrastructure | 6 | 3 | 0 |
| Security | 8 | 4 | 1 |
| Architecture | 6 | 4 | 2 |
| Frontend | 1 | 0 | 0 |
| **TOTAL** | **34** | **19** | **4** |

**Verdict**: 4 FAILs — all addressable before Phase 2 work begins. No show-stoppers for the scaffold, but fixes needed before adding real API integrations.

---

## Findings per Analyst

### Schema Analyst

#### PASS
- Migration journal: N/A — no migrations yet (greenfield)
- FK constraints: N/A — no schema defined yet
- Seed data: N/A — no seed files
- Schema/migration consistency: N/A
- Orphaned migrations: N/A
- Infrastructure declared: TimescaleDB + Redis correctly configured in docker-compose
- Async driver: asyncpg + SQLAlchemy async correctly declared

#### WARN
- **TimescaleDB hypertable indexes**: When schema is authored, `create_hypertable()` calls and time-column indexes are easy to omit → flag during migration authoring
- **Alembic not in dependencies**: SQLAlchemy async is declared but no Alembic → add `alembic>=1.13` to dev deps before first migration
- **`storage/__init__.py` empty**: No engine/session factory stub → populate when DB layer is implemented
- **Floating Docker tag**: `timescale/timescaledb:latest-pg16` will drift → pin to specific version (e.g. `2.14.2-pg16`)

---

### Backend Analyst

#### PASS
- All imports resolve correctly; TYPE_CHECKING guards used consistently
- No hardcoded secrets
- Configuration from environment via pydantic-settings
- Async/await correctness — no blocking calls in async context
- Error handling in PriceFeedManager failover loop
- Clean separation of concerns across all modules

#### WARN
- **Manager direct-source path unguarded**: `get_ticker(source=X)` bypasses try/except failover → wrap in exception handling
- **Simulator fill price**: Market orders with `price=None` fill at `Decimal("0")` → raise ValueError or require market price
- **`/status` hardcoded empty dicts**: No injection path for feeds/strategies → pass registries into `create_app()`
- **Position.side is plain str**: Inconsistent with StrEnum usage elsewhere → define `PositionSide` enum

#### FAIL
- **F1: Source-pinned feed path has no exception handling**: `PriceFeedManager.get_ticker(symbol, source=X)` propagates unhandled exceptions → wrap in try/except, log, fallback or re-raise typed `FeedError`

---

### Infrastructure Analyst

#### PASS
- Port mapping consistent (Dockerfile EXPOSE 8000 = config default = .env.example)
- All env vars documented in .env.example
- Healthchecks on db and redis services
- Database URL consistent across compose + config
- No Windows-specific paths in Docker config
- Volumes correctly mounted

#### WARN
- **No app service in compose**: Only db + redis, no app service → add app service with Dockerfile, depends_on, env_file
- **DB URL uses localhost in .env.example**: Inside compose network, should be `db:5432` → add comment or compose-specific override
- **CORS not configured**: No CORS middleware in FastAPI app → add before exposing to any non-localhost client

---

### Security Analyst

#### PASS
- API keys from environment (pydantic-settings)
- No committed .env file
- No hardcoded secrets in src/
- No f-string SQL construction
- Rate limiter with convex throttle + circuit breaker
- `ExecutionResult.simulated=True` enforced structurally in Simulator
- No key/secret logged anywhere
- .env.example contains only placeholders

#### WARN
- **`/status` unauthenticated**: Exposes operational mode → add API key check on non-health routes
- **Default DB URL contains credentials**: `trdex:trdex@localhost` silently used if env unset → reject default creds in non-dev modes
- **Simulator logs order details at INFO**: Acceptable for sim, but pattern could leak if copied to live → document guard convention
- **No code-level gate enforcer**: `TRDEX_MODE=live` works without checking gate criteria → implement gate check before live executor instantiation

#### FAIL
- **F2: No authentication on any endpoint**: Zero auth middleware on `/health` and `/status`. Before adding order/strategy routes, must add `X-API-Key` dependency or OAuth2 scheme as default dependency

---

### Architecture Analyst

#### PASS
- Clean module boundaries, no circular imports
- Configuration separated from business logic
- Simulation gate criteria match docs (Sharpe>1.0, DD<20%, ≥30d, WR>40%)
- StrategyConfig is Pydantic (not dict) — verified in ABC signature
- PriceFeed ABC matches architecture spec (4 methods + name property)
- Windows event loop pinned correctly

#### WARN
- **Redis not integrated**: Declared in config/compose but never referenced in code → add integration with explicit fallback if unavailable
- **ExecutionGateway gate logic absent**: ABC only, no concrete router implementing sim/live gate → implement DefaultExecutionGateway
- **Simulator doesn't store orders**: `_orders` dict never written in `execute()`, making `cancel()` always return False → store orders on execute
- **Rate limiter not wired**: File exists with correct implementation but not imported/used anywhere → wire into PriceFeed implementations

#### FAIL
- **F3: SPOF — empty feed registry at startup**: `main.py` registers no feeds; first request raises `RuntimeError` → register at least one feed before serving, raise `ConfigurationError` on empty registry
- **F4: No API versioning**: Routes at root (`/health`, `/status`) with no `/v1/` prefix → add version prefix before consumers depend on current paths

---

### Frontend Analyst

#### PASS
- No frontend: N/A — backend-only project with FastAPI REST API

---

## Prioritized Fixes

### P0 — Critical (blocks correctness or startup)
1. **F3**: Register at least one feed in `main.py` before serving; raise `ConfigurationError` on empty `PriceFeedManager`
2. **F1**: Wrap source-pinned feed calls in `PriceFeedManager` with try/except

### P1 — Warning (degrades reliability)
3. **F2**: Add API key authentication middleware to FastAPI (X-API-Key header dependency)
4. **F4**: Add `/v1/` prefix to all API routes
5. Simulator: raise ValueError when market order has no price (instead of filling at 0)
6. Simulator: store orders in `_orders` dict on `execute()` so `cancel()` works
7. Add Alembic to dev dependencies
8. Pin TimescaleDB Docker image to specific version
9. Add app service to docker-compose.yaml
10. Add CORS middleware to FastAPI app

### P2 — Improvements (not urgent)
11. Define `PositionSide` enum (replace plain str)
12. Pass feed/strategy registries into `create_app()` for `/status`
13. Add comment in .env.example about db:5432 for Docker Compose
14. Reject default DB credentials in non-dev modes
15. Wire rate limiter into PriceFeed implementations
16. Implement `DefaultExecutionGateway` with sim/live routing + gate check
17. Document simulator logging convention for live gateway

## Comparison with Previous Audit

First audit — no previous data for comparison.
