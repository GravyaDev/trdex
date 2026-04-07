---
doc_id: kb_index
purpose: |
  Indice delle Knowledge Base per agente.
  NON è un documento condiviso: è solo una mappa per il sistema di routing.
  Ogni agente carica ESCLUSIVAMENTE il proprio file e nessun altro.
---

# Agent Knowledge Base Index

> **Regola**: ogni agente legge SOLO il proprio file. Niente cross-loading.
> Questo INDEX serve solo al routing/loader, non agli agenti stessi.

| Agente | File KB | Ruolo |
|---|---|---|
| **Scout** | [scout.md](scout.md) | Raccolta contesto narrativo (RAG su Qdrant) |
| **Analyst** | [analyst.md](analyst.md) | Calcolo indicatori, signal aggregation, volatility regime |
| **Risk Manager** | [risk_manager.md](risk_manager.md) | Gate sequenziali, position sizing, approve/block |
| **Executor** | [executor.md](executor.md) | Place order via gateway, idempotency, journaling |
| **Stop-Loss Monitor** | [stop_loss_monitor.md](stop_loss_monitor.md) | Background safety net, auto-close, kill switch |

## Convenzioni

Ogni file usa lo stesso schema di blocchi:

- `HARD-*` → regole immutabili (modificabili solo via review umana)
- `PARAM-*` → parametri configurabili via `.env`
- `HEUR-*` → euristiche evolvibili con l'esperienza
- `PROMPT-*` → template di system prompt iniettabili

## Versioning

Ogni file ha:
- `version`: numero di versione semantico
- `last_updated`: data ISO
- `sources`: notebook ID o riferimenti bibliografici

## Evoluzione

I blocchi `HEUR-*` possono evolvere sulla base della memoria storica raccolta in:
- `agent_runs` table (DB)
- `trdex_entity_graph` table (DB)

Le proposte di aggiornamento devono passare per review umana prima di essere applicate.
I blocchi `HARD-*` non sono mai modificabili automaticamente.

## Sorgenti primarie

- **NotebookLM**: `23eff711-d90f-4575-9a2f-5d1244681d9e` (TradingView Guide + Essential Forex Books)
- **Linee guida architetturali**: `Riferimenti/Linee guida trading.md`
