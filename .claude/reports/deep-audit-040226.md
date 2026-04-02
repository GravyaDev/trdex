# Deep Audit — gravya-platform — 040226

**Date**: 2026-04-02  
**Methodology**: 7 independent domain agents (parallel)  
**Codebase snapshot**: 54 SQL migrations, ~96 Node .ts files, 150+ React .tsx files, 56 Python modules

---

## Executive Summary

| Domain | PASS | WARN | FAIL |
|---|---|---|---|
| DB / Schema | 5 | 3 | 1 |
| Python / Agents | 6 | 4 | 3 |
| Infrastructure | 3 | 2 | 4 |
| Architecture | 7 | 3 | 2 |
| Security | 4 | 2 | 3 |
| Frontend | 10 | 5 | 0 |
| Testing | 9 | 10 | 8 |
| **TOTAL** | **44** | **29** | **21** |

**Overall verdict**: ⚠️ WARN — System is functional but has critical security gaps (JWT bypass default, unprotected endpoint) and low test coverage (~7%) on critical paths.

---

## Findings per Dominio

---

### 1. DB / Schema Audit

#### PASS
- ✅ Journal completo — 54 entries (idx 0–53) tutte presenti con tag corrispondenti in `migrations/meta/_journal.json`
- ✅ Migrations gravya_* non alterano tabelle Paperclip — tutte le migration 0047–0053 usano solo `CREATE TABLE gravya_*`, `ALTER TABLE gravya_*` o `INSERT INTO gravya_*`
- ✅ FK constraints corretti — `gravya_supervisor_pipeline.supervisor_id` → `gravya_supervisors.id`, `gravya_supervisor_pipeline.executor_id` → `gravya_executors.id`, tutti con `ON DELETE CASCADE` appropriato
- ✅ Indici presenti su `agent_id`, `client_id`, `supervisor_id` nelle tabelle gravya_* (migration 0052)
- ✅ Seed data idempotenti — tutti gli INSERT nelle migration usano `ON CONFLICT DO NOTHING` o `ON CONFLICT (...) DO UPDATE`

#### WARN
- ⚠️ IVFFlat index con `lists=100` — migration 0047 crea indici IVFFlat ma non imposta `ivfflat.probes` nelle query di retrieval (`pipelines/retrieval.py`). Recall degradata senza probes ≥ sqrt(lists). Suggerimento: aggiungere `SET LOCAL ivfflat.probes = 10` nelle query pgvector
- ⚠️ Seed data in migration SQL — supervisor/executor/tool seed (migration 0052, 0053) eseguiti automaticamente in ogni ambiente (staging, prod). Potenzialmente indesiderato in prod. Suggerimento: separare seed in script dedicato con flag `--seed-only`
- ⚠️ `gravya_schema_version` trigger: `RETURN NEW` nel branch `DELETE` — migration 0052, funzione `gravya_bump_supervisor_version()`. Su DELETE, `NEW` è NULL; il trigger dovrebbe restituire `COALESCE(NEW, OLD)` per evitare errori silenziosi

#### FAIL
- ❌ Trigger `gravya_bump_supervisor_version()` usa `RETURN NEW` anche su DELETE — `NEW` è sempre NULL su DELETE in PostgreSQL. Il trigger fallisce silenziosamente, la `schema_version` non viene incrementata dopo DELETE di un supervisor/executor. Fix: cambiare `RETURN NEW` in `RETURN COALESCE(NEW, OLD)` nella funzione trigger

---

### 2. Python / Agents Audit

#### PASS
- ✅ Nessun import rotto nei file runtime principali (`graph.py`, `router.py`, `supervisor_registry.py`, `generic_supervisor.py`, `generic_executor.py`, `memory_writer.py`, `retrieval.py`, `auth.py`)
- ✅ `llm_invoke_with_tools` importato correttamente in `router.py` (fix applicato)
- ✅ `task_flags: dict` presente in `SupervisorState` (`base_supervisor.py:14`)
- ✅ Nessun import da `..memory.retrieval` nei file runtime — il refactoring a `..pipelines.retrieval` è corretto
- ✅ Nessun secret hardcoded — tutti i secret letti da env vars via `settings.py`
- ✅ Async/await corretto in tutti i file runtime — nessuna chiamata sync in contesto async

