# Command Index

All system commands, their triggers, required tools, and invocation mode.

## Setup

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/onboard-init` | `__NEEDS_ONBOARD` exists in project root | Read, Write, Edit, Agent, Bash(date,git,find,wc) | Self-execute | First-time onboarding — scan project, generate profiles, configure system |

## Daily Rituals

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/start` | Beginning of work day | Read, Write, Edit, Bash(date) | Self-execute | Load memory, create daily note, review tasks |
| `/sync` | Mid-day (after 3-4 hours) | Read, Write, Edit, Bash(date), Agent | Self-execute | Refresh memory, process scratchpad, review tasks |
| `/wrap-up` | End of work day | Read, Write, Edit, Bash(date), Agent | Self-execute | Daily audit, externalize knowledge, prep tomorrow |
| `/standup` | Start of day (quick mode) | Read, Edit, Glob, Bash(git,date) | Self-execute | Auto-generate yesterday/today/blockers from git + tasks |
| `/clear` | Context pressure or task completion | Read, Write, Edit, Bash(date,bash) | Self-execute | Distill state, flush context, stop session |
| `/resume` | After /clear, same day | Read, Edit, Bash(date,bash) | Self-execute | Lightweight resume — load handoff, restart timer, pick up work |
| `/brainstorm-session [idea]` | End of session or between tasks — ideas to keep for later | Read, Edit, Bash(date) | Self-execute | Isolated idea mode — discuss, evaluate, promote to tomorrow's Task Board |

## Quality & Review

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/audit [scope]` | After completing a task/feature | Read, Agent, Write, Edit | Self-execute | Delegate quality review to auditor agent |
| `/review [target]` | Before merging code | Read, Agent, Glob, Grep, Bash(git) | Self-execute | Deep code review — security + performance + architecture |
| `/deep-audit` | Monthly or after major refactors | Read, Agent, Glob, Grep, Write, Bash(date,find) | Self-execute | Full project audit — 6 specialist analysts in parallel, PASS/WARN/FAIL report |
| `/system-audit` | Monthly or after major changes | Read, Glob, Grep, Agent, Write, Edit, Bash(date,wc,find) | Self-execute | Deep infrastructure audit of entire system |
| `/drift-detect` | Monthly or when behaviour feels off | Read, Agent, Glob, Grep, Bash(wc,find,date) | Self-execute | Detect config drift — stale rules, contradictions, orphans |
| `/retro [period]` | End of sprint/week | Read, Write, Edit, Glob, Agent, Bash(date) | Self-execute | Sprint retrospective — analyze patterns, improve process |
| `/debt-map [dir]` | Before planning sprint work | Read, Agent, Glob, Grep, Bash(git,wc,find) | Self-execute | Map and prioritise technical debt across codebase |

## Problem Solving

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/unstick [problem]` | When stuck on a problem 10+ min | Read, Agent, Grep, Glob, WebSearch | Self-execute | Root-cause analysis via unsticker agent |
| `/onboard [project]` | Starting work on unfamiliar codebase | Read, Agent, Glob, Grep, Bash(git,find,wc,ls) | Self-execute | Generate full codebase onboarding guide |

