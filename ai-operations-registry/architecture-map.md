# Architettura Operativa AI

> Ultimo aggiornamento: {{DATE}}

## Mappa mentale

<!-- Adatta il diagramma al tuo progetto. Questa è una struttura di partenza. -->

```mermaid
mindmap
  root(({{PROJECT_NAME}}))
    👤 <br> PARTNER UMANI
      {{HUMAN_1}} <br> {{ROLE_1}}
      {{HUMAN_2}} <br> {{ROLE_2}}
    🤖 <br> AI ORCHESTRATOR
      Orchestrazione
      Memoria
      Agenti specializzati
    🏗️ <br> INFRASTRUTTURA
      Backend <br> {{BACKEND_STACK}}
      Storage <br> {{DB_STACK}}
    🛡️ <br> GOVERNANCE
      HITL <br> Guardrails
      Traceability <br> Audit Logs
```

## Albero gerarchico agenti

<!-- Compila con i tuoi agenti, supervisori, executori, tool. -->
<!-- Pattern: ogni agente ha Responsabilità, Autonomia, Limiti, Tracciabilità. -->

```
{{PROJECT_NAME}} OPERATIONS
│
├── 👤 {{HUMAN_1}} (Partner Umano)
│   ├── Responsabilità: {{...}}
│   └── Ambito HITL: Può promuovere processi da full_manual → full_auto
│
├── 🤖 AI ORCHESTRATOR
│   ├── Config: {{dove è configurato — file, DB, etc.}}
│   ├── Modello LLM: {{modello default + fallback}}
│   ├── Responsabilità:
│   │   ├── Routing task → agente corretto
│   │   ├── Caricamento contesto
│   │   ├── Applicazione protocollo HITL
│   │   └── Logging sessioni e costi
│   │
│   ├── 🔧 AGENTI SPECIALIZZATI
│   │   ├── {{agent_1}} — {{descrizione}}
│   │   ├── {{agent_2}} — {{descrizione}}
│   │   └── ...
│   │
│   └── 🛠️ TOOLS
│       ├── {{tool_1}} — {{descrizione}}
│       └── ...
│
└── 🏗️ INFRASTRUTTURA
    ├── {{layer_1}} — {{stack}}
    └── {{layer_2}} — {{stack}}
```