#### WARN
- ⚠️ Dead code con import rotti: `supervisors/meta_ads_supervisor.py`, `supervisors/content_supervisor.py`, `supervisors/admin_supervisor.py` importano da `..memory.retrieval` (path pre-refactoring, non esiste). Non caricati a runtime ma causerebbero `ImportError` se importati. Annotati come "reference/da rimuovere"
- ⚠️ `utils/supabase_client.py` e `utils/db.py` coesistono — doppio client DB. `supabase_client.py` usa SDK Supabase, `db.py` usa psycopg pool direttamente. Verificare se `supabase_client.py` è usato da qualche path runtime o è legacy
- ⚠️ `supervisor_input` in `graph.py::node_run_supervisor` non include `task_flags: {}` — SupervisorState lo dichiara required. LangGraph può fallire con KeyError se il campo non è inizializzato. Fix: aggiungere `"task_flags": {}` al dict `supervisor_input`
- ⚠️ `agent_registry` orphans: migration 0051 seeda `content-strategist` e `creative-director` in `agent_registry` (vecchia tabella) ma non in `gravya_supervisors` (tabella runtime). Il router può routare a questi agent_id ma `get_or_build_supervisor()` restituirà None → fallback silenzioso

#### FAIL
- ❌ `task_flags` non inizializzato in `graph.py` — `supervisor_input` dict non contiene `"task_flags": {}"`. Fix richiesto: aggiungere il campo al dict prima di invocare il subgraph — `graph.py`, nodo `node_run_supervisor`
- ❌ `rejection_code` su classify failure troppo generico — quando `node_classify_task` fallisce (exception), `task_flags={}` e tutti gli step `condition != "always"` vengono saltati silenziosamente. Il risultato è un output vuoto che poi porta a `rejection_code: rejected:api_error` in `node_collect_result`. Il codice dovrebbe essere `rejected:classification_failed`
- ❌ `supervisors/meta_ads_supervisor.py` — import rotto (`from ..memory.retrieval import ...`). Anche se dead code, deve essere rimosso o fixato per evitare confusione e `ImportError` accidentale

---

### 3. Infrastructure Audit

#### PASS
- ✅ Volume mounts in `docker-compose.yml` usano path Unix (`./services/agents:/app`) — nessun path Windows-specific
- ✅ `n8n` e `soketi` non hanno dipendenze hardcoded da agents service
- ✅ Healthcheck configurato per il servizio agents in `docker-compose.yml`

#### WARN
- ⚠️ `JWT_ENABLED` default in `auth.py` è `"false"` — se la env var non è impostata, tutti gli endpoint sono accessibili senza autenticazione. Pericoloso in staging/prod dove env vars potrebbero mancare
- ⚠️ CORS `allow_origins=["*"]` in `api.py` — accetta richieste da qualsiasi origine. In prod limitare agli origini effettivi di Paperclip

#### FAIL
- ❌ Port mismatch — `settings.py` dichiara `API_PORT=8001` ma `docker-compose.yml` mappa porta `3004:8001` sulla riga del servizio agents. La porta **interna** è 8001 (uvicorn), quella **esterna** è 3004. Il commento in `docker-compose.yml` dice "AGENTS_PORT=3004" come se fosse la porta interna. Verificare che uvicorn ascolti su 8001 e che tutte le chiamate interne usino 8001
- ❌ `EMBEDDINGS_API_KEY` non presente nelle env vars del servizio agents in `docker-compose.yml` — `settings.py` la richiede per le embeddings (Voyage AI). Avvio fallirà se `SKIP_CONFIG_VALIDATION` non è impostato
- ❌ `/kloud/invoke` endpoint non protetto da JWT — vedere Security Audit per dettagli
- ❌ `JWT_ENABLED` default a `false` — vedere Security Audit per dettagli

