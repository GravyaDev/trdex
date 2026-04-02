# Catena Decisionale

> Ultimo aggiornamento: {{DATE}}

## Flow: Richiesta utente → Risultato

<!-- Adatta al flusso del tuo progetto. Questo è un template generico per sistemi AI con HITL. -->

```mermaid
flowchart TD
    A["👤 Utente: richiesta"] --> B["Auth + Validation"]
    B --> C["AI Orchestrator: classifica task"]
    
    C --> D{"Agente identificato?"}
    D -- Sì --> E["Agente: esegui task"]
    D -- No --> F["Risposta diretta / rejection"]
    
    E --> G{"Risultato OK?"}
    G -- Sì --> H{"Richiede HITL?"}
    G -- No, retry --> E
    G -- No, fatal --> I["Errore + log"]
    
    H -- Sì --> J["👤 Umano approva/rifiuta"]
    J --> K["Esegui / Annulla"]
    H -- No --> L["✅ Risposta all'utente"]
    K --> L
    
    style A fill:#e1f5fe
    style L fill:#c8e6c9
    style I fill:#ffcdd2
    style J fill:#fff9c4
```

## Decision Framework

<!-- Ogni decisione autonoma dell'AI segue questo framework. -->

```mermaid
flowchart TD
    A["Decisione da prendere"] --> B["1. Dati disponibili?"]
    B --> C["2. Esiste una regola/direttiva?"]
    C --> D["3. Rischio/beneficio?"]
    D --> E{"Dentro la mia autonomia?"}
    
    E -- Sì --> F["Esegui + Log"]
    E -- No --> G["HITL: chiedi approvazione"]
    G -->|"Approvato"| F
    G -->|"Rifiutato"| H["Annullato + log"]
```
