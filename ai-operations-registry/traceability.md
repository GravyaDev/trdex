# Matrice Tracciabilità

> Ultimo aggiornamento: {{DATE}}

## Dove si registra ogni tipo di evento

<!-- Una riga per tipo di evento. Se non hai una tabella DB, indica file di log o "non tracciato". -->

| Evento | Dove | Campi chiave | Chi logga | Retention |
|---|---|---|---|---|
| Decisione routing | {{tabella/file}} | {{campi}} | {{componente}} | {{retention}} |
| Sessione AI completa | {{tabella/file}} | {{campi}} | {{componente}} | {{retention}} |
| Costo LLM | {{tabella/file}} | {{campi}} | {{componente}} | {{retention}} |
| Azione utente | {{tabella/file}} | {{campi}} | {{componente}} | {{retention}} |
| Errore/anomalia | {{tabella/file}} | {{campi}} | {{componente}} | {{retention}} |

## Flow tracciabilità

```mermaid
flowchart LR
    subgraph INPUT["📥 INPUT"]
        U["Utente/Sistema"]
    end
    
    subgraph PROCESSING["⚙️ PROCESSING"]
        O["Orchestrator"]
        A["Agente"]
    end
    
    subgraph LOGGING["📋 LOGGING"]
        L1["{{log_1}}"]
        L2["{{log_2}}"]
    end
    
    U --> O
    O --> A
    O -->|"decisione"| L1
    A -->|"risultato"| L2
    
    style INPUT fill:#e3f2fd
    style PROCESSING fill:#fff3e0
    style LOGGING fill:#e8f5e9
```
