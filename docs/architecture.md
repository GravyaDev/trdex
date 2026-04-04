# trdex — Architecture & Technical Spec

## Executive Summary

trdex è una piattaforma di trading automation AI-driven per crypto, FX e altri asset. L'architettura combina Clean Architecture con un **Multi-Agent System** orchestrato da LangGraph: agenti AI specializzati (Scout, Analyst, Risk Manager, Executor) collaborano attraverso un grafo a stati per analizzare mercati, valutare rischi ed eseguire operazioni. I dati di contesto (notizie, sentiment) sono indicizzati in un Vector DB (Qdrant) con embeddings Jina AI. Il sistema parte in modalità simulation-only: nessun ordine reale finché i risultati simulati non sono validati. Stack: Python 3.12+, LangGraph, Qdrant, Jina Embeddings, CCXT, PostgreSQL + TimescaleDB.

## Context & Objectives

- **Objective**: Costruire un sistema AI-driven che legga dati di mercato e contesto (notizie, sentiment) via API, utilizzi agenti AI specializzati per analisi e decisioni, esegua strategie in simulazione, e possa graduare verso l'esecuzione reale
- **Audience**: Daniele (sviluppatore unico, Gravya)
- **Approach**: Simulation-first — paper trading → backtest validation → live trading (gated)

---

## Stack Decision

| Componente | Scelta | Motivazione |
|-----------|--------|-------------|
| **Linguaggio** | Python 3.12+ | Ecosistema trading maturo (CCXT, pandas, numpy, ta-lib), async nativo, AI/ML first-class |
| **Package manager** | uv | Veloce, lockfile deterministico, gestisce Python versions |
| **AI Orchestration** | LangGraph | Grafi a stati per multi-agent workflow, controllo deterministico sulle decisioni AI |
| **Embeddings** | Jina AI | API gratuita, server in UE (GDPR-compliant), embeddings per RAG su notizie/sentiment |
| **Vector DB** | Qdrant | Vector search per contesto notizie/sentiment, self-hosted o cloud |
| **Exchange lib** | CCXT | 100+ exchange, API uniforme REST+WS, Python/JS/TS |
| **Data validation** | Pydantic v2 | Type-safe models per ordini, prezzi, config |
| **Data processing** | pandas + polars | pandas per compatibilità, polars per backtest ad alta velocità |
| **Async runtime** | asyncio + aiohttp | WebSocket feeds concorrenti, I/O non bloccante |
| **Database** | PostgreSQL + TimescaleDB | Time-series OHLCV nativo, query SQL standard, compressione |
| **Cache/realtime** | Redis (+ Streams) | Order book cache, pub/sub e Streams per comunicazione inter-agente |
| **API interna** | FastAPI | Dashboard/monitoring endpoint, auto-docs OpenAPI |
| **Dashboard MVP** | Streamlit | Prototipo rapido dashboard visuale (produzione futura: Next.js) |
| **Testing** | pytest + pytest-asyncio | Test async, fixtures, parametrize |
| **Linting** | Ruff | Linter+formatter all-in-one, velocissimo |
| **CI/CD** | GitHub Actions | Pipeline test → lint → type-check |
| **Container** | Docker + docker-compose | Dev environment riproducibile con DB + Redis + Qdrant |

---

## Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                         trdex system                              │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────── DATA LAYER ────────────────────────┐   │
│  │                                                           │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  │   │
│  │  │ Binance  │  │CoinGecko │  │ForexRate │  │News/Soc. │  │   │
│  │  │ (REST)   │  │ (REST)   │  │ (REST)   │  │  APIs    │  │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘  │   │
│  │       └──────────┬───┘─────────────┘─────────────┘        │   │
│  │                  ▼                                        │   │
│  │  ┌────────────────────────────┐  ┌──────────────────────┐ │   │
│  │  │   Price Feed Manager      │  │  Context Ingestion   │ │   │
│  │  │   (rate limiter, failover)│  │  (Jina → Qdrant)     │ │   │
│  │  └────────────┬───────────────┘  └──────────┬───────────┘ │   │
│  └───────────────┼─────────────────────────────┼─────────────┘   │
│                  │                             │                 │
│  ┌───────────── AI AGENT LAYER (LangGraph) ────┼─────────────┐   │
│  │               ▼                             ▼             │   │
│  │  ┌──────────────────┐   ┌──────────────────────────────┐  │   │
│  │  │  SCOUT Agent     │   │  ANALYST Agent               │  │   │
│  │  │  News/sentiment  │──▶│  Technicals + LLM reasoning  │  │   │
│  │  │  monitoring      │   │  (Qdrant RAG context)        │  │   │
│  │  └──────────────────┘   └─────────────┬────────────────┘  │   │
│  │                                       │                   │   │
│  │                                       ▼                   │   │
│  │                         ┌──────────────────────────────┐  │   │
│  │                         │  RISK MANAGER Agent          │  │   │
│  │                         │  Drawdown, limits, stop-loss │  │   │
│  │                         │  CAN BLOCK execution         │  │   │
│  │                         └─────────────┬────────────────┘  │   │
│  │                                       │                   │   │
│  │                                       ▼                   │   │
│  │                         ┌──────────────────────────────┐  │   │
│  │                         │  EXECUTOR Agent              │  │   │
│  │                         │  Order routing (sim/live)    │  │   │
│  │                         └─────────────┬────────────────┘  │   │
│  └───────────────────────────────────────┼───────────────────┘   │
│                                          │                       │
│  ┌───────────── EXECUTION LAYER ─────────┼───────────────────┐   │
│  │                                       ▼                   │   │
│  │  ┌──────────────────┐  ┌──────────────────────────────┐   │   │
│  │  │   Simulator      │  │   Live Executor (gated)      │   │   │
│  │  │   (paper trading)│  │   (CCXT → exchange)          │   │   │
│  │  └────────┬─────────┘  └──────────────┬───────────────┘   │   │
│  └───────────┼───────────────────────────┼───────────────────┘   │
│              └─────────────┬─────────────┘                       │
│                            ▼                                     │
│  ┌─────────────────────────────────────────┐                     │
│  │     Portfolio & Risk Manager            │                     │
│  │     (positions, P&L, drawdown, limits)  │                     │
│  └─────────────────────────────────────────┘                     │
│                                                                  │
│  ┌───────── STORAGE ──────────┐  ┌───── DASHBOARD ────────────┐  │
│  │ TimescaleDB (OHLCV, trades)│  │ FastAPI API + Streamlit UI │  │
│  │ Qdrant (embeddings/context)│  │ (status, portfolio, logs)  │  │
│  │ Redis (cache + streams)    │  │                            │  │
│  └────────────────────────────┘  └────────────────────────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

---

## Bounded Contexts (DDD)

| Context | Responsabilità | Dipendenze |
|---------|---------------|------------|
| **Market Data** | Connessioni API, normalizzazione prezzi, OHLCV, order book | Exchange APIs, aggregatori |
| **Context Ingestion** | News/social scraping, embedding via Jina AI, storage in Qdrant | News APIs, Jina, Qdrant |
| **AI Agents** | Multi-agent orchestration via LangGraph (Scout → Analyst → Risk → Executor) | Market Data, Context Ingestion, Portfolio |
| **Execution** | Routing ordini a simulatore o exchange reale | AI Agents (decisioni), Market Data (prezzi) |
| **Portfolio** | Tracking posizioni, P&L, risk metrics (Sharpe, drawdown, VaR) | Execution (trades completati) |
| **Backtest** | Replay storico con strategia, metriche di performance | Market Data (storico), AI Agents |
| **API/Dashboard** | Monitoring, stato sistema, controlli manuali (FastAPI + Streamlit) | Tutti (read-only) |

---

## Project Structure

