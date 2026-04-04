# Escalation Schema

> Last updated: {{DATE}}

## Escalation tree

```mermaid
flowchart TD
    E["⚙️ Agent detects problem"] --> S{"Type?"}
    
    S -->|"Technical error"| R["Retry"]
    R --> R1{"Resolved?"}
    R1 -- Yes --> OK["✅ Continue"]
    R1 -- No --> F{"Critical?"}
    
    F -- Yes --> FAIL["❌ Stop + log"]
    F -- No --> PS{"Strategy?"}
    PS -->|"Accept with disclaimer"| OK
    PS -->|"Escalation"| HITL
    PS -->|"Abort"| FAIL
    
    S -->|"Outside autonomy"| HITL["🚨 HITL"]
    
    HITL --> HUM["👤 Human decides"]
    HUM -->|"Approved"| OK
    HUM -->|"Rejected"| CANCEL["Cancelled + log"]
    
    style OK fill:#c8e6c9
    style HITL fill:#fff9c4
    style FAIL fill:#ffcdd2
    style CANCEL fill:#ffcdd2
```

## Unconditional escalation triggers

<!-- These triggers ALWAYS cause escalation, regardless of the HITL level. -->
<!-- Adapt to your project's reality. -->

| # | Trigger | Rationale |
|---|---|---|
| 1 | Real expense involved | Budget at risk |
| 2 | Irreversible impact | Sending, publishing, deploying |
| 3 | Decision outside directives | No applicable rule |
| 4 | Interpersonal situation | Conflict, complaint, negotiation |
| 5 | Subjective judgment | Subjectivity not algorithmizable |
| 6 | Repeated anomaly (3+ times) | Structural error pattern |

## HITL Levels

| Level | Behavior | Promoted by |
|---|---|---|
| `full_manual` | Every action requires approval | Default |
| `escalation` | Only high-risk decisions | Human partner |
| `low_risk` | Only unconditional triggers | Human partner |
| `full_auto` | No interruption (log-only) | Human partner + periodic review |