---

### 4. Architecture Audit

#### PASS
- ✅ Failure isolation — crash di un executor non blocca altri supervisori: `run_generic_executor` wrappa ogni step in try/except, `is_critical=False` continua il pipeline
- ✅ Cache failure safe — `get_or_build_supervisor()` cattura eccezioni nel build (incluso DB irraggiungibile) e restituisce None invece di crashare il processo
- ✅ Double-check locking corretto — `supervisor_registry.py`: fast path cache check, poi lock, poi re-check dentro lock — pattern corretto per evitare doppio build concorrente
- ✅ State isolation — `SupervisorState` è un `TypedDict`, ogni invocazione riceve un nuovo dict → nessun riferimento mutabile condiviso tra invocazioni
- ✅ `initialize_supervisors()` è no-op (`pass`) — backward compat preservata
- ✅ `get_supervisor()` shim funziona — chiama `get_or_build_supervisor()` che è il nuovo path
- ✅ Pipeline condition evaluation safe — su `classify_task` failure, `flags={}` → tutti gli step `condition != "always"` vengono saltati. Safe default (non esegue passi condizionali senza classificazione)

#### WARN
- ⚠️ LLM provider unico — nessuna fallback chain configurata per il provider LLM usato in `classify_task` (Haiku). Se il provider è down, la classificazione fallisce e tutti i passi condizionali vengono saltati silenziosamente
- ⚠️ `task_flags` non nel `supervisor_input` iniziale — vedi Python Audit FAIL
- ⚠️ Memory writer — nessuna scrittura diretta da supervisors/executors verso Tier 2. I segnali passano tramite `memory_signals` nel return state ✅. MA: il memory writer riceve i segnali dal nodo `memory_writer` nel Kloud graph — verificare che tutti i percorsi di uscita dal supervisor passino per questo nodo

#### FAIL
- ❌ `task_flags` non inizializzato in `supervisor_input` — vedi Python Audit
- ❌ `agent_registry` orphans — `content-strategist` e `creative-director` presenti in `agent_registry` (migration 0051) ma non in `gravya_supervisors`. Il router può assegnare task a questi supervisor_id ma `get_or_build_supervisor()` restituirà None con fallback silenzioso

---

### 5. Security Audit

#### PASS
- ✅ JWT verification — algoritmo verificato (`HS256`), `exp` check attivo, secret letto da env var (`PAPERCLIP_AGENT_JWT_SECRET`)
- ✅ `importlib` whitelist — `_ALLOWED_MODULE_PREFIXES = frozenset({"src.tools."})` + `_validate_module_path` blocca `..` e caratteri non-alphanum — prevenzione path traversal
- ✅ Nessun secret in codice o response body — tutti i secret letti da env vars, nessun echo in risposta API
- ✅ LLM guard presente — `utils/llm_guard.py` con prompt injection mitigation

#### WARN
- ⚠️ `CORS allow_origins=["*"]` — vedi Infrastructure Audit
- ⚠️ `HITL_WEBHOOK_SECRET` non validato all'avvio — il secret viene usato per verificare webhook HITL ma non è incluso nella validation all'avvio in prod. Se assente, HMAC verification fallirà a runtime

#### FAIL
- ❌ `JWT_ENABLED` default a `"false"` — `auth.py:38-39` — se env var non impostata, tutti gli endpoint accettano richieste non autenticate. Fix: cambiare default a `"true"` (`os.getenv("JWT_ENABLED", "true")`)
- ❌ `/kloud/invoke` endpoint non ha JWT middleware — `api.py:401-415` — l'endpoint principale di invocazione non usa `Depends(verify_token)`. Fix: aggiungere dipendenza auth identica agli altri endpoint
- ❌ Nessun rate limiting su `/invoke` — endpoint esposto senza throttling. In prod, un attaccante può generare costi LLM illimitati. Fix: aggiungere `slowapi` o `fastapi-limiter`