```
trdex/
├── pyproject.toml              # uv/pip config, dependencies
├── .env.example                # Template variabili ambiente
├── docker-compose.yaml         # PostgreSQL + TimescaleDB + Redis
├── Dockerfile                  # App container
├── docs/
│   └── architecture.md         # Questo documento
├── src/
│   └── trdex/
│       ├── __init__.py
│       ├── main.py             # Entry point, avvio servizi
│       ├── config.py           # Settings da env/file (Pydantic Settings)
│       │
│       ├── market/             # Bounded Context: Market Data
│       │   ├── __init__.py
│       │   ├── models.py       # Ticker, OHLCV, OrderBook, Trade (Pydantic)
│       │   ├── feeds/
│       │   │   ├── __init__.py
│       │   │   ├── base.py     # ABC: PriceFeed, OrderBookFeed
│       │   │   ├── binance.py  # Binance WS + REST via CCXT
│       │   │   ├── coingecko.py # CoinGecko REST aggregator
│       │   │   └── forex.py    # ForexRateAPI / EODHD
│       │   ├── manager.py      # PriceFeedManager: routing, failover
│       │   └── rate_limiter.py # Adaptive rate limiter (da API headers)
│       │
│       ├── context/            # Bounded Context: Context Ingestion
│       │   ├── __init__.py
│       │   ├── models.py       # NewsItem, SentimentScore, ContextChunk
│       │   ├── ingestion.py    # News/social API scraping
│       │   ├── embeddings.py   # Jina AI embeddings client
│       │   └── vector_store.py # Qdrant storage and retrieval (RAG)
│       │
│       ├── agents/             # Bounded Context: AI Agents (LangGraph)
│       │   ├── __init__.py
│       │   ├── models.py       # AgentState, AgentDecision
│       │   ├── graph.py        # LangGraph state machine definition
│       │   ├── scout.py        # Scout Agent: news/sentiment monitoring
│       │   ├── analyst.py      # Analyst Agent: technicals + LLM reasoning
│       │   ├── risk.py         # Risk Manager Agent: limits, stop-loss, blocks
│       │   └── executor.py     # Executor Agent: order routing logic
│       │
│       ├── strategy/           # Strategy utilities (indicatori, config)
│       │   ├── __init__.py
│       │   ├── models.py       # Signal, StrategyConfig
│       │   ├── indicators.py   # Indicatori tecnici (RSI, MACD, BB, ecc.)
│       │   └── examples/
│       │       └── sma_cross.py # Esempio: SMA crossover (rule-based fallback)
│       │
│       ├── execution/          # Bounded Context: Execution
│       │   ├── __init__.py
│       │   ├── models.py       # Order, Fill, ExecutionResult
│       │   ├── gateway.py      # ExecutionGateway: route sim/live
│       │   ├── simulator.py    # Paper trading engine
│       │   └── live.py         # Real order execution (gated)
│       │
│       ├── portfolio/          # Bounded Context: Portfolio & Risk
│       │   ├── __init__.py
│       │   ├── models.py       # Position, Portfolio, RiskMetrics
│       │   ├── tracker.py      # Position tracking, P&L calc
│       │   └── risk.py         # Drawdown, Sharpe, VaR, position sizing
│       │
│       ├── backtest/           # Bounded Context: Backtest
│       │   ├── __init__.py
│       │   ├── engine.py       # Replay engine con data storica
│       │   └── report.py       # Performance report generator
│       │
│       ├── api/                # FastAPI dashboard
│       │   ├── __init__.py
│       │   ├── app.py          # FastAPI app factory
│       │   └── routes/
│       │       ├── status.py   # Health, stato sistema
│       │       ├── portfolio.py # Posizioni, P&L
│       │       └── strategy.py # Attivazione/disattivazione strategie
│       │
│       └── storage/            # Persistence layer
│           ├── __init__.py
│           ├── database.py     # Async SQLAlchemy + TimescaleDB
│           └── repositories.py # Repository pattern per OHLCV, trades, ecc.
│
├── tests/
│   ├── conftest.py
│   ├── market/
│   ├── strategy/
│   ├── execution/
│   ├── portfolio/
│   └── backtest/
│
├── scripts/
│   └── seed_historical.py     # Download e importa dati storici
│
└── Riferimenti/                # Documenti di ricerca (esistenti)
```

