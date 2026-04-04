# Memory

## Now
- Architettura aggiornata con AI Agent System (LangGraph, Qdrant, Jina)
- 4 FAIL audit risolti (F1-F4), 22 test passing
- Prossimo: commit + push, poi Phase 2 (AI Agents)

## Project: trdex
- **What**: AI-driven trading automation platform (crypto, FX, stocks)
- **Phase**: Audit fixes done. Phase 2 (AI Agents) è priorità immediata.
- **Stack**: Python 3.12+, LangGraph, Qdrant, Jina Embeddings, CCXT, asyncio, Pydantic v2, FastAPI, PG+TimescaleDB, Redis, polars
- **Architecture**: Clean Arch + DDD + Multi-Agent System (Scout → Analyst → Risk → Executor)
- **Owner**: Daniele (daniele@gravya.it), app privata (no MiFID)

## Architecture (docs/architecture.md)
- **AI Agent Layer**: LangGraph state machine, 4 agents (Scout, Analyst, Risk, Executor)
- **Context Ingestion**: News/social → Jina embeddings (UE, gratuito) → Qdrant vector DB
- **Data Layer**: Binance/CoinGecko/ForexRate feeds + rate limiter convesso
- **Execution**: Simulator (paper) + Live (gated), safety gates esterni all'AI
- **Dashboard MVP**: Streamlit (futuro: Next.js)
- **Backlog futuro**: LLM locale (Ollama), Telegram bot, Redis Streams

## Audit Status
- Deep audit 2026-04-04: 4 FAIL → tutti risolti
- F1: source-pinned feed error handling → FeedError typed
- F2: API auth → X-API-Key middleware
- F3: empty feed registry → ConfigurationError
- F4: API versioning → /v1/ prefix

## Key Files
- `docs/architecture.md` — architettura completa (aggiornata con AI agents)
- `.claude/reports/deep-audit-2026-04-04.md` — audit report
- `Riferimenti/Suggerimenti.md` — suggerimenti LLM secondario (integrati)

## Open Threads
- [ ] Commit + push audit fixes + architecture update
- [ ] Phase 2: LangGraph + Qdrant + Jina + Multi-Agent System

## Blockers
- (none)
