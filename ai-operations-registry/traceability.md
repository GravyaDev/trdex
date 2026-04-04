# Traceability Matrix

> Last updated: {{DATE}}

## Where each event type is logged

<!-- One row per event type. If you don't have a DB table, indicate log file or "not tracked". -->

| Event | Where | Key fields | Logged by | Retention |
|---|---|---|---|---|
| Routing decision | {{table/file}} | {{fields}} | {{component}} | {{retention}} |
| Complete AI session | {{table/file}} | {{fields}} | {{component}} | {{retention}} |
| LLM cost | {{table/file}} | {{fields}} | {{component}} | {{retention}} |
| User action | {{table/file}} | {{fields}} | {{component}} | {{retention}} |
| Error/anomaly | {{table/file}} | {{fields}} | {{component}} | {{retention}} |

## Traceability flow

```mermaid
flowchart LR
    subgraph INPUT["📥 INPUT"]
        U["User/System"]
    end
    
    subgraph PROCESSING["⚙️ PROCESSING"]
        O["Orchestrator"]
        A["Agent"]
    end
    
    subgraph LOGGING["📋 LOGGING"]
        L1["{{log_1}}"]
        L2["{{log_2}}"]
    end
    
    U --> O
    O --> A
    O -->|"decision"| L1
    A -->|"result"| L2
    
    style INPUT fill:#e3f2fd
    style PROCESSING fill:#fff3e0
    style LOGGING fill:#e8f5e9
```
