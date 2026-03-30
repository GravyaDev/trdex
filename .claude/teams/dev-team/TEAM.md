# Dev Team — Modulo Claudify

Team di agenti specializzati per sviluppo software. Riutilizzabile su qualsiasi progetto.

## Come funziona

Il team è **agnostico dell'architettura**. Il contesto specifico del progetto viene iniettato tramite `PROJECT_CONTEXT.md` — ogni agente lo legge come prima azione.

Non esiste comunicazione JSON tra agenti (i subagent sono effimeri in Claude Code). La comunicazione avviene via file nella cartella `context/`.

---

## Setup per un nuovo progetto

1. Copia `PROJECT_CONTEXT.md` nella cartella `.claude/teams/dev-team/` del tuo progetto
2. Compilalo con lo stack e le convenzioni del progetto
3. Invoca gli agenti o usa i comandi `/team`

```
{progetto}/
  .claude/
    teams/
      dev-team/
        PROJECT_CONTEXT.md    ← compilato per questo progetto
        context/              ← shared context tra agenti (auto-creata)
```

---

## Agenti disponibili

| Agente | Ruolo | Quando usarlo |
|--------|-------|---------------|
| `task-decomposer` | Decompone feature in task atomici | Prima di iniziare una feature |
| `backend-architect` | Design API, architettura, DDD | Quando serve decidere struttura |
| `database-architect` | Schema DB, migrations, indexing | Quando serve modificare il DB |
| `code-reviewer` | Review security/performance/patterns | Prima di ogni merge |
| `architect-review` | SOLID, boundaries, abstractions | Per review architetturale |
| `python-ai-developer` | Python/LangGraph/LiteLLM/AI | Per il layer AI del progetto |
| `fullstack-developer` | Express/React/Node full-stack | Per feature applicative |

---

## Workflow consigliati

### Feature Node.js/full-stack
1. `task-decomposer` → decompone
2. `backend-architect` → design API (se serve)
3. `database-architect` → schema changes (se serve)
4. `fullstack-developer` → implementa
5. `code-reviewer` + `architect-review` → review

### Feature AI/Python
1. `task-decomposer` → decompone
2. `backend-architect` → design contratto API (se cross-stack)
3. `python-ai-developer` → implementa
4. `code-reviewer` → review

### Feature cross-stack
1. `task-decomposer` → decompone, identifica layer
2. `backend-architect` → contratto API Express ↔ FastAPI
3. `fullstack-developer` → parte Node.js
4. `python-ai-developer` → parte Python
5. `code-reviewer` + `architect-review` → review integrata

---

## Comunicazione tra agenti (file-based)

```
context/
  current-feature.md    — task-decomposer scrive, altri leggono
  architecture.md       — backend-architect e database-architect scrivono
  review-notes.md       — code-reviewer e architect-review scrivono
```

Gli agenti leggono questi file all'avvio se presenti, per avere contesto della sessione in corso.

---

## Comandi rapidi

```
/team decompose [feature]   — task-decomposer
/team architect [feature]   — backend-architect + database-architect
/team review                — code-reviewer + architect-review
/team build [feature]       — workflow completo
```
