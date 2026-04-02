# /deep-audit

Audit architetturale completo multi-agente del progetto gravya-platform.
Team di 6 analisti specializzati Gravya. Produce report PASS/WARN/FAIL.
Metodologia riproducibile — eseguire periodicamente o dopo refactoring maggiori.

## Trigger
- Invocazione esplicita: `/deep-audit`
- Raccomandato dopo: refactoring architetturali, merge da upstream, nuove integrazioni esterne
- Frequenza suggerita: mensile o ogni 5+ sessioni di sviluppo intenso

---

## Fase 1 — Snapshot codebase

Usare un agente Explore per mappare la struttura corrente:

```
Agent(Explore): Mappa tutti i file .py sotto services/agents/src/, tutti i file .ts/.tsx
sotto ui/src/ (pagine Gravya), lista migration SQL, lista file docker-compose*.
Non leggere contenuti — solo struttura. Restituire conteggio per categoria.
```

---

## Fase 2 — Lancio 6 analisti in parallelo

Lanciare TUTTI in un singolo messaggio (parallel tool calls).
Ogni analista riceve: path esatti dei file da leggere, criteri di valutazione, formato output.

Formato output per ogni analista:
```
## [Nome Analista]
### PASS
- [criterio]: [evidenza]
### WARN
- [criterio]: [problema] → [suggerimento]
### FAIL
- [criterio]: [problema critico] → [fix richiesto]
```

---

### Analista 1 — Schema Analyst

**Scope**: Integrità schema PostgreSQL, migration, journal, indici, FK, coerenza gravya_* vs Paperclip, pgvector, sistema memoria 6-tier.

**File da leggere**:
- `app/packages/db/src/migrations/0047` → ultimo (tutti)
- `app/packages/db/src/migrations/meta/_journal.json`
- `app/packages/db/src/schema/` (file gravya_*.ts)
- `app/scripts/seed-gravya-dev.sql`
- `app/scripts/seed-gravya-prod.sql`

**Criteri**:
1. Journal completo — ogni .sql ha entry corrispondente con idx progressivo
2. Nessuna migration Gravya altera tabelle Paperclip (solo ADD TABLE / ALTER su gravya_*)
3. FK constraints corretti — references a tabelle esistenti, ON DELETE semanticamente appropriato
4. Indici presenti su colonne usate in query critiche (agent_id, client_id, supervisor_id)
5. Seed data idempotenti (ON CONFLICT DO NOTHING o DO UPDATE)
6. Drizzle schema files coerenti con migration SQL (nessuna tabella definita in schema ma non in migration)
7. Trigger gravya_bump_supervisor_version() — referenzia colonne esistenti, RETURN COALESCE(NEW, OLD) su DELETE
8. pgvector: HNSW index presente (non IVFFlat), dimensioni coerenti con Voyage AI (1024d)
9. Memory 6-tier: tabelle session_logs, entity_facts, pinned_docs, agent_memory — esistono e hanno indici corretti
10. Seed DDL-only in migration, dati in seed scripts separati — nessun INSERT in migration post-0052

---

### Analista 2 — Python/AI Analyst

**Scope**: Qualità codice Python, LangGraph graph, supervisors/executors dinamici, memoria 6-tier, importlib whitelist, async correctness, LiteLLM integration, HITL flow.

**File da leggere**:
- `services/agents/src/api.py`
- `services/agents/src/kloud/graph.py`
- `services/agents/src/kloud/router.py`
- `services/agents/src/kloud/supervisor_registry.py`
- `services/agents/src/kloud/kloud_config.py`
- `services/agents/src/kloud/memory_writer.py`
- `services/agents/src/kloud/context_resolver.py`
- `services/agents/src/supervisors/generic_supervisor.py`
- `services/agents/src/supervisors/base_supervisor.py`
- `services/agents/src/executors/generic_executor.py`
- `services/agents/src/executors/base_executor.py`
- `services/agents/src/tools/llm_client.py`
- `services/agents/src/pipelines/retrieval.py`
- `services/agents/src/utils/db.py`
- `services/agents/src/utils/embeddings_client.py`
- `services/agents/src/utils/auth.py`
- `services/agents/config/settings.py`

