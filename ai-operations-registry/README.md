# AI Operations Registry — {{PROJECT_NAME}}

> **Purpose:** Full traceability of every AI process. No black boxes.
> **Last updated:** {{DATE}}
> **Policy:** Every AI operation must be logged with who, what, where, how, and why.
> **Update frequency:** Weekly (Friday, wrap-up Step 6d)

---

## Index

| Section | File | Description |
|---|---|---|
| Operational architecture | [architecture-map.md](architecture-map.md) | Mind map + agent hierarchy tree |
| Decision chain | [decision-chain.md](decision-chain.md) | Request-to-result flow + decision framework |
| Process registry | [processes.md](processes.md) | Active and planned processes with HITL level |
| Traceability matrix | [traceability.md](traceability.md) | Where each event type is logged |
| Escalation schema | [escalation.md](escalation.md) | Escalation tree + unconditional triggers |
| Known gaps | [gaps.md](gaps.md) | Traceability gaps with fix priority |

---

## Principles

1. **No black boxes** — every AI decision has a log with who, what, why
2. **Progressive HITL** — `full_manual` → `escalation` → `low_risk` → `full_auto`, promoted only by human partners
3. **Unconditional escalation** — real expenses, irreversible impacts, and creative judgments ALWAYS go to human partners
4. **Tracked cost** — every LLM call logs model, tokens, cost

---

## Significant architectural changes

| Date | Change |
|---|---|
| {{DATE}} | Initial registry |

---

*Living document — updated every Friday at wrap-up.*
