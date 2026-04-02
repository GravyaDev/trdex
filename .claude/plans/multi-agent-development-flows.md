# Piano: `/implement` — Multi-Agent Development Flows (Template Kloudify)

## Status: APPROVATO — implementare dopo Meta Ads validation (Fase 2 roadmap)

---

## Filosofia

`/implement` è un **comando generico Kloudify**, non specifico per Gravya.
Funziona su qualsiasi progetto che abbia un `CLAUDE.md`.

Il comando non contiene assunzioni su stack, linguaggio o architettura.
Al primo uso su un progetto, esegue una **pre-analisi architetturale** che produce
un **Project Implementation Profile**. Da quel momento, ogni invocazione di `/implement`
usa il profilo per configurare ruoli, prompt e confini.

---

## Architettura del comando

```
/implement <descrizione feature>
     │
     ▼
┌─────────────────────────────┐
│ Step 0: Profile Check       │  ← Esiste .claude/implement-profile.md?
│   No  → Step 0b: Generate   │     Pre-analisi architetturale
│   Sì  → Step 1: Classify    │     Leggi profilo e procedi
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│ Step 1: Classify feature    │  ← Quale tipo? Quali layer coinvolti?
│   → single-layer            │
│   → cross-layer             │
│   → db-only                 │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│ Step 2: Architecture Design │  ← Agent: Architect (profilo-aware)
│   → Piano implementativo    │
│   → Contratto inter-layer   │
│   → User approva            │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│ Step 3: Schema (se serve)   │  ← Agent: Schema Dev
│   → Migration DDL-only      │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│ Step 4: Implementation      │  ← Agent(s): Layer Dev (1 per layer)
│   → Parallelo se cross-layer│     Prompt compilato dal profilo
│   → Sequenziale se single   │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│ Step 5: Review              │  ← Agent: Reviewer (criteri dal profilo)
│   → block / warn / info     │
│   → Se block → torna Step 4 │
└─────────────────────────────┘
     │
     ▼
┌─────────────────────────────┐
│ Step 6: Integrazione        │  ← Syntax check, Task Board, commit offer
└─────────────────────────────┘
```

---

## Step 0b: Project Implementation Profile

Questo step gira solo alla prima invocazione, o quando l'utente chiede `/implement --reprofile`.

### Input

Il comando legge (in parallelo):
- `CLAUDE.md` (o `.claude/memory.md` se CLAUDE.md non è informativo)
- Struttura cartelle (1 livello di profondità per ogni root significativa)
- `package.json`, `requirements.txt`, `Cargo.toml`, `go.mod` — qualsiasi dependency manifest presente
- `docker-compose*.yml` se esiste

### Output: `.claude/implement-profile.md`

```markdown
# Project Implementation Profile
# Auto-generato da /implement — modificabile dall'utente

## Progetto
nome: <nome progetto>
descrizione: <1 riga>

## Layer

### <layer-name>
- path: <root path relativo>
- language: <python|typescript|go|rust|...>
- framework: <fastapi|express|next|...>
- stack_summary: <1 riga con framework + ORM + runtime>
- test_command: <comando per eseguire i test>
- boundaries: <cosa NON tocca — path degli altri layer>

### <layer-name-2>
...

## Schema
- orm: <drizzle|prisma|alembic|sqlx|none>
- migration_path: <path relativo>
- migration_pattern: <DDL-only + seed separato | all-in-one | ORM-managed>

## Convenzioni
- commit_style: <conventional|free|co-authored>
- branch_strategy: <feature-branch|trunk|...>
- review_criteri_custom:
  - <criterio 1 specifico del progetto>
  - <criterio 2>
  ...

## Ruoli attivi
# Lista dei ruoli che /implement deve attivare per questo progetto.
# Ogni ruolo corrisponde a un agente con prompt compilato.
- architect
- schema-dev        # solo se sezione Schema è presente
- layer-dev:<layer-name>
- layer-dev:<layer-name-2>
- reviewer
```

### Esempio concreto — Gravya

```markdown
## Layer

### node-server
- path: app/server/
- language: typescript
- framework: Express.js (Paperclip fork) + Drizzle ORM
- stack_summary: Express.js, Drizzle, BetterAuth, TanStack Query (frontend app/ui/)
- test_command: cd app && pnpm test:run
- boundaries: NON tocca app/services/agents/

### python-ai
- path: app/services/agents/
- language: python
- framework: FastAPI + LangGraph + LiteLLM
- stack_summary: FastAPI, LangGraph, LiteLLM, Voyage AI, supervisors/executors dinamici, memoria 6-tier
- test_command: cd app/services/agents && make test
- boundaries: NON tocca app/server/, app/ui/

### frontend
- path: app/ui/
- language: typescript
- framework: React 19 SPA (Vite) + TanStack Query + Tailwind
- stack_summary: React 19, Vite, TanStack Query, Tailwind CSS, queryKeys centralizzati
- test_command: cd app/ui && pnpm test
- boundaries: NON tocca app/server/src/, app/services/

## Schema
- orm: drizzle
- migration_path: app/packages/db/src/migrations/
- migration_pattern: DDL-only + seed in app/scripts/seed-gravya-*.sql

## Ruoli attivi
- architect
- schema-dev
- layer-dev:node-server
- layer-dev:python-ai
- layer-dev:frontend
- reviewer
```

