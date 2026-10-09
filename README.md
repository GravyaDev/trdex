# trdex

AI-driven trading automation platform for crypto, FX, and multi-asset markets.

## What it does

trdex runs a continuous trading loop that monitors multiple symbols on Binance, generates buy/sell signals using technical analysis (SMA cross, RSI, volatility regime), manages risk with adaptive stop-loss/take-profit, and tracks portfolio performance in simulation mode before going live.

**Current state**: Phase 2 observation — running 24/7 on a VPS in simulation mode with 9 crypto symbols, accumulating real-market-data trade history to validate strategy performance before risking real capital.

## Architecture

```
                    ┌──────────────────────────────────────────────┐
                    │              Scheduler (5 min)               │
                    │     for each symbol in watchlist:            │
                    └──────────┬───────────────────────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │        LangGraph State Machine   │
              │                                  │
              │  Scout ──► Analyst ──► Risk ──► Executor
              │    │          │         │          │
              │  market    signal    gates      fill
              │  data +    (SMA +    (kill      (Simulator
              │  context    RSI +    switch,     or Live
              │  (Qdrant)   CV)     sizing,     Executor)
              │                     pyramiding)
              └──────────────────────────────────┘
                               │
              ┌────────────────▼────────────────┐
              │         StopLossMonitor          │
              │  tick every 30s, adaptive SL/TP  │
              │  proportional to symbol CV       │
              └─────────────────────────────────┘
```

### Key components

| Component | Purpose | Location |
|---|---|---|
| **Agent pipeline** | Scout → Analyst → Risk → Executor state machine | `src/trdex/agents/` |
| **Intent model** | 5-value enum (OPEN_LONG, CLOSE_LONG, OPEN_SHORT, CLOSE_SHORT, HOLD) + signal-to-intent translator | `src/trdex/agents/intent.py` |
| **Market feeds** | Binance REST/WS (primary) + 5 fallback feeds, rate-limited | `src/trdex/market/` |
| **Risk management** | StopLossMonitor with adaptive SL/TP/trailing proportional to volatility CV, KillSwitch, per-symbol config overrides | `src/trdex/risk/` |
| **Execution** | Simulator (simulation mode) + LiveExecutor scaffold (live mode), idempotency keys | `src/trdex/execution/` |
| **Portfolio** | Position tracking, atomic close-fill with P&L ledger, mark-to-market | `src/trdex/portfolio/` |
| **Storage** | TimescaleDB: OHLCV, positions, agent_runs, account_balance, entity_graph, agent_memory, symbol_config | `src/trdex/storage/` |
| **Context** | News ingestion (CryptoCompare, StockData) → Jina embeddings → Qdrant vector store | `src/trdex/context/` |
| **Dashboard** | Streamlit UI with portfolio, positions, P&L charts, agent history, risk monitor, per-symbol config | `src/trdex/dashboard/` |
| **API** | FastAPI REST with auth, rate limiting, CORS | `src/trdex/api/` |
| **Memory** | 6-tier system: KB, agent_memory, nominations, trade narratives, entity graph, agent_runs | `src/trdex/memory/` |
| **Backtest** | Polars-vectorised engine with RSI Wilder/MACD/Bollinger, Sharpe annualisation | `src/trdex/backtest/` |

## Stack

