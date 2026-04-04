# Memory

## Now
- Architecture doc completato → `docs/architecture.md`
- Prossimo: scaffold progetto (pyproject.toml, struttura, docker)

## Project: trdex
- **What**: Trading automation platform (crypto, FX, stocks)
- **Phase**: Greenfield — architettura definita, pronto per scaffold
- **Stack**: Python 3.12+, uv, CCXT, asyncio, Pydantic v2, FastAPI, PostgreSQL+TimescaleDB, Redis, Ruff, pytest
- **Architecture**: Clean Architecture, DDD bounded contexts (Market Data, Strategy, Execution, Portfolio, Backtest, API)
- **Owner**: Daniele (daniele@gravya.it)

## Architecture (docs/architecture.md)
- 6 bounded contexts: Market, Strategy, Execution, Portfolio, Backtest, API
- Core interfaces: PriceFeed, Strategy, ExecutionGateway (ABC)
- Simulation-first: paper trading → backtest validation → live (gated)
- Rate limiter: convex throttle basato su API headers reali
- 5 MVP phases pianificate

## Key Reference Docs
- `docs/architecture.md` — architettura completa + tech spec
- `Riferimenti/` — API catalog, framework survey, HFT guidance

## Open Threads
- [ ] Scaffold progetto (pyproject.toml, struttura dir, docker-compose)
- [ ] Define branching strategy (git-workflow skill)
- [ ] Implementare primo PriceFeed (Binance REST)

## Blockers
- (none)