**Criteri**:
1. Nessun import rotto (path inesistenti, riferimenti a moduli rinominati)
2. Dead code identificato — file `meta_ads_supervisor.py`, `content_supervisor.py`, `admin_supervisor.py` se ancora esistono
3. Async/await corretto — nessuna chiamata sync in contesto async (specialmente DB e LLM)
4. Error handling: ogni LLM call ha try/except con fallback o re-raise esplicito
5. Nessun secret hardcoded
6. SupervisorState TypedDict include tutti i campi usati (incluso `task_flags`)
7. `supervisor_input` in graph.py include `task_flags: {}`
8. Nessun `from ..memory.retrieval` residuo (vecchio path)
9. `llm_invoke_with_tools` importato correttamente in router.py
10. LangGraph: CompiledGraph costruito da DB config (non hardcoded), cachato in-memory, invalidato su schema_version bump
11. importlib whitelist: `_ALLOWED_MODULE_PREFIXES` copre tutti i path legittimi, nessun bypass
12. Memory writer: nessuna scrittura diretta da supervisor/executor (solo segnali → evaluate_and_write)
13. KloudConfig: TTL cache funzionante, fallback a settings.py se DB irraggiungibile
14. Fallback LLM: `fallback_llm_model` presente su supervisors e executors, usato in llm_invoke
15. Pipeline classification: `classify_task` fallisce gracefully (empty flags → tutti step "always" eseguiti)

---

### Analista 3 — Infrastructure Analyst

**Scope**: Docker, porte, env vars, integrazione Paperclip, healthcheck, deploy.

**File da leggere**:
- `app/docker-compose.yml`
- `app/docker-compose.quickstart.yml`
- `app/services/agents/Dockerfile`
- `app/.env.example`
- `services/agents/config/settings.py`
- `app/server/src/index.ts` (main entry)
- `app/server/src/startup-banner.ts`

**Criteri**:
1. Port mapping coerente — internal port in Dockerfile/uvicorn == external mapping in compose
2. Tutti gli env var usati nel codice sono in .env.example
3. Healthcheck configurato per agents service in docker-compose
4. Database URL consistente tra agents e server
5. JWT secret condiviso: PAPERCLIP_AGENT_JWT_SECRET (server) ↔ PAPERCLIP_AGENT_TOKEN (agents)
6. Volume mounts corretti — nessun path Windows-specific in docker-compose
7. CORS_ORIGINS configurato (non wildcard `*` in prod)
8. OfficeCLI binary: `scripts/setup_officecli.sh` eseguito in Dockerfile, binary path corretto
9. EMBEDDINGS_API_KEY / VOYAGE_API_KEY mappato in compose
10. Nessun service dipende da agents via hostname hardcoded (deve passare da gateway)

---

### Analista 4 — Security Analyst

**Scope**: Auth, JWT, input validation, API keys, injection risks, importlib, LLM guard, rate limiting.

**File da leggere**:
- `services/agents/src/utils/auth.py`
- `services/agents/src/utils/llm_guard.py` (se esiste)
- `services/agents/src/api.py`
- `services/agents/src/executors/generic_executor.py`
- `services/agents/config/settings.py`
- `services/agents/src/kloud/router.py`
- `services/agents/src/tools/office/office_tool.py`

**Criteri**:
1. JWT verification — algoritmo HS256, exp check, secret match con Paperclip
2. Ogni endpoint autenticato (nessun endpoint pubblico non-intenzionale; /health è OK)
3. Input sanitization — task input validato prima di passare all'LLM
4. importlib whitelist — `_ALLOWED_MODULE_PREFIXES` copre solo `src.tools.`, nessun bypass via `..` o relative import
5. Nessun secret in codice, log, o response body
6. SQL — nessuna query con f-string o concatenazione (solo parametrizzate $1, $2)
7. KLOUD_INVOKE_SECRET validato su `/kloud/invoke`
8. HITL_WEBHOOK_SECRET validato all'avvio in prod
9. Rate limiting attivo su endpoint critici (/invoke, /run, /run/async)
10. OfficeCLI: file_path validation (no traversal, extension whitelist)
11. LLM guard: prompt injection mitigation (se presente — WARN se assente)