---

### 6. Frontend Audit

#### PASS
- ✅ Gravya routes protette — route nestata sotto `<CloudAccessGate />` — `App.tsx:170, 316`
- ✅ API calls usano base URL relativo `/api/` — nessun URL hardcoded (localhost, 3004) — `api/client.ts:1`, `ask-gravya.ts:28-43`
- ✅ Error handling in AskGravya — loading/error/retry/connection-loss gestiti — `AskGravya.tsx:34-39, 86-107`
- ✅ Error handling in GravyaDashboard — PageSkeleton, EmptyState, fallback messages — `GravyaDashboard.tsx:33-70`
- ✅ Nessun dato sensibile nel bundle — no API keys, auth via cookie `credentials: "include"` — `api/client.ts:24`
- ✅ Gravya integrato in navigazione — sidebar link + Command Palette shortcut — `Sidebar.tsx:110-120`
- ✅ Command Palette integration sicura — evento custom `gravya:open-ask` — `CommandPalette.tsx:265`
- ✅ XSS protection — rendering come plain text React JSX — `AskGravya.tsx:202-205`
- ✅ React Query cache isolation — keys includono `selectedCompanyId` — `GravyaDashboard.tsx:34`
- ✅ Polling cleanup — timeout cleared on unmount — `AskGravya.tsx:72, 82-84`

#### WARN
- ⚠️ `askGravyaApi` non esportato da `api/index.ts` — import diretto inconsistente con altri moduli API — `api/index.ts`
- ⚠️ Nessun `queryKeys.gravya` — stringhe hardcoded invece di query key helpers — `GravyaDashboard.tsx:34-58`
- ⚠️ Polling interval fisso a 2s — nessun exponential backoff — `AskGravya.tsx:93`
- ⚠️ Errore polling generico — nessun logging server-side del dettaglio — `AskGravya.tsx:103-104`
- ⚠️ Nessun timeout esplicito su richiesta sync — può bloccarsi indefinitamente — `AskGravya.tsx:11`

#### FAIL
*(nessun FAIL critico rilevato)*

---

### 7. Testing Audit

#### PASS
- ✅ Fixture per dipendenze esterne — `conftest.py` mocka psycopg, langchain, langgraph, PyJWT — `tests/unit/conftest.py:9-34`
- ✅ Unit test usano mock DB — nessuna chiamata DB reale — `test_memory_writer.py:30-43`
- ✅ Memory writer tier routing coperto — tutti i tier (2, 3, 4, 5, multi-tier) — `test_memory_writer.py:36-114`
- ✅ Graph node_load_memory testa tutti e 6 i tier — `test_graph.py:12-47`
- ✅ Rejection codes testati in card_analyzer — `test_card_analyzer.py:30-41`
- ✅ `SKIP_CONFIG_VALIDATION` flag configurato — `config/settings.py:126`
- ✅ LLM calls mockate — `test_card_analyzer.py:117-126`
- ✅ Graceful degradation testata — retrieval ritorna `[]` se DB non disponibile — `test_retrieval.py:18-56`
- ✅ Graph topology verificata — nodi e archi corretti — `test_graph.py:73-94`

#### WARN
- ⚠️ `router.py` zero coverage — funzione `route()` con confidence threshold, rejection, tool loop non testata
- ⚠️ `supervisor_registry` cache invalidation non testata
- ⚠️ `session_logger` outcome status non testato
- ⚠️ `generic_supervisor` pipeline execution non testata — condition evaluation, is_critical, partial_strategy
- ⚠️ `utils/auth.py` JWT verification non testata
- ⚠️ `context_resolver` non testato
- ⚠️ Integration test folder vuota — conftest esiste ma zero test_*.py
- ⚠️ Memory writer error paths non testati
- ⚠️ Classification failure fallback (flags={}) non testato esplicitamente
- ⚠️ `github_pr.py` non testato

