# Context — Shared State del Dev Team

Questa cartella contiene i file di contesto condiviso tra gli agenti del team.
È il meccanismo di comunicazione tra agenti (non JSON messaging — i subagent sono effimeri).

## File

| File | Scritto da | Letto da | Contenuto |
|------|-----------|---------|-----------|
| `current-feature.md` | task-decomposer | tutti | Feature in corso, task atomici, dipendenze |
| `architecture.md` | backend-architect, database-architect | fullstack-developer, python-ai-developer | Decisioni architetturali della sessione |
| `review-notes.md` | code-reviewer, architect-review | utente, agenti di fix | Note di review accumulate |

## Convenzioni

- I file vengono sovrascritti ad ogni sessione (non sono storici)
- Se un agente trova un file esistente, lo legge per contesto prima di scrivere
- La cartella viene creata automaticamente al primo utilizzo del team
- **Non committare** questi file — aggiungere `context/` al `.gitignore` del progetto
