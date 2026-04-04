# Task Board

## Today
- [ ] Scaffold progetto (pyproject.toml, uv, struttura directory, docker-compose)
- [ ] Definire branching strategy

## This Week
- [ ] Pydantic models (Ticker, OHLCV, Order, Signal)
- [ ] PriceFeed ABC + implementazione Binance REST (CCXT)
- [ ] Rate limiter adattivo
- [ ] Test suite base (pytest + conftest)
- [ ] CI/CD pipeline (GitHub Actions: test + lint + type-check)

## Backlog
- [ ] Strategy ABC + esempio SMA crossover
- [ ] Indicatori tecnici (RSI, MACD, Bollinger)
- [ ] Simulator (paper trading engine)
- [ ] ExecutionGateway (routing sim/live)
- [ ] Portfolio tracker (posizioni, P&L)
- [ ] Persistenza OHLCV su TimescaleDB
- [ ] Backtest engine + performance report
- [ ] Seed script dati storici
- [ ] Feed CoinGecko + ForexRateAPI
- [ ] FastAPI dashboard
- [ ] WebSocket feed Binance
- [ ] Risk manager (position sizing, drawdown limits)
- [ ] Live executor (ordini reali, testnet first)
- [ ] Safety gates (max loss, kill switch)

## Done
- [x] Onboarding + Kloudify setup (2026-04-04)
- [x] Stack decision: Python 3.12+, uv, CCXT, asyncio, Pydantic, FastAPI, PG+TimescaleDB, Redis (2026-04-04)
- [x] Architecture doc: `docs/architecture.md` (2026-04-04)