#### FAIL
- ❌ `router.py` rejection codes non testati — path `rejected:unclassified` e `rejected:ambiguous` — `router.py:204-215`
- ❌ Router LLM tool loop non testato — max 5 iterazioni, tool execution, message stack — `router.py:166-232`
- ❌ `supervisor_registry` double-check locking non testato — race condition protection — `supervisor_registry.py:54-109`
- ❌ HITL flow end-to-end non testato — `requires_interrupt=True` → `outcome_status="interrupted"` — `graph.py`, `session_logger.py`
- ❌ Import validation mancante — broken module paths non rilevati automaticamente
- ❌ `kloud/tools.py` non testato — query_tasks, query_clients, search_memory_semantic — 6 tools critici
- ❌ No database integration test — integration conftest solo mock, nessun test reale
- ❌ `checkpointer.py` non testato — checkpoint get/put per LangGraph state persistence

**Coverage stimata: ~7%** (4 moduli su 56+ con test diretti)

---

## Fix Prioritizzati

### P0 — Critici (blocca avvio o sicurezza produzione)

| # | Finding | File | Fix |
|---|---|---|---|
| P0-1 | `JWT_ENABLED` default `"false"` | `src/utils/auth.py:38-39` | Cambiare default a `"true"` |
| P0-2 | `/kloud/invoke` senza JWT auth | `src/api.py:401-415` | Aggiungere `Depends(verify_token)` |
| P0-3 | Port mismatch docker-compose/settings | `docker-compose.yml:62` + `settings.py:94` | Verificare uvicorn porta interna = 8001 |
| P0-4 | `EMBEDDINGS_API_KEY` mancante in docker-compose | `docker-compose.yml` agents env | Aggiungere env var |
| P0-5 | Trigger RETURN NEW su DELETE | `migration 0052` gravya_bump_supervisor_version() | `RETURN COALESCE(NEW, OLD)` |

### P1 — Warning (degrada affidabilità)

| # | Finding | File | Fix |
|---|---|---|---|
| P1-1 | `task_flags` non nel supervisor_input | `src/kloud/graph.py` node_run_supervisor | Aggiungere `"task_flags": {}` al dict |
| P1-2 | `agent_registry` orphans | Migration 0051 + `gravya_supervisors` | Aggiungere content-strategist e creative-director a gravya_supervisors o rimuovere da agent_registry |
| P1-3 | `meta_ads_supervisor.py` import rotto | `src/supervisors/meta_ads_supervisor.py` | Rimuovere file (dead code) |
| P1-4 | Rejection code generico su classification failure | `src/supervisors/generic_supervisor.py` | Usare `rejected:classification_failed` |
| P1-5 | `HITL_WEBHOOK_SECRET` non validato all'avvio | `config/settings.py` | Aggiungere alla validation di prod |
| P1-6 | `supabase_client.py` potenzialmente legacy | `src/utils/supabase_client.py` | Verificare usi e rimuovere se non usato |

### P2 — Miglioramenti (non urgenti)

| # | Finding | File | Fix |
|---|---|---|---|
| P2-1 | IVFFlat probes non impostati | `src/pipelines/retrieval.py` | Aggiungere `SET LOCAL ivfflat.probes = 10` |
| P2-2 | CORS `allow_origins=["*"]` | `src/api.py` | Limitare agli origin Paperclip in prod |
| P2-3 | No rate limiting su /invoke | `src/api.py` | Aggiungere slowapi o fastapi-limiter |
| P2-4 | Test coverage critica — router, registry, HITL | `tests/unit/` | Aggiungere test_router.py, test_supervisor_registry.py, test_hitl_flow.py |
| P2-5 | Integration test DB mancante | `tests/integration/` | Aggiungere pytest fixture con testcontainers |
| P2-6 | Polling senza exponential backoff | `ui/src/AskGravya.tsx:93` | Aggiungere backoff |
| P2-7 | `askGravyaApi` non in barrel export | `ui/src/api/index.ts` | Aggiungere export |
