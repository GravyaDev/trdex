# Design: Architettura Dinamica Supervisor/Executor/Tool

## Status: APPROVED — pronto per implementazione

---

## Contesto

Supervisor, executor e tool devono essere gestibili dalla dashboard (CRUD senza deploy).
Nessun file Python hardcoded per supervisor/executor. Tool = moduli Python deterministici riutilizzabili.

**Constraint fisso**: LangGraph `CompiledGraph` non è serializzabile → costruito a runtime da config DB, cachato in-memory.

---

## Modello architetturale

```
Kloud (global orchestrator)
  └── Supervisor "Marco" (generic shell, DB-configured)
        ├── Executor "Insights Fetcher" → Tool: MetaAdsTool
        ├── Executor "Budget Optimizer" → Tool: MetaAdsTool, BudgetCalcTool
        └── [altri executor...]

Supervisor = generic_supervisor.py legge config DB → costruisce grafo LangGraph
Executor   = generic_executor.py legge config DB → carica tool con importlib
Tool       = modulo Python deterministico (whitelist-validated)
```

---

## Decisioni architetturali

### Q1: Ordine executor nella pipeline
**Opzione A: Lista statica ordinata** (`gravya_supervisor_pipeline.position`)

- Nessun LLM routing a livello di pipeline
- Routing LLM rimane solo Kloud → quale Supervisor
- Campo `is_critical` per ogni step: determina comportamento su errore
- LLM routing aggiunto SOLO quando esiste un caso concreto (YAGNI)

### Q2: State pattern inter-executor
**Opzione C: Hybrid** — messages + executor_outputs + pipeline_metadata

```python
class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]        # audit log completo, tool calls
    executor_outputs: Annotated[dict[str, Any], merge_dict]    # accesso O(1) per supervisor
    pipeline_metadata: Annotated[dict[str, Any], merge_dict]   # timing, token usage
    task: str
    current_executor: str | None
    final_result: str | None
    errors: Annotated[list[str], operator.add]
```

- `messages` = log immutabile per audit e contesto LLM
- `executor_outputs` = projection strutturata per validazione supervisor
- Reducer `merge_dict` (non replace) per branching parallelo sicuro

### Q3: Validazione supervisor
**Validazione deterministica config-based**

Ogni executor dichiara `completeness_status: "complete" | "partial" | "error"`.
Pipeline config ha per ogni step:
- `is_critical: bool` — se True e status=error → blocca
- `partial_strategy: "accept_with_disclaimer" | "escalate_hitl" | "abort"`

Il supervisor non usa LLM per la validazione — legge la config e applica la strategia.
La soglia "parziale accettabile" è una decisione dell'admin, non dell'LLM a runtime.

### Naming/Persona
**Iniezione doppia**: Kloud + supervisor stesso

- `display_name` in `agent_registry` → nel `cards_summary` di Kloud ("sto passando a Marco")
- Stesso `display_name` → iniettato nel system_prompt del supervisor a runtime
- `context_resolver.py` risolve nomi → agent_id (Tier 5 entity graph)
- Edge case: rinomina → fatto Tier 5 `previously_known_as`

---

## DB Schema — Migration 0052

### 5 nuove tabelle (prefisso gravya_)