---

## Core Interfaces (ABC)

### PriceFeed

```python
from abc import ABC, abstractmethod
from trdex.market.models import Ticker, OHLCV

class PriceFeed(ABC):
    """Interfaccia base per tutti i price feed."""
    
    @abstractmethod
    async def get_ticker(self, symbol: str) -> Ticker:
        """Prezzo corrente per un simbolo."""
        ...
    
    @abstractmethod
    async def get_ohlcv(
        self, symbol: str, timeframe: str, limit: int = 100
    ) -> list[OHLCV]:
        """Candele storiche."""
        ...
    
    @abstractmethod
    async def subscribe_ticker(self, symbol: str, callback) -> None:
        """Stream real-time (WebSocket dove disponibile)."""
        ...
    
    @abstractmethod
    async def close(self) -> None:
        """Chiudi connessioni."""
        ...
```

### Strategy

```python
from abc import ABC, abstractmethod
from trdex.strategy.models import Signal
from trdex.market.models import OHLCV

class Strategy(ABC):
    """Interfaccia base per strategie di trading."""
    
    @abstractmethod
    async def evaluate(self, candles: list[OHLCV]) -> Signal | None:
        """Valuta i dati e ritorna un segnale (BUY/SELL) o None."""
        ...
    
    @abstractmethod
    def configure(self, config: "StrategyConfig") -> None:
        """Configura parametri della strategia (Pydantic model tipizzato)."""
        ...
```

### ExecutionGateway

```python
from abc import ABC, abstractmethod
from trdex.execution.models import Order, ExecutionResult

class ExecutionGateway(ABC):
    """Routing ordini a simulatore o exchange reale."""
    
    @abstractmethod
    async def execute(self, order: Order) -> ExecutionResult:
        ...
    
    @abstractmethod
    async def cancel(self, order_id: str) -> bool:
        ...
```

---

## Data Models (Pydantic)

```python
from pydantic import BaseModel
from datetime import datetime
from decimal import Decimal
from enum import Enum

class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"

class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"

class SignalAction(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"

class Ticker(BaseModel):
    symbol: str
    price: Decimal
    timestamp: datetime
    source: str

class OHLCV(BaseModel):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

class Signal(BaseModel):
    action: SignalAction
    symbol: str
    confidence: float  # 0.0 - 1.0
    reason: str
    timestamp: datetime

class Order(BaseModel):
    symbol: str
    side: Side
    type: OrderType
    amount: Decimal
    price: Decimal | None = None  # None for market orders
    
class ExecutionResult(BaseModel):
    order_id: str
    symbol: str
    side: Side
    filled_amount: Decimal
    filled_price: Decimal
    fee: Decimal
    timestamp: datetime
    simulated: bool  # True = paper trading
```

---

## Rate Limiting Strategy

Per conformità con le regole della knowledge-base:

1. **Basato su segnali API reali** — leggi `X-RateLimit-*` headers e `Retry-After`
2. **Fallback conservativo** — se headers assenti (CoinGecko free, ForexRateAPI), usa timer locale conservativo (default: 10 req/min). Configurabile per-exchange.
3. **Throttle proporzionale convesso**:
   - < 60% utilizzo → velocità normale
   - 60-85% → rallenta progressivamente (delay esponenziale)
   - 85-95% → quasi fermo (1 req ogni 5-10s)
   - > 95% → stop completo, attendi reset
4. **Per-exchange rate limiter** — ogni feed ha il suo limiter indipendente
5. **Circuit breaker con half-open recovery**:
   - Dopo 3 errori 429 consecutivi → OPEN (pausa 60s)
   - Dopo pausa → HALF-OPEN (1 probe request)
   - Se probe OK → CLOSED (normale)
   - Se probe fallisce → OPEN (pausa raddoppiata, max 5 min)
6. **Soft-ban detection** — confronta timestamp dati ricevuti con clock locale. Se dati > 60s stale su exchange che dovrebbe essere live → alert "possible soft ban/stale data"

---

## MVP Phases

