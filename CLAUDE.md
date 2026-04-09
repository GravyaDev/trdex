# Claude Context — Kloudify

This project uses Kloudify, a professional operating system for Claude Code.
Always read `.claude/memory.md` before taking action.

## ⛔ HARD RULES — Enforced by hooks, no exceptions

These rules are checked mechanically by `.claude/hooks/guard-bash.sh`. Violating them blocks the command.

| Rule | What to do instead |
|------|-------------------|
| **Never call third-party APIs directly** (curl/wget/requests/httpx/fetch to any external platform API) | Always use a python tool that handles rate-limiting, throttle headers, retries, auth |
| **Never read official API docs from secondary sources** (articles, blog posts) | Always fetch `/docs` or `/openapi.json` from the official endpoint first, then ask user if nothing was found |
| **Never write outside working directory** | This applies to ALL repos and directories, no exceptions. Any repo outside working directory is an independent product. Writing there causes cross-contamination and violates repo isolation. The user has stated this constraint clearly multiple times. Before every Read/Write/Edit/Bash, verify the target path. If it doesn't, stop and ask the user for clarification before proceeding.

## Rule Precedence — project KB > global user instructions

When a project-specific rule in `.claude/knowledge-base.md` conflicts with a
default set in the global user instructions (`~/.claude/CLAUDE.md`), **the
project knowledge-base wins**. Always. No exceptions.

The most frequent case where this matters is **commit identity**: the global
user instructions may define a default `Co-Authored-By` trailer that applies
across all projects. If the project knowledge-base declares its own `Commit
Identity` rule, that project rule takes precedence and the global default
MUST NOT be used in commits for this project.

This is enforced mechanically by `.claude/hooks/guard-commit-identity.sh`:
the hook reads the knowledge-base, extracts the required email, and HARD
BLOCKS any `git commit` whose message contains a `Co-Authored-By` trailer
with a different email. If no identity is configured in the knowledge-base,
the hook is fail-open (allows any trailer) — this is the base-repo case.

## First-Run Onboarding

If the file `__NEEDS_ONBOARD` exists in the project root:
- If the project is **already onboardated** (`.claude/memory.md` or
  `.claude/knowledge-base.md` exists), delete the sentinel silently
  and continue — the onboarding was already done.
- Otherwise, execute `/onboard-init` before any other action. This
  runs the automated first-time setup: project scan, profile
  generation, and system configuration.

## Date Format

All dates throughout the system use **ISO 8601: `YYYY-MM-DD`**. This applies to:
- Daily Notes filenames (`Daily Notes/YYYY-MM-DD.md`)
- Log entries and timestamps
- Knowledge base source tags (`[Source: user override 2026-04-03]`)
- Audit reports and security patch logs

Never use locale-dependent formats (MM/DD/YY, DD/MM/YY, YYYY-MM-DD). The system date for today is provided in the conversation context — use that, not `date` command output, to avoid format mismatches.

## Quick Start

**Daily rituals (you invoke these)**:
- `/start` — begin work
- `/sync` — mid-day refresh
- `/wrap-up` — end of day
- `/audit` — verify quality after a task or feature
- `/system-audit` — deep infrastructure audit (monthly)

**Auto-nudged (Kloudify surfaces these in your daily note when their trigger fires)**:
- `/retro` — sprint retrospective. Nudged after 7+ days without one (`retro-suggester.sh`).
- `/unstick` — when blocked. Nudged when 3+ failures of the same category accumulate (`stuck-detector.sh`).
- `/debt-map` — tech debt inventory. Nudged when 20+ new TODO/FIXME markers accumulate (`debt-suggester.sh`).

For context-pressure handling (`/clear` and friends), see the **Context Health** section below.

## Key Files
- Memory: `.claude/memory.md` (read this for current context)
- Universal Rules: `.claude/universal-rules.md` (cross-project rules shipped with Kloudify — read before every task)
- Knowledge Base: `.claude/knowledge-base.md` (project-specific learned rules — read after universal-rules.md)
- Task Board: `Task Board.md`
- Scratchpad: `Scratchpad.md` (quick capture, processed during /sync, cleared at /wrap-up)
- Daily Notes: `Daily Notes/` (created automatically by /start)
- Knowledge Nominations: `.claude/knowledge-nominations.md` (candidate learnings — auditor reviews)
- Command Index: `.claude/command-index.md` (all commands with triggers and tools)

