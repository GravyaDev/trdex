# Claude Context — Kloudify

This project uses Kloudify, a professional operating system for Claude Code.
Always read `.claude/memory.md` before taking action.

## ⛔ HARD RULES — Enforced by hooks, no exceptions

These rules are checked mechanically by `.claude/hooks/guard-bash.sh`. Violating them blocks the command.

| Rule | What to do instead |
|------|-------------------|
| **Never call third-party APIs directly** (curl/wget/requests/httpx/fetch to any external platform API) | Always use a python tool that handles rate-limiting, throttle headers, retries, auth |
| **Never read official API docs from secondary sources** (articles, blog posts) | Always fetch `/docs` or `/openapi.json` from the official endpoint first, then ask user if nothing was found |
| **Never write outside `trdex/`** | This applies to ALL repos and directories, no exceptions. Any repo outside trdex is an independent product. Writing there from a trdex session causes cross-contamination and violates repo isolation. The user has stated this constraint clearly multiple times. Before every Read/Write/Edit/Bash, verify the target path starts with `trdex/`. If it doesn't, stop and ask the user for clarification before proceeding.

## First-Run Onboarding

If the file `__NEEDS_ONBOARD` exists in the project root, execute `/onboard-init` before any other action. This runs the automated first-time setup: project scan, profile generation, and system configuration.

## Date Format

All dates throughout the system use **ISO 8601: `YYYY-MM-DD`**. This applies to:
- Daily Notes filenames (`Daily Notes/YYYY-MM-DD.md`)
- Log entries and timestamps
- Knowledge base source tags (`[Source: user override 2026-04-03]`)
- Audit reports and security patch logs

Never use locale-dependent formats (MM/DD/YY, DD/MM/YY, YYYY-MM-DD). The system date for today is provided in the conversation context — use that, not `date` command output, to avoid format mismatches.

## Quick Start
- Run `/start` to begin work
- Run `/sync` mid-day to refresh memory
- Run `/wrap-up` at end of day
- Run `/audit` to verify recent work quality
- Run `/clear` to safely flush context and resume fresh
- Run `/unstick` when stuck on a problem
- Run `/retro` for sprint retrospective
- Run `/system-audit` for deep infrastructure audit

## Key Files
- Memory: `.claude/memory.md` (read this for current context)
- Knowledge Base: `.claude/knowledge-base.md` (system-wide learned rules — read before every task)
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

## Memory Architecture (6 Tiers)
1. **memory.md** — Active session context (what you're doing now)
2. **Agent Memory** (`.claude/agent-memory/`) — Per-agent persistent knowledge across sessions
3. **Knowledge Base** (`.claude/knowledge-base.md`) — System-wide learned rules (auditor-gated)
4. **Knowledge Nominations** (`.claude/knowledge-nominations.md`) — Candidate learnings pipeline
5. **MCP Knowledge Graph** — Structured entities and relations (if memory MCP enabled)
6. **Daily Notes** — Chronological session history and handoff records

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
| A fact or learned rule | `knowledge-base.md` | Agent memory |
| What happened on a specific day | `Daily Notes/YYYY-MM-DD.md` | Audit trail |
| What went wrong before | `knowledge-base.md` → Hard Rules | Agent memory → Known Patterns |
| What commands exist | `.claude/command-index.md` | `.claude/commands/{name}.md` |

## Context Health

Sessions have finite context. Heavy operations consume it fast.

**Automatic safety net (hooks):**
- `PreCompact` hook saves state before auto-compaction
- `SessionStart(compact)` hook restores context after compaction
- `SessionStart(user)` hook resets stale gate files on every fresh session

**Completeness gates (PreToolUse Write|Edit — hard blocks):**
- **knowledge-base.md**: Every entry needs `[Source:]` provenance, max 200 lines, no TBD/TODO
- **memory.md**: Max 100 lines (Write only)
- **settings.json**: Must be valid JSON (broken JSON breaks all hooks)
- **Agent defs** (`.claude/agents/*.md`): No TBD/TODO — instructions must be definitive
- **Ungated** (iterative by nature): Daily Notes, Scratchpad, Templates, Logs, Commands, Skills

**Self-monitoring (soft signals — Claude's responsibility):**
- After ~30+ tool calls or 3+ large file reads: run `/clear` proactively
- If you see a "compacting conversation" warning: run `/clear` immediately
- If output quality degrades (repetition, missed details): run `/clear`
- When a discrete multi-step task completes: consider `/clear` before starting the next unrelated task
- When switching between different task domains: acknowledge the boundary, prefer `/clear` for heavy switches

**How /clear works:** Distills session state into memory.md + daily note handoff, preserving retrieval paths. Then automatically resumes work by reloading compressed context and executing the next action. Seamless to the user.

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
