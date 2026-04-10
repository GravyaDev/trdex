# Memory

## Now

- **trdex LIVE in production**: `https://trdex.gravya.it` (FastAPI) + `/dashboard/` (Streamlit, GitHub OAuth)
- **Phase 2 observation**: 25 crypto symbols (aggressive tuning), Runtime Config DB-backed, scheduler 5 min
- **Sessione 2026-04-10 chiusa**: Historical Market Episode RAG pipeline COMPLETE (8 step) + 2 merge forward da main. 344/344 test pass. Pushed.

## ⚠️ Branch LLM dev — `llm-agents`

- **Branch**: `llm-agents` (worktree `trdex-llm/`, pushato su origin)
- **Stato**: Task 1-7 LLM agents DONE (commits `d294159`, `a4d2dcb`, `4af323a`). RAG Tier 4b DONE (`0431781`). Merge forward da main x2 (`0121bc6`).
- **Design doc**: `.claude/reports/llm-agents-design-2026-04-08.md` (Rev 1, 23 objections)
- **Deploy guide**: `docs/deploy-llm-instance.md` — parallel Coolify app `trdex-llm.gravya.it` (DNS created)
- **Workflow**: bug di prod su main → merge forward nel branch. MAI il contrario.

## Prossima sessione

1. **Deploy trdex-llm su Coolify** — ANTHROPIC_API_KEY, OAuth callback, attivare Analyst LLM da dashboard
2. **Attivare RAG Tier 4b in prod** — `backfill_ohlcv.py --days 365` per symbol + `generate_episodes.py --all`
3. **Task 8 LLM Evaluation framework** — quando hai dati live (50 golden scenarios, LLM vs rule A/B)

## Project: trdex

- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 2 observation LIVE, 25 symbols
- **Stack**: Python 3.12+, LangGraph, Qdrant 1.13, Jina, CCXT, FastAPI, asyncpg, PG+TimescaleDB, polars==1.33.1, Streamlit+plotly, LangChain (Anthropic/OpenAI/Gemini)
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor), LangGraph state machine
- **Memory**: 7-tier (KB / agent_memory / nominations / trade_narratives / market_episodes / entity_graph / agent_runs)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)
- **Tests**: 344/344 passing
- **Commit identity**: `Author: GravyaDev <dev@gravya.it>`, trailer `Co-Authored-By: Kloud <kloud@gravya.it>`. MAI Claude.

## Production state

- **Domain**: `https://trdex.gravya.it` (Traefik + Let's Encrypt via Coolify)
- **Containers**: `db` (TimescaleDB 2.17.2-pg16), `redis` 7, `qdrant` 1.13, `app` (FastAPI), `dashboard` (Streamlit)
- **Auth**: OAuth2-proxy GitHub (dashboard), `TRDEX_API_KEY` X-API-Key (API)
- **Runtime Config**: DB-backed (migration 012), hot-reload via dashboard Settings
- **News sources**: CryptoCompare + StockData + Perplexity Sonar
- **Telegram**: disabilitato (`TRDEX_TELEGRAM_API_ID=0`)
- **StopLoss**: adattivo a CV, pin Binance feed (anti cross-feed distortion)

## Known Issues

- **Coolify non interpola env vars dentro Traefik labels** → basicauth hash hardcoded in compose
- **Dev locale**: polars==1.33.1 Windows, httpx (non aiohttp), telethon pyaes compile-from-source

## Scelte tecniche fisse

- RSI Wilder smoothing, SMA 5/13 (aggressive), Sharpe 365 days/year
- Balance ledger source of truth, idempotency `agent:{run_id}` / `close:{pos_id}`
- Intent enum con short reserved, readiness gate legge da ledger
- VPS ports: 8500→8000 (app), 8501→8501 (dashboard)
- Symbols/thresholds config via dashboard Settings (Runtime Config single source of truth)
- RAG Tier 4b: Qdrant collection `trdex_market_episodes`, doc_id deterministico `{symbol}:{timeframe}:{end_ts}` sha256
