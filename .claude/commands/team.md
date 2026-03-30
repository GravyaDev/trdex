# /team — Dev Team Workflow

Attiva il team di agenti specializzati in `.claude/teams/dev-team/`.

## Utilizzo

```
/team decompose [feature]    → task-decomposer: scompone la feature in task atomici
/team architect [feature]    → backend-architect + database-architect: progetta la soluzione
/team review                 → code-reviewer + architect-review: revisione del codice
/team build [feature]        → workflow completo: decompose → architect → build → review
/team python [feature]       → python-ai-developer: implementa componenti AI/Python
```

## Setup (una tantum per progetto)

Prima di usare il team su un nuovo progetto, compila:
```
{progetto}/.claude/teams/dev-team/PROJECT_CONTEXT.md
```

Copia il template da `.claude/teams/dev-team/PROJECT_CONTEXT.md` e compila tutte le sezioni.

---

## Procedure

### `/team decompose [feature]`

1. Invoca l'agente `task-decomposer` con il task descritto
2. L'agente legge `PROJECT_CONTEXT.md` e scompone la feature in task atomici con dipendenze
3. Output scritto in `.claude/teams/dev-team/context/current-feature.md`
4. Presenta il task breakdown all'utente per approvazione prima di procedere

### `/team architect [feature]`

1. Leggi `.claude/teams/dev-team/context/current-feature.md` se esiste
2. Invoca `backend-architect` per il design API/servizi
3. Invoca `database-architect` per schema e migration strategy
4. Entrambi scrivono in `.claude/teams/dev-team/context/architecture.md`
5. Presenta il design per approvazione

### `/team review`

1. Leggi `.claude/teams/dev-team/context/architecture.md` se esiste (contesto)
2. Identifica i file modificati (chiedi all'utente se non specificato, o usa git diff)
3. Invoca `code-reviewer` → scrive in `.claude/teams/dev-team/context/review-notes.md`
4. Invoca `architect-review` per SOLID/boundaries
5. Presenta findings aggregati con severity 🔴/🟡/🟢

### `/team build [feature]`

Workflow completo in sequenza:

1. **Decompose** — esegui `/team decompose [feature]`
2. **Architect** — presenta il task breakdown, poi esegui `/team architect [feature]`
3. **Build** — scegli l'agente giusto:
   - TypeScript/React/Express → `fullstack-developer`
   - Python/LangGraph/FastAPI → `python-ai-developer`
   - Cross-stack → entrambi in sequenza (DB → backend → frontend)
4. **Review** — esegui `/team review` sull'implementazione

### `/team python [feature]`

1. Leggi `context/current-feature.md` e `context/architecture.md` se esistono
2. Invoca `python-ai-developer` con il task
3. L'agente legge `PROJECT_CONTEXT.md` → sezione AI Layer per contesto specifico

---

## File di contesto condiviso

Gli agenti comunicano tramite file in `.claude/teams/dev-team/context/`:

| File | Scritto da | Letto da |
|------|-----------|---------|
| `current-feature.md` | task-decomposer | tutti gli altri agenti |
| `architecture.md` | backend-architect, database-architect | fullstack-developer, python-ai-developer, architect-review |
| `review-notes.md` | code-reviewer | architect-review (per continuità) |

Vedi `.claude/teams/dev-team/context/README.md` per le convenzioni complete.

---

## Note

- Ogni agente legge `PROJECT_CONTEXT.md` come prima azione — non serve ripetere il contesto manualmente
- Per usare il team su un altro progetto: copia `.claude/teams/dev-team/` nella root del progetto e compila `PROJECT_CONTEXT.md`
- La directory `context/` contiene stato temporaneo della sessione di lavoro corrente — può essere svuotata tra feature diverse