## System Architecture
- **Agents** (`.claude/agents/`): Specialist subagents with persistent memory
  - `auditor` — Quality gate. Reviews work, promotes knowledge, proposes SOP revisions
  - `unsticker` — Unblocks you when stuck. Root-cause analysis, fresh approaches
  - `error-whisperer` — Translates cryptic errors into fixes. Pattern matching across sessions
  - `rubber-duck` — Forces you to articulate the real problem. Socratic debugging
  - `pr-ghostwriter` — Writes PR descriptions, commit messages, changelogs from diffs
  - `yak-shave-detector` — Catches scope creep. "You started doing X but now you're doing Y"
  - `debt-collector` — Tracks tech debt. Catalogues shortcuts, suggests when to pay them down
  - `onboarding-sherpa` — Learns a new codebase fast. Architecture maps, key-file identification
  - `archaeologist` — Excavates why code exists. Git blame + context reconstruction
- **Commands** (`.claude/commands/`): Workflow rituals and utilities
- **Hooks** (`.claude/hooks/`): Deterministic safety enforcement (logging, verification)
- **Logs** (`.claude/logs/`): Audit trail + incident log — auto-populated by hooks
- **Skills** (`.claude/skills/`): Domain knowledge, loaded on demand

## Activation Model — when each primitive fires

Three primitives, three orthogonal triggers. Use this classification when adding new behavior to Kloudify or when deciding whether something belongs as a hook, a command, or a skill.

| Primitive | Trigger axis | When to use it | Example |
|-----------|--------------|----------------|---------|
| **Hook** (`.claude/hooks/*.sh`) | **Artefact-triggered** — fires on a deterministic event (file write, tool call, session start, failure pattern). No human intent needed. | Behavior that should happen *automatically* in response to a state change. The user must not have to remember it. | `drift-detect.sh` runs when `CLAUDE.md` is edited; `stuck-detector.sh` fires when 3+ failures of the same category accumulate. |
| **Command** (`.claude/commands/*.md`) | **Intent-triggered** — fires when the user explicitly invokes `/foo`. Requires a human "now" decision. | Deliberate rituals tied to a specific moment, or critical operations that must be human-armed. Few enough to remember without effort. | `/start`, `/wrap-up`, `/audit`, `/deep-audit` — temporal rituals or human-gated critical actions. |
| **Skill** (`.claude/skills/*/SKILL.md`) | **Semantic-triggered** — fires when the agent recognizes a task that matches the skill's `description` frontmatter. Activated by natural-language conversation, not by syntax. | Pure procedural knowledge with no temporal trigger and no critical-action requirement. The user describes the goal, the agent picks the right skill. | `report-writing`, `competitive-intel`, `scaffold-cli` — payload knowledge applied on user request. |

**Decision filter** for any new behavior:
1. Is there an *observable artefact signal* (file change, threshold, event) that marks the right moment? → **Hook**.
2. Does it require *deliberate human intent* at a specific moment, or is it a *critical operation* that must not auto-fire? → **Command**.
3. Is it *procedural knowledge* the user requests in natural language? → **Skill**.

If none of the three apply, the behavior probably doesn't need to exist. If two apply, the artefact-triggered path wins (more deterministic, less to remember).

**Determinism note** — hooks are the only primitive that gives you *pre-action* determinism (the action is gated before it runs). Commands and skills give you *post-action* accountability (you log what happened after it ran). When the cost of a wrong action is high, prefer the hook even if the trigger is awkward.

**Migration history**: see commit `6df3259` for the first application of this model — three procedural commands (`/scaffold-cli`, `/report`, `/competitive-intel`) were converted to skills because they had no artefact trigger and no temporal ritual. Commit `59fd187` added three artefact-triggered hooks (drift, onboarding, stuck) to replace behaviors that previously required the user to remember to invoke a command.

