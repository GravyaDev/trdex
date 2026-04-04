# Decision Chain

> Last updated: {{DATE}}

## Flow: User request → Result

<!-- Adapt to your project's flow. This is a generic template for AI systems with HITL. -->

```mermaid
flowchart TD
    A["👤 User: request"] --> B["Auth + Validation"]
    B --> C["AI Orchestrator: classify task"]
    
    C --> D{"Agent identified?"}
    D -- Yes --> E["Agent: execute task"]
    D -- No --> F["Direct response / rejection"]
    
    E --> G{"Result OK?"}
    G -- Yes --> H{"Requires HITL?"}
    G -- No, retry --> E
    G -- No, fatal --> I["Error + log"]
    
    H -- Yes --> J["👤 Human approves/rejects"]
    J --> K["Execute / Cancel"]
    H -- No --> L["✅ Response to user"]
    K --> L
    
    style A fill:#e1f5fe
    style L fill:#c8e6c9
    style I fill:#ffcdd2
    style J fill:#fff9c4
```

## Decision Framework

<!-- Every autonomous AI decision follows this framework. -->

```mermaid
flowchart TD
    A["Decision to make"] --> B["1. Data available?"]
    B --> C["2. Existing rule/directive?"]
    C --> D["3. Risk/benefit?"]
    D --> E{"Within my autonomy?"}
    
    E -- Yes --> F["Execute + Log"]
    E -- No --> G["HITL: request approval"]
    G -->|"Approved"| F
    G -->|"Rejected"| H["Cancelled + log"]
```
