# Command Index

All system commands, their triggers, required tools, and invocation mode.

## Daily Rituals

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/start` | Beginning of work day | Read, Write, Edit, Bash(date) | Self-execute | Load memory, create daily note, review tasks |
| `/sync` | Mid-day (after 3-4 hours) | Read, Write, Edit, Bash(date), Agent | Self-execute | Refresh memory, process scratchpad, review tasks |
| `/wrap-up` | End of work day | Read, Write, Edit, Bash(date), Agent | Self-execute | Daily audit, externalize knowledge, prep tomorrow |
| `/standup` | Start of day (quick mode) | Read, Edit, Glob, Bash(git,date) | Self-execute | Auto-generate yesterday/today/blockers from git + tasks |
| `/clear` | Context pressure or task completion | Read, Write, Edit, Bash(date) | Self-execute | Distill state, flush context, auto-resume |
| `/brainstorm-session [idea]` | End of session or between tasks — ideas to keep for later | Read, Edit, Bash(date) | Self-execute | Isolated idea mode — discuss, evaluate, promote to tomorrow's Task Board |

## Quality & Review

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/audit [scope]` | After completing a task/feature | Read, Agent, Write, Edit | Self-execute | Delegate quality review to auditor agent |
| `/review [target]` | Before merging code | Read, Agent, Glob, Grep, Bash(git) | Self-execute | Deep code review — security + performance + architecture |
| `/system-audit` | Monthly or after major changes | Read, Glob, Grep, Agent, Write, Edit, Bash(date,wc,find) | Self-execute | Deep infrastructure audit of entire system |
| `/drift-detect` | Monthly or when behaviour feels off | Read, Agent, Glob, Grep, Bash(wc,find,date) | Self-execute | Detect config drift — stale rules, contradictions, orphans |
| `/retro [period]` | End of sprint/week | Read, Write, Edit, Glob, Agent, Bash(date) | Self-execute | Sprint retrospective — analyze patterns, improve process |
| `/debt-map [dir]` | Before planning sprint work | Read, Agent, Glob, Grep, Bash(git,wc,find) | Self-execute | Map and prioritise technical debt across codebase |

## Problem Solving

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/unstick [problem]` | When stuck on a problem 10+ min | Read, Agent, Grep, Glob, WebSearch | Self-execute | Root-cause analysis via unsticker agent |
| `/onboard [project]` | Starting work on unfamiliar codebase | Read, Agent, Glob, Grep, Bash(git,find,wc,ls) | Self-execute | Generate full codebase onboarding guide |

## Planning & Strategy

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/competitive-intel [market]` | Entering a new market or evaluating position | Read, Write, Edit, Agent, Glob, WebSearch, WebFetch, Bash(date) | Self-execute | Deep competitive analysis with strategic recommendations |

## Communication & Delivery

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/report [topic]` | Need to present findings to stakeholders | Read, Write, Edit, Agent, Glob, Grep, Bash(date) | Self-execute | Generate audience-aware professional report |
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

## Dev Team

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/team decompose [feature]` | Starting a new feature | Read, Write, Edit, Glob, Grep | Self-execute | Scompone una feature in task atomici via task-decomposer → scrive context/current-feature.md |
| `/team architect [feature]` | After decompose, before build | Read, Write, Edit, Bash, Glob, Grep | Self-execute | Design API + DB schema via backend-architect + database-architect → scrive context/architecture.md |
| `/team review` | Before merge or after implementation | Read, Grep, Glob, Bash | Self-execute | Code review (security/performance/correctness) + architectural review → scrive context/review-notes.md |
| `/team build [feature]` | Full feature workflow | Read, Write, Edit, Bash, Glob, Grep | Self-execute | Workflow completo: decompose → architect → build (fullstack o python developer) → review |
| `/team python [feature]` | AI/Python feature implementation | Read, Write, Edit, Bash, Glob, Grep | Self-execute | Implementa componenti LangGraph/FastAPI/LiteLLM via python-ai-developer |

## System Building

| Command | Trigger | Tools | Mode | Description |
|---------|---------|-------|------|-------------|
| `/playbook [name]` | Repeating a manual workflow | Read, Write, Edit, Glob, Bash(date) | Self-execute | Record a workflow and auto-generate a reusable command |
| `/scaffold-cli [binary]` | Starting a new CLI tool or formalising an existing one | Read, Write, Edit, Bash(ocli,date), Glob | Self-execute | Design CLI spec-first with OpenCLI, generate code + docs |
| `/generate-skills [category\|slug\|--all]` | Adding/updating boilerplate skills | Read, Write, Bash(find,mkdir) | Self-execute | Generate SKILL.md files from manifest — single source of truth for boilerplate skills |

## Auto-Trigger Conditions

Commands should be proactively invoked (not waiting for user) when:

| Condition | Command |
|-----------|---------|
| Session starts fresh | `/start` (if morning) or `/standup` (if quick) |
| Ideas emerge at end of session or between tasks | `/brainstorm [seed]` |
| 30+ tool calls in session | `/clear` |
| Compaction warning | `/clear` (emergency mode) |
| Discrete multi-step task completes | Consider `/clear` |
| Quality feels degraded | `/clear` |
| Stuck for 10+ minutes | `/unstick` |
| Feature/task completed | `/audit` |
| Starting a CLI tool project | `/scaffold-cli` |
| Before merging code | `/review` (which auto-invokes `:security` + `:predict`) |
| Starting unfamiliar project | `/onboard` |
| Passing work to someone else | `/handoff` (which auto-invokes `:ship --dry-run`) |
| System behaviour feels off | `/drift-detect` |
| Code changed today at wrap-up | `/autoresearch:security --diff --depth shallow` |
| Friday wrap-up | `/autoresearch:learn --mode update --depth quick` |
| Same error hit 3+ times | `/autoresearch:debug` (via `/unstick` escalation) |
| Shipping a release | `/autoresearch:ship --dry-run` (via `/release`) |
| Weekly audit (T3+) | `/autoresearch:scenario` (via `/audit`) |

## Invocation Modes

- **Self-execute**: Read the command file and follow the procedure directly
- **Recommend**: Output `RECOMMEND: /command [args] — [reason]` for the orchestrator