### Phase 1 — Scaffold + Audit Fixes (COMPLETATA + fix in corso)
- [x] Scaffold progetto (pyproject.toml, uv, struttura directory)
- [x] Docker compose (PostgreSQL + TimescaleDB + Redis)
- [x] Pydantic models, PriceFeed ABC, Strategy ABC, Simulator, FastAPI
- [x] Rate limiter, circuit breaker, test suite, CI
- [ ] Fix audit F1-F4 (error handling, auth, API versioning)

### Phase 2 — AI Agent System + Context (PRIORITÀ IMMEDIATA)
Obiettivo: **il cervello AI del sistema** — LangGraph multi-agent + RAG context.
- [ ] Aggiungere dipendenze: langgraph, qdrant-client, jina SDK, polars
- [ ] Docker compose: aggiungere Qdrant
- [ ] Context Ingestion: Jina embeddings client + Qdrant vector store
- [ ] LangGraph state machine: Scout → Analyst → Risk → Executor pipeline
- [ ] Scout Agent: monitoraggio news/sentiment via API
- [ ] Analyst Agent: analisi tecnica + LLM reasoning con RAG context da Qdrant
- [ ] Risk Manager Agent: drawdown limits, stop-loss, block execution
- [ ] Executor Agent: routing a Simulator o Live (con gate check)
- [ ] Implementazione Binance REST feed (CCXT) — primo feed concreto
- [ ] End-to-end test: data → agents → simulated order

### Phase 3 — Execution & Portfolio (settimana 3-4)
- [ ] DefaultExecutionGateway con routing sim/live + gate check
- [ ] Portfolio tracker (posizioni, P&L)
- [ ] Position sizing conservativo (max 2% portfolio)
- [ ] Stop-loss hardware/software esterno all'AI
- [ ] Persistenza OHLCV su TimescaleDB
- [ ] Indicatori tecnici base (RSI, MACD, Bollinger) — input per Analyst Agent

### Phase 4 — Backtest & Validation (settimana 5-6)
- [ ] Confronto backtrader vs vectorbt, implementare il migliore
- [ ] Backtest engine (vectorized su polars DataFrame)
- [ ] Performance report (Sharpe, max drawdown, win rate)
- [ ] Seed script per dati storici
- [ ] Feed CoinGecko + ForexRateAPI

### Phase 5 — Dashboard & Real-time (settimana 7-8)
- [ ] Streamlit dashboard MVP (portfolio, agent decisions, logs)
- [ ] FastAPI endpoints completi (portfolio, strategy control)
- [ ] WebSocket feed Binance (raw, senza ccxt.pro)
- [ ] Alerting (log-based)

### Phase 6 — Live Trading (quando criteri simulazione soddisfatti)
Criteri gate (configurabili, default):
- Simulazione ≥ 30 giorni
- Sharpe ratio > 1.0
- Max drawdown < 20%
- Win rate > 40%

Gate hard-coded in ExecutionGateway (non process discipline).
- [ ] Live executor (ordini reali via CCXT)
- [ ] Safety gates (max loss giornaliero, kill switch) — esterno all'AI
- [ ] Binance testnet prima di produzione
- [ ] Audit di sicurezza API keys
- [ ] Test di precisione per-exchange prima di abilitare nuovi exchange

### Backlog Futuro
- [ ] LLM locale (Llama via Ollama/vLLM) per reasoning privacy-first
- [ ] Telegram bot per notifiche e analisi giornaliera
- [ ] Next.js dashboard (sostituzione Streamlit per produzione)
- [ ] Redis Streams per comunicazione inter-agente ad alta velocità

---

## Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Rate limit ban su exchange | M | H | Throttle convesso, circuit breaker, monitoring utilizzo |
| Dati di mercato inconsistenti | M | M | Validazione Pydantic, cross-check multi-source |
| Perdita API key | L | H | Secrets management, .env mai in git, encryption at rest |
| Simulazione non rappresentativa | M | H | Slippage model, fee simulation, confronto con paper trading exchange |
| Strategia profittevole in backtest ma non in live | H | H | Walk-forward validation, out-of-sample testing, position sizing conservativo |
| Downtime exchange durante posizione aperta | M | H | Circuit breaker, stop-loss su exchange, heartbeat monitoring |
| Allucinazione LLM che spinge ordine errato | M | H | Risk Manager Agent ha potere di veto, stop-loss esterno all'AI, confidence threshold |
| Sentiment data stale o manipolato | M | M | Cross-reference multi-source, decay temporale su embeddings, freshness check |
| Qdrant downtime | L | M | Fallback a strategia rule-based (SMA crossover) senza contesto AI |
| Jina API rate limit o downtime | L | M | Cache locale embeddings recenti, batch processing, fallback graceful |

---

## Success Metrics

| Metric | Target MVP | Measurement |
|--------|-----------|-------------|
| Feed uptime | > 99% | Heartbeat monitoring |
| Latenza ticker (REST) | < 500ms | Timestamp diff |
| Latenza ticker (WS) | < 100ms | Timestamp diff |
| Backtest coverage | > 1 anno di dati | Row count TimescaleDB |
| Test coverage | > 80% | pytest-cov |
| Simulation accuracy vs real | < 2% scostamento | Confronto paper vs exchange paper trading |

---

## Constraints (from knowledge-base)

- **Sempre leggere docs ufficiali API** prima di codificare qualsiasi integrazione
- **Rate limiter basato su segnali API reali**, non stime locali
- **Throttle proporzionale convesso** — ban risk cresce esponenzialmente
- **Consultare github.com/public-apis/public-apis** prima di scrivere integrazioni custom
- **Windows**: usare `.env` file, mai inline env vars
- **Commit identity**: `Co-Authored-By: Kloud <kloud@gravya.it>`

---

## Design Review Log (Multi-Agent Brainstorming — 2026-04-04)

### Obiezioni accolte e revisioni applicate

| # | Obiezione | Fonte | Revisione |
|---|-----------|-------|-----------|
| 1 | Rate limiter assume headers che non sempre esistono | Skeptic | Aggiunto fallback conservativo (10 req/min) se headers assenti |
| 2 | Nessun meccanismo per distinguere ban da outage | Skeptic | Aggiunta soft-ban detection (timestamp staleness > 60s) |
| 3 | Simulazione senza criteri di uscita | Skeptic + User Adv. | Definiti criteri gate: ≥30gg, Sharpe>1.0, DD<20%, WR>40%. Hard-coded. |
| 4 | CCXT nasconde varianza tra exchange | Skeptic | MVP solo Binance. Test precisione obbligatorio per nuovi exchange. |
| 5 | 8 settimane per 6 context irrealistico | Tutti | Phase 1 = thin vertical slice end-to-end. Context incrementali. |
| 6 | ccxt.pro è pacchetto separato per WS | Constraint G. | MVP solo REST. WS raw in Phase 4 senza ccxt.pro. |
| 7 | Circuit breaker senza half-open | Constraint G. | Aggiunto stato half-open con probe + backoff esponenziale (max 5min). |
| 8 | asyncio su Windows: ProactorEventLoop | Constraint G. | Pin SelectorEventLoop in entrypoint. CI su Linux via Docker. |
| 9 | Nessun feedback fino Phase 4 | User Adv. | `/health` + `/status` in Phase 1. Output terminale della sim. |
| 10 | Strategy.configure(dict) non tipizzato | User Adv. | Sostituito con Pydantic StrategyConfig tipizzato per strategia. |
| 11 | Nessun position sizing di default | User Adv. | Default 2% portfolio per trade in Phase 2. |
| 12 | Confusione Simulator vs Backtest | User Adv. | Documentato: Simulator = forward paper. Backtest = replay storico. |
| 13 | 6 bounded contexts troppi per solo dev | Tutti | Organizzazione logica mantenuta, implementazione incrementale. |
| 14 | CI backtest brucia GitHub Actions minutes | Constraint G. | Backtest solo locale. CI: unit test + lint + type-check. |

**Disposition: APPROVED** — Design rivisto e validato dopo review strutturata a 3 agenti.