---

### Analista 5 — Architecture Analyst

**Scope**: Isolamento failure, SPOF, coerenza architetturale, modularità, backward compat, SOLID.

**File da leggere**:
- `services/agents/src/kloud/graph.py`
- `services/agents/src/kloud/supervisor_registry.py`
- `services/agents/src/kloud/kloud_config.py`
- `services/agents/src/supervisors/generic_supervisor.py`
- `services/agents/src/executors/generic_executor.py`
- `services/agents/src/api.py`
- `services/agents/src/kloud/types.py`
- `services/agents/src/supervisors/base_supervisor.py`

**Criteri**:
1. Failure isolation — crash di un supervisor non blocca altri supervisori
2. Cache failure — errore nel build supervisor (DB irraggiungibile) non crasha il processo
3. SPOF — LLM provider unico? Fallback chain configurata? (fallback_llm_model)
4. State leaks — SupervisorState non condivide riferimenti mutabili tra invocazioni
5. Async concurrency — asyncio.Lock su supervisor build (double-check locking) corretto
6. Pipeline condition evaluation — fallback safe quando classify_task fallisce (flags={})
7. agent_registry coerenza — supervisori registrati in agent_registry ma non in gravya_supervisors
8. Memory writer — nessuna scrittura diretta da supervisor/executor (solo segnali)
9. Backward compat — initialize_supervisors() è no-op, get_supervisor() shim funziona
10. KloudConfig — separazione config Kloud orchestrator vs config singoli supervisors
11. Nessun accoppiamento tra supervisors (uno non importa codice di un altro)
12. HITL gate: interrupt_check è post-supervisor, non duplicato dentro supervisor

---

### Analista 6 — Frontend Analyst

**Scope**: Pagine Gravya nel frontend Paperclip, integrazione API, UX, errori gestiti, Soketi realtime.

**File da leggere**:
- `app/ui/src/` (cerca tutti i file con "Gravya" o "gravya" nel nome/path)
- `app/ui/src/api/` (cerca file gravya, agents, askGravya)
- `app/ui/src/lib/queryKeys.ts`

**Criteri**:
1. Pagine Gravya usano lo stesso pattern routing/auth di Paperclip
2. Chiamate API a agents service — URL configurato da env, non hardcoded
3. Nessun dato sensibile esposto nel bundle frontend
4. Error states gestiti (loading, error, empty) su ogni pagina Gravya
5. Soketi integration — subscription ai canali corretti per real-time updates
6. queryKeys: tutte le query Gravya usano `queryKeys.gravya.*` (no hardcoded strings)
7. AskGravya: exponential backoff su polling, timeout configurato
8. TanStack Query: staleTime/gcTime configurati ragionevolmente (non default infinito)
9. Nessuna logica business nel frontend (solo presentazione + API calls)

---

## Fase 3 — Compilazione report

Aggregare tutti i risultati in:
```
.claude/reports/deep-audit-MMDDYY.md
```

Struttura report:
```markdown
# Deep Audit — gravya-platform — MMDDYY

## Executive Summary

| Analista | PASS | WARN | FAIL |
|---|---|---|---|
| Schema | X | Y | Z |
| Python/AI | ... | ... | ... |
| Infrastructure | ... | ... | ... |
| Security | ... | ... | ... |
| Architecture | ... | ... | ... |
| Frontend | ... | ... | ... |
| **TOTALE** | ... | ... | ... |

## Findings per analista
[Sezione per ogni analista con dettagli PASS/WARN/FAIL]

## Fix prioritizzati
### P0 — Critici (blocca avvio o correttezza)
### P1 — Warning (degrada affidabilità)
### P2 — Miglioramenti (non urgenti)

## Confronto con audit precedente
[Delta: nuovi FAIL, WARN→PASS, regressioni]
```

---

## Fase 4 — Aggiornamento sistema

Al completamento:
- P0 fix → Task Board "Priority Fix"
- P1 fix → Task Board "This Week"
- P2 fix → Backlog
- Aggiornare `memory.md` con stato audit
- Nominare eventuali learnings a `knowledge-nominations.md`
- Se FAIL count > 3: raccomandare di NON procedere con feature work fino a fix