```sql
-- Supervisor behavior config
CREATE TABLE gravya_supervisors (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id         text        NOT NULL UNIQUE,  -- FK logica a agent_registry
  display_name     text        NOT NULL,          -- "Marco"
  avatar_url       text,
  color            text,                          -- "#3B82F6"
  system_prompt    text        NOT NULL,
  llm_model        text        NOT NULL DEFAULT 'claude-sonnet-4-6',
  temperature      numeric(3,2) NOT NULL DEFAULT 0.3,
  routing_mode     text        NOT NULL DEFAULT 'sequential',
  max_retries      integer     NOT NULL DEFAULT 1,
  validation_criteria jsonb    NOT NULL DEFAULT '[]',
  schema_version   integer     NOT NULL DEFAULT 1,  -- per cache invalidation
  extra_config     jsonb       NOT NULL DEFAULT '{}',
  is_active        boolean     NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Executor behavior config (riutilizzabili tra supervisor)
CREATE TABLE gravya_executors (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  executor_id      text        NOT NULL UNIQUE,   -- "campaign-planner"
  display_name     text        NOT NULL,
  avatar_url       text,
  color            text,
  system_prompt    text        NOT NULL,
  llm_model        text        NOT NULL DEFAULT 'claude-haiku-4-5',
  temperature      numeric(3,2) NOT NULL DEFAULT 0.1,
  max_tokens       integer     NOT NULL DEFAULT 4096,
  output_format    text        NOT NULL DEFAULT 'json',
  output_schema    jsonb       NOT NULL DEFAULT '{}',
  max_retries      integer     NOT NULL DEFAULT 1,
  escalation_strategy text     NOT NULL DEFAULT 'report_error',
  is_active        boolean     NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

-- Tool registry (moduli Python deterministici)
CREATE TABLE gravya_tools (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  tool_id          text        NOT NULL UNIQUE,   -- "meta-ads-client"
  display_name     text        NOT NULL,
  description      text,
  module_path      text        NOT NULL,          -- "src.tools.meta.ads_tool"
  function_name    text        NOT NULL,          -- "MetaAdsClient"
  input_schema     jsonb       NOT NULL DEFAULT '{}',
  output_schema    jsonb       NOT NULL DEFAULT '{}',
  category         text        NOT NULL DEFAULT 'generic',
  is_active        boolean     NOT NULL DEFAULT true,
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- Pipeline ordinata: supervisor → executor (many-to-many con ordine)
CREATE TABLE gravya_supervisor_pipeline (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  supervisor_id    uuid        NOT NULL REFERENCES gravya_supervisors(id) ON DELETE CASCADE,
  executor_id      uuid        NOT NULL REFERENCES gravya_executors(id) ON DELETE RESTRICT,
  position         integer     NOT NULL,             -- 0-based, ORDER BY position
  is_critical      boolean     NOT NULL DEFAULT true, -- blocca se error
  partial_strategy text        NOT NULL DEFAULT 'accept_with_disclaimer',
  condition        text        NOT NULL DEFAULT 'always',
  input_mapping    jsonb       NOT NULL DEFAULT '{}',
  output_key       text,
  is_active        boolean     NOT NULL DEFAULT true,
  UNIQUE (supervisor_id, position),
  UNIQUE (supervisor_id, executor_id)
);

-- Tool assegnati a executor (many-to-many)
CREATE TABLE gravya_executor_tools (
  id               uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
  executor_id      uuid        NOT NULL REFERENCES gravya_executors(id) ON DELETE CASCADE,
  tool_id          uuid        NOT NULL REFERENCES gravya_tools(id) ON DELETE RESTRICT,
  priority         integer     NOT NULL DEFAULT 0,
  config_override  jsonb       NOT NULL DEFAULT '{}',
  is_active        boolean     NOT NULL DEFAULT true,
  UNIQUE (executor_id, tool_id)
);
```

### Trigger schema_version (per cache invalidation automatica)

```sql
CREATE OR REPLACE FUNCTION gravya_bump_supervisor_version()
RETURNS TRIGGER AS $$
BEGIN
  UPDATE gravya_supervisors
  SET schema_version = schema_version + 1, updated_at = now()
  WHERE id = COALESCE(NEW.supervisor_id, OLD.supervisor_id);
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER gravya_pipeline_version_bump
  AFTER INSERT OR UPDATE OR DELETE ON gravya_supervisor_pipeline
  FOR EACH ROW EXECUTE FUNCTION gravya_bump_supervisor_version();
```

### Query di caricamento completo (1 query, 0 round-trip extra)

```sql
SELECT s.*, p.position, p.is_critical, p.partial_strategy,
       e.executor_id, e.display_name AS executor_display_name,
       e.system_prompt AS executor_system_prompt, e.llm_model AS executor_llm_model,
       jsonb_agg(jsonb_build_object(
         'tool_id', t.tool_id, 'module_path', t.module_path,
         'function_name', t.function_name, 'config_override', et.config_override
       ) ORDER BY et.priority) FILTER (WHERE t.id IS NOT NULL) AS tools
FROM gravya_supervisors s
JOIN gravya_supervisor_pipeline p ON p.supervisor_id = s.id AND p.is_active = true
JOIN gravya_executors e ON e.id = p.executor_id AND e.is_active = true
LEFT JOIN gravya_executor_tools et ON et.executor_id = e.id AND et.is_active = true
LEFT JOIN gravya_tools t ON t.id = et.tool_id AND t.is_active = true
WHERE s.agent_id = $1 AND s.is_active = true
GROUP BY s.id, p.id, e.id
ORDER BY p.position ASC;
```

---

## File Python da creare/modificare

### Nuovi file

| File | Scopo |
|---|---|
| `src/supervisors/generic_supervisor.py` | Build grafo LangGraph da config DB |
| `src/executors/generic_executor.py` | Build nodo executor + tool loading importlib |