---

## Template prompt agenti

I prompt sono **template con slot** compilati dal profilo. Non contengono nomi di progetto, framework o pattern hardcoded.

### Architect

```
Sei l'architetto del progetto. Conosci i seguenti layer:

{{#each profile.layers}}
- **{{name}}** ({{language}}/{{framework}}): {{stack_summary}}
  Path: {{path}}
{{/each}}

Schema: {{profile.schema.orm}} in {{profile.schema.migration_path}}

Analizza la feature richiesta e produci:
1. Impatto architetturale — quali layer coinvolti, file stimati
2. Contratto inter-layer — se cross-layer, definisci endpoint/schema condivisi
3. Rischi e dipendenze
4. Piano step-by-step

Non scrivere codice. Solo design.
```

### Layer Dev (uno per layer)

```
Sei lo sviluppatore del layer **{{layer.name}}**.

Stack: {{layer.stack_summary}}
Path: {{layer.path}}
Linguaggio: {{layer.language}}

CONFINI: {{layer.boundaries}}
Se la feature richiede interazione con altri layer, esponi/consuma
l'interfaccia definita nel piano architetturale — NON importare codice
da fuori il tuo path.

Segui le convenzioni del progetto:
{{#each profile.convenzioni.review_criteri_custom}}
- {{this}}
{{/each}}
```

### Schema Dev

```
Gestisci lo schema del database.

ORM: {{profile.schema.orm}}
Migration path: {{profile.schema.migration_path}}
Pattern: {{profile.schema.migration_pattern}}

Produci migration che rispettano il pattern del progetto.
Non inserisci dati di seed nella migration (a meno che migration_pattern = all-in-one).
Verifica FK, indici, naming coerente con tabelle esistenti.
```

### Reviewer

```
Sei il code reviewer del progetto. Checklist:

Universali:
- Security: no secrets in code/logs, query parametrizzate, auth su endpoint
- Async: no sync in async context (se layer async)
- Error handling: try/except o try/catch su chiamate esterne, fallback
- Architecture: failure isolation, no state leaks, no accoppiamento tra layer

Specifici progetto:
{{#each profile.convenzioni.review_criteri_custom}}
- {{this}}
{{/each}}

Coerenza con piano:
- Il codice implementato corrisponde al piano architetturale approvato in Step 2?
- Il contratto inter-layer è rispettato?
```

---

## Classificazione feature (Step 1)

Il comando analizza la descrizione e i layer coinvolti:

| Tipo | Condizione | Layer Dev attivati |
|---|---|---|
| `single-layer` | Feature tocca 1 solo layer | 1 agente |
| `cross-layer` | Feature tocca 2+ layer | N agenti (parallelo) |
| `db-only` | Solo schema change | Schema Dev + Reviewer |

Se ambiguo → chiedi all'utente.

---

## Comunicazione inter-agente

### Default (subagent standard)
- File-based: piano scritto in `Scratchpad.md`, letto dagli agenti
- Nessuna comunicazione diretta tra agenti
- Contratto API definito dall'Architect, rispettato da tutti

### Upgrade futuro (claude-peers-mcp)
- Se installato: comunicazione real-time tra agenti
- Particolarmente utile per cross-layer: "quale formato JSON ti aspetti?"
- Vedi: parcheggio in Task Board (Fase 4)

---

## Posizione in roadmap

```
Timeline Gravya:
  ✅ Fase 1 — Foundation Dinamica
  ⬜ Fase 2 — Meta Ads tool validation (in corso)
  ⬜ Fase 3 — Dashboard CRUD API + frontend

  ──── /implement disponibile da qui ────

  ⬜ Fase 4 — Google Ads, Email Marketing (primo uso reale)
  ⬜ Fase 5 — Supervisore di Cliente
  ⬜ Fase 6 — Council of AI Elders
```

Timeline Kloudify:
  - Comando implementato: prima di Fase 4
  - Profilo Gravya generato: automatico al primo uso
  - Committato in repo Kloudify: dopo test su Gravya + 1 progetto diverso
  - claude-peers-mcp: valutare per Fase 4

**Effort:**
- `.claude/commands/implement.md` — 1 sessione
- Test su Gravya (Google Ads come feature reale) — 1 sessione
- Test su progetto diverso (validazione agnosticità) — 1 sessione
- Raffinamento + commit Kloudify — 0.5 sessione

---

## File prodotti dal comando

| File | Persistenza | Scopo |
|---|---|---|
| `.claude/implement-profile.md` | Permanente | Profilo progetto, editabile |
| `Scratchpad.md` | Sessione | Piano architetturale corrente, cleared da /wrap-up |
| Migration `.sql` | Permanente | Schema change |
| Codice sorgente | Permanente | Implementazione |

---

## Differenza da altri comandi

| Comando | Scope | Modifica codice | Quando |
|---|---|---|---|
| `/deep-audit` | Intero progetto | Mai | Periodico, post-refactor |
| `/review` | Changeset/PR | Offre fix | Pre-merge |
| `/implement` | Singola feature | Sì | Per ogni feature nuova |