- **Runtime**: Python 3.12+, asyncio
- **AI framework**: LangGraph + LangChain Core (today: deterministic rule engine; branch `llm-agents`: real LLM agents)
- **Database**: PostgreSQL + TimescaleDB 2.17 (via asyncpg + SQLAlchemy 2.x async)
- **Vector store**: Qdrant 1.13 (news/sentiment context for agent decisions)
- **Embeddings**: Jina v3 (1024-dim, via httpx — no SDK dependency)
- **Exchange**: Binance via CCXT (REST + WebSocket)
- **Cache**: Redis 7.x
- **Dashboard**: Streamlit + Plotly
- **Deploy**: Docker Compose on Coolify 4.x (Traefik + Let's Encrypt)
- **Testing**: pytest + pytest-asyncio, 312 tests

## Quick start (dev locale)

```bash
# Prerequisites: Python 3.12+, Docker, uv
git clone https://github.com/GravyaDev/trdex.git
cd trdex

# Copy env template and fill in API keys
cp .env.example .env
# Edit .env: at minimum set POSTGRES_PASSWORD

# Start infrastructure (DB, Redis, Qdrant) + app
docker compose up -d

# The app applies migrations automatically on startup (lifespan),
# creates the Qdrant collection, and starts the scheduler if
# TRDEX_AGENT_SCHEDULER_ENABLED=true.

# Run tests
uv run pytest -q

# Dashboard (dev locale, without Docker)
uv run streamlit run src/trdex/dashboard/app.py
# Open http://localhost:8501
```

## Production deploy (Coolify)

trdex is designed to run on Coolify 4.x with the included `docker-compose.yaml`. The compose defines 5 services:

| Service | Image | Port |
|---|---|---|
| `db` | timescale/timescaledb:2.17.2-pg16 | internal only |
| `redis` | redis:7-alpine | internal only |
| `qdrant` | qdrant/qdrant:v1.13.0 | internal only |
| `app` | build from repo | 8500 → 8000 |
| `dashboard` | build from repo (same image, different CMD) | /dashboard/ via Traefik |

The dashboard is served at `/dashboard/` behind Traefik basic-auth middleware. See `docker-compose.yaml` for the Traefik labels and the hardcoded htpasswd hash.

Full deploy guide: `/opt/gravya/services/coolify-trdex/README.md` on the VPS.

## Configuration

All configuration is via environment variables. See `.env.example` for the full list with descriptions. Key variables:

| Variable | Purpose | Default |
|---|---|---|
| `TRDEX_MODE` | `simulation` or `live` | `simulation` |
| `TRDEX_API_KEY` | FastAPI auth (empty = no auth) | — |
| `TRDEX_AGENT_SCHEDULER_ENABLED` | Auto-run agent cycles | `false` |
| `TRDEX_AGENT_SCHEDULER_INTERVAL` | Seconds between cycles | `300` |
| `TRDEX_AGENT_SCHEDULER_SYMBOLS` | Comma-separated pairs | `BTC/USDT,ETH/USDT` |
| `TRDEX_SL_POSITION_PCT` | Base stop-loss % (adaptive scales up for volatile coins) | `0.05` |
| `TRDEX_SL_TAKE_PROFIT_PCT` | Base take-profit % | `0.10` |
| `TRDEX_SL_TRAILING_STOP_PCT` | Base trailing stop % | `0.03` |
| `TRDEX_GATE_MAX_DRAWDOWN` | Max realised drawdown before KillSwitch | `0.20` |

## Risk management

The StopLossMonitor runs every 30 seconds and uses **adaptive thresholds** proportional to each symbol's coefficient of variation (CV):

```
effective_sl  = max(base_sl,  2.5 × CV)
effective_tp  = max(base_tp,  5.0 × CV)
effective_trail = max(base_trail, 1.5 × CV)
```

This prevents whipsaw stop-outs on volatile altcoins (e.g., ENJ with CV=13% gets SL=32% instead of 5%) while keeping tight stops on low-vol assets (BTC with CV=0.4% stays at 5%).

Per-symbol overrides are available via the `/v1/risk/symbol-config` API and the dashboard "Per-Symbol Risk Thresholds" expander.

**Position size** is risk-based: `size = min(max_position_pct, risk_per_trade_pct / effective_sl)`, so a wider adaptive stop means a smaller position, not more risk per trade.

**Volatility-regime gate** (Risk Gate 4c): new entries are blocked when the CV of the last 20 closes is outside `thresholds.regime_cv_min` / `regime_cv_max`, the range the strategy was backtested on (`scripts/backtest/regime_range.py`). In simulation unset bounds disable the gate; in live they block every entry.

## Go-live checklist

Live mode is enforced by the readiness gate (`GET /v1/system/readiness`, dashboard banner, Risk Gate 5 on every live entry). Each step below is a readiness criterion unless marked otherwise.

1. **Refresh data and derive regime bounds — at the start of the simulation that will be judged.** `python scripts/backtest/fetch_ohlcv.py`, then `python -m scripts.backtest.regime_range`; enter `regime_cv_min`, `regime_cv_max` and `regime_data_end` in dashboard → Risk Thresholds. The change date (`regime_set_at`) is stamped automatically; if it is more recent than `gate_min_days` the readiness report shows a warning (the simulation did not run with these bounds).
2. **Run the simulation** for `gate_min_days` with the bounds in place: ≥ 20 trades, win rate, Sharpe and max drawdown within the configured limits.
3. **Check the readiness banner**: READY and no warnings.
4. **Switch `TRDEX_MODE=live`** (not a readiness criterion: operator decision).
5. **Keep the bounds fresh**: readiness fails once `regime_data_end` is older than `regime_max_age_days` (default 90). In live that blocks new entries (exits and the StopLossMonitor keep working) until step 1 is repeated.

## Observability

- **Dashboard**: `https://trdex.gravya.it/dashboard/` (basic auth)
- **CLI**: `uv run python -m trdex.scripts.inspect_runs --hours 24` (inside app container or dev)
- **API**: `GET /v1/health`, `/v1/status`, `/v1/system/readiness`, `/v1/portfolio`, `/v1/risk/status`

## Project status

| Phase | Status | Description |
|---|---|---|
| Phase 1 | ✅ Done | Core scaffold, data layer, market feeds |
| Phase 2 | 🟡 Active | Production observation in simulation mode |
| Phase 2 LLM | 📝 Design | Real LLM agents (branch `llm-agents`) |
| Phase 3 | ⏳ Pending | Strategy iteration (multi-SMA, RSI, MACD) |
| Phase 4 | ⏳ Pending | Live mode with real capital |

## License

MIT