### File modificati

| File | Modifica |
|---|---|
| `src/kloud/supervisor_registry.py` | Lazy loading + cache + asyncio.Lock + invalidation |
| `src/kloud/graph.py` | `node_run_supervisor`: `get_supervisor()` → `await get_or_build_supervisor()` |
| `src/kloud/router.py` | `load_cards()` legge `display_name` da DB, inietta in cards_summary |
| `src/kloud/context_resolver.py` | Risolve nomi agente → agent_id |

### Sicurezza importlib

```python
_ALLOWED_MODULE_PREFIXES: frozenset[str] = frozenset({
    "src.tools.",
    "src.executors.",
})

def _validate_module_path(module_path: str) -> None:
    if ".." in module_path or module_path.startswith("."):
        raise ToolLoadError(f"Relative path non consentito")
    if not any(module_path.startswith(p) for p in _ALLOWED_MODULE_PREFIXES):
        raise ToolLoadError(f"Module path non autorizzato: {module_path!r}")
    if not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_.]*', module_path):
        raise ToolLoadError(f"Caratteri non validi in module_path")
```

### Cache pattern

```python
# supervisor_registry.py
_cache: dict[str, CacheEntry] = {}
_build_locks: dict[str, asyncio.Lock] = {}

async def get_or_build_supervisor(supervisor_id: str) -> CompiledGraph | None:
    # Fast path: cache hit
    entry = _cache.get(supervisor_id)
    if entry and not await _is_cache_stale(supervisor_id, entry.config_updated_at):
        return entry.graph
    # Slow path: acquisisci lock, double-check, costruisci
    lock = await _get_or_create_lock(supervisor_id)
    async with lock:
        entry = _cache.get(supervisor_id)
        if entry and not await _is_cache_stale(...):
            return entry.graph
        graph, updated_at = await _build_supervisor(supervisor_id)
        _cache[supervisor_id] = CacheEntry(graph, now, updated_at)
        return graph
```

---

## Ordine di implementazione

**Fase 1 — Foundation (prerequisito)**
1. [ ] Migration 0052: 5 tabelle + trigger schema_version
2. [ ] generic_supervisor.py
3. [ ] generic_executor.py
4. [ ] supervisor_registry.py (dynamic)
5. [ ] graph.py: node_run_supervisor → await
6. [ ] router.py: display_name in cards_summary
7. [ ] Seed DB: 3 supervisor + 6 executor esistenti (**script separato**, non nella migration — i seed sono dati environment-specific e non devono essere inclusi in 0052.sql per evitare conflitti con upstream merge)

**Fase 2 — Meta Ads su nuova architettura**
8. [ ] ads_tool.py (Meta Business SDK)
9. [ ] insights_fetcher come executor in DB (non file hardcoded)
10. [ ] Test e2e su architettura dinamica

**Fase 3 — Dashboard CRUD**
11. [ ] API REST supervisor/executor/tool
12. [ ] Frontend schede agent editabili

---

## Tool già implementati (da seedare in gravya_tool_registry)

| tool_id | module_path | function_name | category |
|---|---|---|---|
| `officecli` | `src.tools.office.office_tool` | `OfficeCLITool` | `file_operation` |
| `meta-ads-client` | `src.tools.meta.ads_tool` | `MetaAdsTool` | `api_integration` |
| `plutio` | `src.tools.plutio.plutio_tool` | `PlutioTool` | `api_integration` |
| `google-analytics` | `src.tools.google.analytics_tool` | `GoogleAnalyticsTool` | `api_integration` |

OfficeCLI binary: `data/tools/officecli/officecli[.exe]` — setup via `scripts/setup_officecli.sh` o `.ps1`

---

## Supervisor esistenti da migrare (Fase 1 seed)

| agent_id | display_name | executor_pipeline |
|---|---|---|
| meta-ads | Marco | campaign-planner(0), performance-analyzer(1) |
| content | Sofia | copy-executor(0), social-post-executor(1) |
| admin | (TBD) | invoice-executor(0), doc-executor(1) |

---

## Note importanti

- **Backward compatibility**: `initialize_supervisors()` diventa stub vuoto, `get_supervisor()` rimane per compatibilità ma ritorna da cache (non fa build)
- **Startup**: nessun grafo costruito all'avvio (lazy loading)
- **Errori di build**: isolati per supervisor, non bloccano gli altri
- **Dashboard invalidation**: `POST /api/v1/supervisors/{id}/invalidate` → `invalidate_supervisor(id)`
