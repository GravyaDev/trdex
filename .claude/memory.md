# Memory

## Now

- **trdex LIVE in production**: `https://trdex.gravya.it` (FastAPI) + `/dashboard/` (Streamlit, GitHub OAuth)
- **trdex-llm deploy-ready**: runbook `docs/deploy-trdex-llm-runbook.md`. DNS OK, branch `llm-agents` pushato @ `f3fea47`, GitHub App Coolify già installata org-wide, OAuth App creata, 3 LLM provider key pronte. Prossimo passo: creare app Coolify UI.
- **Sessione 2026-04-18 (completata)**: Kloudify v1.3.2→v1.4.4 + 2 merge forward (7+3 commit) + runbook deploy trdex-llm + P1 hot-reload integration toggles CHIUSO. Commits: `c720f0e`, `7850117`, `98e69e3`, `f3fea47`. Push done. 400/400 test. 0 vulns.

## ⚠️ Branch LLM dev — `llm-agents`

- **Branch**: `llm-agents` (worktree `trdex-llm/`, pushato su origin)
- **Stato**: Task 1-7 LLM agents DONE. LLMCaller wired nel lifespan (commit `bb9b1a4`). RAG Tier 4b DONE. Telegram pipeline COMPLETE. Security 7/7 CLOSED. Merge forward x6 totali. 400/400 test.
- **Design doc**: `.claude/reports/llm-agents-design-2026-04-08.md` (Rev 1, 23 objections)
- **Deploy guide**: `docs/deploy-llm-instance.md` — parallel Coolify app `trdex-llm.gravya.it` (DNS created)
- **Workflow**: bug di prod su main → merge forward nel branch. MAI il contrario.

## Prossima sessione

1. **Deploy trdex-llm Step 1-3 (UI Coolify + VPS)** — seguire `docs/deploy-trdex-llm-runbook.md`. Step 1-3 umani, Step 4-6 insieme.
2. **Attivare RAG Tier 4b in prod** — dopo deploy OK: `backfill_ohlcv.py --days 365` per symbol + `generate_episodes.py --all`
3. **TelegramSignalExecutor** — Step 2 Telegram integration (7 subtask in Task Board)
4. **Multi-asset Forex** — design approvato, 4 fasi (AssetClassRegistry → OANDA → Dashboard split)
5. **Task 8 LLM Evaluation framework** — quando hai dati live dal deploy

## Project: trdex

- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Phase 2 observation LIVE, 25 symbols
- **Stack**: Python 3.12+, LangGraph, Qdrant 1.13, Jina, CCXT, FastAPI, asyncpg, PG+TimescaleDB, polars==1.33.1, Streamlit+plotly, LangChain (Anthropic/OpenAI/Gemini)
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor), LangGraph state machine
- **Memory**: 7-tier (KB / agent_memory / nominations / trade_narratives / market_episodes / entity_graph / agent_runs)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)
- **Tests**: 400/400 passing
- **Commit identity**: `Author: Daniele <daniele@gravya.it>`, trailer `Co-Authored-By: Kloud <kloud@gravya.it>`. MAI Claude. MAI `dev@gravya.it` (mailbox inesistente, era regressione pre-2026-04-17).

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

- RSI Wilder + direzionale (>50 BUY, <50 SELL, 30/70 overextension), SMA 9/21 su 1h, Sharpe 365 days/year
- SL 2% / TP 4% / trailing 1.5% (post-tuning 2026-04-15), 10 symbols liquidi (BTC ETH SOL BNB XRP ADA AVAX LINK POL ATOM)
- Balance ledger source of truth, idempotency `agent:{run_id}` / `close:{pos_id}`
- Intent enum con short reserved, readiness gate legge da ledger
- VPS ports: 8500→8000 (app), 8501→8501 (dashboard)
- Symbols/thresholds config via dashboard Settings (Runtime Config single source of truth)
- RAG Tier 4b: Qdrant collection `trdex_market_episodes`, doc_id deterministico `{symbol}:{timeframe}:{end_ts}` sha256
