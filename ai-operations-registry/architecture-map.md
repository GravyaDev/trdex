# AI Operational Architecture

> Last updated: {{DATE}}

## Mind map

<!-- Adapt the diagram to your project. This is a starting structure. -->

```mermaid
mindmap
  root(({{PROJECT_NAME}}))
    👤 <br> HUMAN PARTNERS
      {{HUMAN_1}} <br> {{ROLE_1}}
      {{HUMAN_2}} <br> {{ROLE_2}}
    🤖 <br> AI ORCHESTRATOR
      Orchestration
      Memory
      Specialized agents
    🏗️ <br> INFRASTRUCTURE
      Backend <br> {{BACKEND_STACK}}
      Storage <br> {{DB_STACK}}
    🛡️ <br> GOVERNANCE
      HITL <br> Guardrails
      Traceability <br> Audit Logs
```

## Agent hierarchy tree

<!-- Fill in with your agents, supervisors, executors, tools. -->
<!-- Pattern: each agent has Responsibility, Autonomy, Limits, Traceability. -->

```
{{PROJECT_NAME}} OPERATIONS
│
├── 👤 {{HUMAN_1}} (Human Partner)
│   ├── Responsibility: {{...}}
│   └── HITL scope: Can promote processes from full_manual → full_auto
│
├── 🤖 AI ORCHESTRATOR
│   ├── Config: {{where it is configured — file, DB, etc.}}
│   ├── LLM Model: {{default model + fallback}}
│   ├── Responsibilities:
│   │   ├── Task routing → correct agent
│   │   ├── Context loading
│   │   ├── HITL protocol enforcement
│   │   └── Session and cost logging
│   │
│   ├── 🔧 SPECIALIZED AGENTS
│   │   ├── {{agent_1}} — {{description}}
│   │   ├── {{agent_2}} — {{description}}
│   │   └── ...
│   │
│   └── 🛠️ TOOLS
│       ├── {{tool_1}} — {{description}}
│       └── ...
│
└── 🏗️ INFRASTRUCTURE
    ├── {{layer_1}} — {{stack}}
    └── {{layer_2}} — {{stack}}
```