## Communication & Delivery

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/release [version]` | Shipping a new version | Read, Write, Edit, Glob, Grep, Bash(git,date) | Self-execute | Auto-generate release notes — technical + marketing + executive |
| `/handoff [recipient]` | Passing work to another person or AI | Read, Write, Edit, Glob, Grep, Bash(git,date) | Self-execute | Structured session handoff with full context briefing |

## Autoresearch (Autonomous Loops)

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/autoresearch [goal]` | Any task with a measurable metric | Read, Write, Edit, Bash(git:*), Agent | Self-execute | Autonomous iteration loop — modify, verify, keep/discard, repeat |
| `/autoresearch:plan [goal]` | Before starting a complex autoresearch run | Read, Write, Agent | Self-execute | Interactive wizard: Goal → Scope + Metric + Verify |
| `/autoresearch:debug` | Circular debugging 3+ attempts or bug hunt | Read, Grep, Glob, Bash(git:*) | Self-execute | Scientific bug-hunting loop — runs until root cause found |
| `/autoresearch:fix` | Build broken, tests failing, type errors | Read, Write, Edit, Bash(git:*) | Self-execute | Iterative fix loop — one atomic fix per iteration until zero errors |
| `/autoresearch:security [scope]` | Before merge, wrap-up (code changed), /review | Read, Grep, Glob | Self-execute | STRIDE + OWASP + 4 red-team personas |
| `/autoresearch:predict [scope]` | During /review, before /proposal | Read, Glob | Self-execute | 5-persona swarm: Architect, Security, Performance, Reliability, Devil's Advocate |
| `/autoresearch:scenario [seed]` | During /brief, /audit T3+, edge case exploration | Read, Write, Agent | Self-execute | 12-dimension scenario generator — edge cases, failures, abuse patterns |
| `/autoresearch:ship [target]` | During /release, /handoff | Read, Write, Bash(git:*) | Self-execute | 8-phase universal shipping checklist — dry-run or execute |
| `/autoresearch:learn` | Fridays at wrap-up, before /onboard | Read, Write, Edit, Glob | Self-execute | Scout → generate/update docs → validate → fix cycle |

## System Building

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/playbook [name]` | Repeating a manual workflow | Read, Write, Edit, Glob, Bash(date) | Self-execute | Record a workflow and auto-generate a reusable command |
| `/generate-skills [category\|slug\|--all]` | Adding/updating boilerplate skills | Read, Write, Bash(find,mkdir) | Self-execute | Generate SKILL.md files from manifest — single source of truth for boilerplate skills |

## Migrated to Skills

These were once commands but have been converted to **skills** because they are pure procedural knowledge with no temporal trigger or critical-action requirement. They are now activated semantically by the agent when the user describes a matching task in natural language. No `/command` to remember — just describe what you want and the skill activates.

| Former command | Now skill | Activation hint |
|----------------|-----------|-----------------|
| `/scaffold-cli [binary]` | [`scaffold-cli`](./skills/scaffold-cli/SKILL.md) | "scaffold a CLI", "design a command-line tool", "create an ocli spec" |
| `/report [topic]` | [`report-writing`](./skills/report-writing/SKILL.md) | "write a report", "create an executive summary", "draft a report for [audience]" |
| `/competitive-intel [market]` | [`competitive-intel`](./skills/competitive-intel/SKILL.md) | "analyze competitors", "competitive analysis", "how do we compare against" |

**Migration date**: 2026-04-07. Reason: pure procedural knowledge, no artefact trigger and no rituale temporale → fits the skill-first model better than the command-first one. See `Lavoro 3` in commit history for the design discussion that led here.

## Auto-Trigger Conditions

Commands should be proactively invoked (not waiting for user) when:

| Condition | Command |
|-----------|---------|
| `__NEEDS_ONBOARD` file exists | `/onboard-init` (before any other command) |
| Session starts fresh | `/start` (if morning) or `/standup` (if quick) |
| Ideas emerge at end of session or between tasks | `/brainstorm [seed]` |
| 30+ tool calls in session | `/clear` |
| Compaction warning | `/clear` (emergency mode) |
| Discrete multi-step task completes | Consider `/clear` |
| Quality feels degraded | `/clear` |
| Stuck for 10+ minutes | `/unstick` |
| Feature/task completed | `/audit` |
| Before merging code | `/review` (which auto-invokes `:security` + `:predict`) |
| Starting unfamiliar project | `/onboard` |
| Passing work to someone else | `/handoff` (which auto-invokes `:ship --dry-run`) |
| System behaviour feels off | `/drift-detect` |
| Code changed today at wrap-up | `/autoresearch:security --diff --depth shallow` |
| Friday wrap-up | `/autoresearch:learn` + AI Operations Registry update (if present) |
| Monthly or after major refactors | `/deep-audit` |
| Same error hit 3+ times | `/autoresearch:debug` (via `/unstick` escalation) |
| Shipping a release | `/autoresearch:ship --dry-run` (via `/release`) |
| Weekly audit (T3+) | `/autoresearch:scenario` (via `/audit`) |

## Invocation Modes

- **Self-execute**: Read the command file and follow the procedure directly
- **Recommend**: Output `RECOMMEND: /command [args] — [reason]` for the orchestrator
