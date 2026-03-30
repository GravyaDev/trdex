# Project Context — Gravya Platform

> File compilato per il progetto Gravya. Gli agenti del dev-team leggono questo file come prima azione.

---

## Stack

- **Backend**: Express.js (embedded in Paperclip control plane, `app/server/`)
- **Frontend**: React 19 SPA con Vite (`app/packages/ui/`)
- **Database**: PostgreSQL 17 + pgvector (`pgvector/pgvector:pg17` Docker image)
- **ORM**: Drizzle ORM (Node.js) — schema in `app/packages/db/src/schema/`
- **AI Layer**: LangGraph + LiteLLM (Python 3.12, FastAPI) — in `app/services/agents/src/`
- **Auth**: BetterAuth + JWT HS256 (`PAPERCLIP_AGENT_JWT_SECRET`)
- **Realtime**: Soketi (Pusher-compatible) — porta 6001
- **Monorepo**: pnpm workspaces — `app/` è la root del monorepo
- **Runtime**: Node.js 20 + Python 3.12

---

## Struttura directory chiave

```
gravya-platform/
  app/                          # Monorepo root (pnpm workspaces)
    server/src/                 # Backend Express.js (TypeScript)
      routes/                   # Route handlers (REST API)
      services/                 # Business logic layer
      middleware/               # Auth, logging, error handling
    packages/
      ui/src/                   # React 19 SPA (Vite)
      db/src/
        schema/                 # Drizzle schema files (gravya_*.ts + paperclip tables)
        migrations/             # SQL migration files (NNNN_name.sql)
    services/agents/            # Python AI service
      src/
        api.py                  # FastAPI entry point (porta 3004)
        kloud/                  # Kloud orchestrator (LangGraph root graph)
          graph.py              # LangGraph StateGraph definition
          router.py             # Supervisor routing + DB tool loop
          types.py              # TypedDict states + Pydantic models
          memory_writer.py      # Scrive in DB solo tramite questo modulo
        supervisors/            # Supervisor subgraphs (meta_ads, content, admin, ...)
        executors/              # Executor modules (meta_ads/, content/, admin/)
        memory/                 # Retrieval, embedding helpers
        tools/
          llm_client.py         # Centralizzato — usare SEMPRE questo, mai provider SDK diretti
        utils/                  # DB helpers, auth, etc.
```

---

## Pattern specifici del progetto

- **Prefisso tabelle Gravya**: tutte le tabelle di dominio hanno prefisso `gravya_` (es. `gravya_memory`, `gravya_crm_records`, `gravya_agent_registry`). Le tabelle Paperclip non hanno prefisso.
- **Co-author obbligatorio**: ogni commit deve includere `Co-Authored-By: Kloud <kloud@gravya.it>`
- **Migrations**: generare con `pnpm db:generate` (Drizzle Kit) dalla root `app/`. File SQL in `app/packages/db/src/migrations/`. Numerazione sequenziale `NNNN_name.sql`.
- **Logger**: usare `logger.ts` (TypeScript) o `logging.getLogger(__name__)` (Python) — mai `console.log` / `print` in produzione.
- **API errors**: `{ error: string, code: string }` con HTTP status appropriati (400/401/403/404/500).
- **Agent JWT**: le chiamate da Paperclip → agents service usano `PAPERCLIP_AGENT_TOKEN` header; le chiamate inverse usano JWT firmato con `PAPERCLIP_AGENT_JWT_SECRET`.
- **No direct DB inserts dagli Executor**: gli executor emettono `memory_signals` nello state; è `memory_writer.py` a scrivere nel DB.

---

## Architettura AI

- **Orchestratore**: Kloud (LangGraph root graph) — modello default `claude-sonnet-4-6`
- **Pattern agenti**: Kloud → Supervisors → Executors (subgraph gerarchico)
- **Memory system — 6 tier**:
  - T1 — `gravya_pinned_documents` — direttive agenzia, pinned sempre nel prompt
  - T2 — `gravya_agent_memory` — memoria agente per client/sessione
  - T3 — `gravya_knowledge_rules` — regole operative obbligatorie
  - T4 — `gravya_memory` — semantic search (pgvector + BM25, voyage-4 1024d)
  - T5 — `gravya_entity_graph` — fatti entità clienti strutturati
  - T6 — `gravya_session_logs` — log sessioni recenti
- **LLM provider**: LiteLLM — sempre tramite `tools/llm_client.py`, mai provider SDK diretti
- **Embeddings**: Voyage AI `voyage-4` 1024 dimensioni (`VOYAGE_API_KEY`)
- **HITL levels** (dal più restrittivo):
  - `full_manual` — sempre interrupt, approvazione umana obbligatoria
  - `escalation` — interrupt se change_pct > soglia O total > budget_limit
  - `low_risk` — interrupt solo per anomalie significative
  - `full_auto` — nessun interrupt, esecuzione automatica
- **Supervisor routing**: `router.py` legge `agent_registry` da DB, confidence threshold 0.80 (env `ROUTING_CONFIDENCE_THRESHOLD`)
- **Modelli per ruolo**:
  - Orchestrazione Kloud: `claude-sonnet-4-6` (env `KLOUD_MODEL`)
  - Routing: configurabile per supervisor
  - Creative (content): GPT-4o o Claude Sonnet

---

## Comandi di sviluppo

```bash
# Avvio dev (dalla root app/)
pnpm dev                        # Avvia server + UI in watch mode
pnpm dev:server                 # Solo backend Express
pnpm dev:ui                     # Solo frontend Vite

# Docker (dalla root app/)
docker compose up -d            # Avvia tutti i servizi (db, server, agents, n8n, soketi)
docker compose up -d agents     # Solo il servizio Python

# Test
pnpm test:run                   # Vitest (tutti i test)
cd app/services/agents && python -m pytest src/tests/  # Test Python

# Migration DB (dalla root app/)
pnpm db:generate                # Genera SQL da schema Drizzle
pnpm db:migrate                 # Applica migrations pending

# Build
pnpm build                      # Build completo monorepo
pnpm typecheck                  # Type check TypeScript

# DB diretto (sviluppo locale)
docker exec -i app-db-1 psql -U paperclip -d paperclip
```

---

## Note importanti

- **DB porta**: in dev con Docker Compose la porta esposta è `5432` (non 5433 — dipende dalla configurazione locale). Verificare con `docker ps`.
- **DB user**: `paperclip` (non `postgres`) — sia user che password e database name.
- **Agents service**: porta `3004`, health check su `GET /health`. URL interno Docker: `http://agents:3004`.
- **Paperclip control plane**: Paperclip è il framework host su cui Gravya è costruito — non modificare tabelle senza prefisso `gravya_` a meno che non sia strettamente necessario.
- **Soketi**: porta 6001 (WebSocket). In dev, abilitato solo se `SOKETI_ENABLED=true`.
- **n8n**: porta 5678 — workflow automation, condivide il DB PostgreSQL (schema `n8n`).
- **BLOCKER attivo**: non implementare nuovi Supervisor di servizi (Google Ads, Email Marketing, ecc.) finché non è completata l'infrastruttura di test per Meta Ads (`tools/meta/ads_tool.py` + `executors/meta_ads/insights_fetcher.py`).