## Memory Architecture (7 Tiers)
1. **memory.md** — Active session context (what you're doing now)
2. **Agent Memory** (`.claude/agent-memory/`) — Per-agent persistent knowledge across sessions
3. **Universal Rules** (`.claude/universal-rules.md`) — Cross-project rules shipped with Kloudify (versioned in base repo, read by all agents at startup)
4. **Knowledge Base** (`.claude/knowledge-base.md`) — Project-specific learned rules (auditor-gated, gitignored, created at onboarding)
5. **Knowledge Nominations** (`.claude/knowledge-nominations.md`) — Candidate learnings pipeline
6. **MCP Knowledge Graph** — Structured entities and relations (if memory MCP enabled)
7. **Daily Notes** — Chronological session history and handoff records

## Command Awareness

All agents can invoke system commands. Read `.claude/command-index.md` for the full catalog.

- **Self-execute**: If you have the tools a command requires, read `.claude/commands/{name}.md` and follow the procedure directly.
- **Recommend**: If you lack the tools, output `RECOMMEND: /command [args] — [reason]` for the orchestrator.
- Agents should proactively invoke commands when trigger conditions match.

## Retrieval Map — Where to look for what

| You need... | Check first | Then |
|---|---|---|
| What am I doing right now? | `memory.md` → Now | Task Board → Today |
| How to do a procedure | `.claude/commands/` or `.claude/skills/` | CLAUDE.md |
| A universal rule (cross-project) | `universal-rules.md` | — |
| A project-specific rule | `knowledge-base.md` → Hard Rules | Agent memory |
| What happened on a specific day | `Daily Notes/YYYY-MM-DD.md` | Audit trail |
| What went wrong before | `universal-rules.md` then `knowledge-base.md` | Agent memory → Known Patterns |
| What commands exist | `.claude/command-index.md` | `.claude/commands/{name}.md` |

## Context Health

Sessions have finite context. Heavy operations consume it fast.

**Automatic hooks at compact boundaries:**
- `PreCompact` hook (`pre-compact-handoff.sh`) writes an "Auto-compaction cut" placeholder in today's daily note with a precise timestamp and recovery pointers. **It does NOT distill session state** — a bash hook cannot read Claude's in-context memory. The placeholder is a breadcrumb, not a handoff.
- `SessionStart(compact)` hook (`post-compact-resume.sh`) injects a short orientation prompt pointing Claude to the recovery anchors (memory.md, knowledge-base.md, the daily note). **It does NOT instruct bulk re-read** and **does NOT auto-resume the previous task** — Claude waits for user input.
- `SessionStart(user)` hook (`session-reset.sh`) resets stale gate files, validates hook permissions, prunes oversized audit trails.

**Completeness gates (PreToolUse Write|Edit — hard blocks):**
- **universal-rules.md** and **knowledge-base.md**: Every entry needs `[Source:]` provenance, max 200 lines, no TBD/TODO
- **memory.md**: Max 100 lines (Write only)
- **settings.json**: Must be valid JSON (broken JSON breaks all hooks)
- **Agent defs** (`.claude/agents/*.md`): No TBD/TODO — instructions must be definitive
- **Ungated** (iterative by nature): Daily Notes, Scratchpad, Templates, Logs, Commands, Skills

**Context-pressure response — emergency vs proactive:**

The response to context pressure is **two-tier** and the distinction matters:

*Emergency tier* (auto-acting, no confirmation needed):
- **Compacting warning visible**: run `/clear` in emergency mode immediately. No choice — the alternative is uncontrolled compaction.
- **Prompt-too-long hard error**: same.

In emergency mode `/clear` skips the optional reads and distills only from in-context memory, then stops. This is the only case where Claude invokes `/clear` without asking.

*Proactive tier* (signalling, NOT auto-acting):
- **After ~30+ tool calls or 3+ large file reads**: surface a visible heads-up to the user — "Heads up: context is getting heavy. `/clear` is a natural stopping point if you want a fresh session." Do NOT invoke `/clear` without confirmation.
- **Output quality degrades** (repetition, missed details): same — signal the degradation, suggest `/clear`, wait for the user.
- **Discrete multi-step task completes**: suggest `/clear` as an option, do not force it. The user may want to continue in the same session.
- **Switching between different task domains**: acknowledge the boundary in plain language, suggest `/clear` if the switch is heavy, wait.

**Why the split**: `/clear` is NOT seamless. It saves a handoff and stops — the user must open a fresh session to continue. Auto-invoking `/clear` proactively interrupts the flow and forces a session restart the user did not ask for. Auto-invoking in emergency is different: the session is going to break anyway, and `/clear` gives a cleaner failure mode than uncontrolled compaction.

**How /clear works:** Distills in-context session state into `Daily Notes/YYYY-MM-DD.md` as a Session Handoff section, updates `memory.md` if needed, promotes/nominates learnings, then **stops and reports the save location**. It does NOT re-read files, does NOT auto-resume, does NOT continue the previous task. To resume the work, open a fresh session and read the handoff section of the daily note. See `.claude/commands/clear.md` for the full protocol.

**Delegation for context hygiene:**
When a task is self-contained (its output does not inform the next step), delegate it to a subagent. This preserves context for work that actually needs it. Examples: batch find-and-replace, linting checks, file generation from templates, verification scans.

## Response Quality

At the end of every task, verify that the response satisfies the real intent of the request. If there are discrepancies (missing output format, incomplete execution, instructions not followed), perform an internal Chain-of-Thought refinement pass and return only the corrected version. Do not conclude a task until every instruction has been respected.

## Maintenance
- Keep memory.md compact (<100 lines)
- Aggressively prune stale items
- Done list cleared on Fridays
- Review incident log during /sync and /wrap-up
- Auditor proposes SOP revisions — user approves before changes apply