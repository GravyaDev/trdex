"# trdex — PRD & Audit Memory

## Descrizione del Progetto
**trdex** è una piattaforma di trading algoritmico autonoma che esegue operazioni tramite:
- API di exchange esterni (Binance via CCXT)
- Segnali da gruppi/canali Telegram
- Sistema multi-agente AI (LangGraph: Scout → Analyst → Risk → Executor)
- RAG con Qdrant per contesto news/sentiment
- Backtest vectorizzato con Polars

## Stack Tecnologico
- **Backend:** Python 3.11/3.12, FastAPI, SQLAlchemy async, asyncpg
- **DB:** TimescaleDB (PostgreSQL), Qdrant (vector store), Redis (pianificato)
- **AI:** LangGraph, Jina AI embeddings
- **Exchange:** CCXT (Binance)
- **Telegram:** Telethon
- **Backtest:** Polars, backtrader

## Architettura
```
Market Feeds (Binance/CoinGecko)
    ↓
Agent Cycle: Scout → Analyst → Risk → Executor
    ↓
Simulation / Live Gateway (CCXT)
    ↓
TimescaleDB + Qdrant storage
```

## Sessioni di Lavoro

### 2026-02 — Audit Globale (solo report, nessuna modifica)
**Tipo:** Analisi / Code Review

Risultati audit:
- 29 issue totali: 5 critici, 13 medi, 11 bassi
- 24/48 test falliscono per mancanza pytest-asyncio
- Python version mismatch (env=3.11, constraint=>=3.12)
- Bug semantico: position_size usato come quantità assoluta invece di frazione
- 2x datetime.utcnow() deprecati
- CORS misconfiguration (stringa invece di lista)
- Sicurezza: api_key vuota disabilita auth silenziosamente
- Sessione Telethon non protetta
- assert usato come guardia di sicurezza in embeddings.py
- Due implementazioni RSI incompatibili (analyst vs backtest)
- Dead code nel backtest engine
- Redis dichiarato ma non usato

## Issue Aperti per Priorità

### P0 — Critici
- [ ] CRIT-1: Installare pytest-asyncio (24 test non girano)
- [ ] CRIT-2: Correggere requires-python (>=3.12 vs Python 3.11 reale)
- [ ] CRIT-3: datetime.utcnow() in agents/state.py → datetime.now(UTC)
- [ ] CRIT-4: datetime.utcnow() in context/vector_store.py → datetime.now(UTC)
- [ ] CRIT-5: Chiarire semantica position_size (frazione vs quantità assoluta)

### P1 — Medi
- [ ] MED-1: Dead code nel backtest engine (riga 100)
- [ ] MED-2: Unificare le due implementazioni RSI
- [ ] MED-3: self._embedder dead code in ingestion.py
- [ ] MED-4: asyncio.Queue nel telegram monitor
- [ ] MED-5: Float → Numeric nel DB per dati finanziari
- [ ] MED-6: unrealized_pnl_pct restituisce frazione non percentuale
- [ ] MED-7: CORS: split stringa comma-separated
- [ ] MED-8: Lazy init grafo non thread-safe

### P1 — Sicurezza
- [ ] SEC-1: Bloccare startup live se api_key vuoto
- [ ] SEC-2: Validazione lunghezza/formato API keys
- [ ] SEC-3: Proteggere file sessione Telethon
- [ ] SEC-4: assert → raise RuntimeError in embeddings.py

### P2 — Qualità / Architettura
- [ ] QUAL-1: import asyncio dentro loop while
- [ ] QUAL-2: _dict_to_state fragile
- [ ] QUAL-3: RSI non usa Wilder smoothing standard
- [ ] QUAL-4: Route inline in app.py, directory routes/ vuota
- [ ] QUAL-5: SMACrossStrategy fallback BTC/USDT hardcoded
- [ ] QUAL-6: Sharpe ratio assume barre giornaliere
- [ ] QUAL-7: fetch_polars omette colonna source
- [ ] QUAL-8: pin_event_loop_policy non chiamata nei test
- [ ] QUAL-9: README descrive Kloudify non trdex
- [ ] QUAL-10: Verificare __version__ in __init__.py
- [ ] TEST-1: Edge cases parser Telegram mancanti
- [ ] TEST-2: test_backtest_uptrend non deterministico
- [ ] TEST-3: test_ohlcv_repo non testa rollback
- [ ] TEST-4: Nessun test per modalità live del Risk Manager
- [ ] ARCH-1: Portfolio non persistente
- [ ] ARCH-2: TelegramMonitor.start() richiede interazione umana
- [ ] ARCH-3: Nessun retry/idempotenza per ordini
- [ ] ARCH-4: Nessuna schedulazione del ciclo agente
- [ ] ARCH-5: Redis dichiarato ma mai usato

## Feature Backlog
- WebSocket feed (Phase 4)
- Live execution gateway (Phase 5)
- Dashboard Next.js
- Scheduler del ciclo agente
- Persistenza portfolio
- Autenticazione Telethon headless
"