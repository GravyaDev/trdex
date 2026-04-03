# Kloudify

**A professional operating system for Claude Code.**

Kloudify transforms Claude Code from a powerful AI assistant into a persistent, self-improving development partner. It adds structured memory, specialist agents, automated safety hooks, and on-demand professional skills — all orchestrated through simple slash commands.

---

## Highlights

| Feature | What it does |
|---|---|
| **6-tier memory** | Claude remembers context across sessions, learns from mistakes, and gets smarter over time |
| **9 specialist agents** | Purpose-built subagents for quality, debugging, code review, onboarding, and more |
| **25+ commands** | Workflow rituals (`/start`, `/sync`, `/wrap-up`) plus tools for planning, audit, review, and delivery |
| **On-demand skills** | Generator approach: manifest + template → focused skill files produced when needed. No bloat. |
| **Automated hooks** | Deterministic safety nets: dangerous command blocking, file backup, completeness gates, project stack tracking, full audit trail |
| **Self-improvement engine** | Knowledge nominations → auditor review → promoted rules. The system gets better the more you use it |
| **Project profiling** | Auto-generated `project-stack.md` + `project-structure.md` keep agents aware of your stack without re-scanning |
| **AI Operations Registry** | Optional traceability layer: who does what, where, how — with escalation and gap tracking |

---

## Quick Start

### Prerequisites

- **Claude Code** installed ([claude.ai](https://claude.ai)) — requires a paid Anthropic plan
- **`jq`** — command-line JSON processor (hooks depend on it)

```bash
# Verify installations
claude --version
jq --version
```

### Install

```bash
cd /path/to/your/project

# Copy Kloudify into your project root
cp -r /path/to/kloudify-download/* .
cp -r /path/to/kloudify-download/.claude .
```

> **Note:** If you already have a `.claude/` directory, merge manually — don't overwrite existing settings or memory.

### Onboard

Launch Claude Code:

```bash
claude
```

Kloudify detects `__NEEDS_ONBOARD` and automatically runs the onboarding wizard. It will:

1. Scan your project structure, languages, and frameworks
2. Generate project profile files
3. Ask you a few questions to tailor the system
4. Configure commit identity, memory, and preferences
5. Run `/start` to begin your first session

No manual prompt needed. That's it. You're running.

---

## Project Structure

```
your-project/
├── CLAUDE.md                    # System instructions (Claude reads this first)
├── CLAUDE.local.md              # Personal overrides (gitignored)
├── Task Board.md                # Kanban-style task tracking
├── Scratchpad.md                # Quick capture (processed during /sync)
├── Daily Notes/                 # Chronological session history
├── ai-operations-registry/      # AI traceability (optional — copy from template/)
│
└── .claude/
    ├── memory.md                # Active session context (<100 lines)
    ├── knowledge-base.md        # System-wide learned rules (auditor-gated)
    ├── knowledge-nominations.md # Candidate learnings pipeline
    ├── command-index.md         # Full command catalog
    ├── settings.json            # Hook configuration
    ├── project-stack.md         # Auto-generated: runtimes, dependencies
    ├── project-structure.md     # Auto-generated: directory tree
    │
    ├── agents/                  # 9 specialist subagents
    │   ├── auditor.md           #   Quality gate — reviews all work
    │   ├── unsticker.md         #   Unblocks you when stuck
    │   ├── error-whisperer.md   #   Translates cryptic errors into fixes
    │   ├── rubber-duck.md       #   Socratic debugging
    │   ├── pr-ghostwriter.md    #   Writes PR descriptions & changelogs
    │   ├── yak-shave-detector.md#   Catches scope creep
    │   ├── debt-collector.md    #   Tracks and prioritises tech debt
    │   ├── onboarding-sherpa.md #   Learns new codebases fast
    │   └── archaeologist.md     #   Excavates why code exists
    │
    ├── commands/                # Workflow commands
    │   ├── start.md             #   Begin work session
    │   ├── sync.md              #   Mid-day refresh
    │   ├── wrap-up.md           #   End-of-day ritual
    │   ├── clear.md             #   Flush context, resume fresh
    │   ├── audit.md             #   Quality review
    │   ├── review.md            #   Deep code review
    │   ├── deep-audit.md        #   Full project audit (6 specialist analysts)
    │   ├── brainstorm-session.md#   Isolated idea mode
    │   ├── unstick.md           #   Get unstuck
    │   ├── onboard.md           #   Scan new codebase
    │   ├── report.md            #   Professional report
    │   ├── release.md           #   Release notes
    │   ├── handoff.md           #   Session handoff
    │   ├── autoresearch.md      #   Autonomous iteration loops
    │   └── ...                  #   + more
    │
    ├── hooks/                   # Automated safety hooks
    │   ├── guard-bash.sh        #   Blocks dangerous shell commands
    │   ├── backup-before-write.sh#  Backs up files before overwrites
    │   ├── completeness-gate.sh #   Validates content completeness
    │   ├── log-changes.sh       #   Logs all file modifications
    │   ├── log-failures.sh      #   Logs tool failures
    │   ├── log-stop-verdict.sh  #   Logs session verdicts
    │   ├── pre-compact-handoff.sh#  Saves state before auto-compaction
    │   ├── post-compact-resume.sh#  Restores context after compaction
    │   ├── session-reset.sh     #   Resets stale gate files
    │   └── update-project-stack.sh# Tracks structural file changes
    │
    ├── skills/                  # On-demand skill generation
    │   ├── _generator/          #   Template + manifests
    │   └── ...                  #   Generated skill files (on demand)
    │
    ├── plans/                   # Architecture plans and designs
    ├── reports/                 # Audit reports (generated by /deep-audit)
    ├── agent-memory/            # Per-agent persistent knowledge
    ├── backups/                 # Automatic file backups
    └── logs/                    # Audit trail & incident log
```

---

## Daily Workflow

```
Morning:    /start → work → /sync (if switching tasks)
Afternoon:  work → /clear (if context gets heavy) → work
Evening:    /wrap-up
Weekly:     /retro (Friday)
Periodic:   /deep-audit (monthly or after major refactors)
```

---

## Commands

### Daily Rituals

| Command | Description |
|---|---|
| `/start` | Begin work session — load memory, create daily note, security checks (npm + pip audit) |
| `/sync` | Mid-day refresh — update memory, process scratchpad |
| `/wrap-up` | End of day — audit, knowledge externalization, project profile refresh, prep tomorrow |
| `/standup` | Quick standup — yesterday/today/blockers from git + tasks |
| `/clear` | Flush context and resume fresh (use between unrelated tasks) |
| `/brainstorm-session [idea]` | Isolated idea mode — discuss, evaluate, promote to Task Board |

### Quality & Review

| Command | Description |
|---|---|
| `/audit [scope]` | Quality review via the auditor agent |
| `/review [target]` | Deep code review — security + performance + architecture |
| `/deep-audit` | Full project audit — 6 specialist analysts in parallel, PASS/WARN/FAIL report |
| `/system-audit` | Infrastructure health check of the Kloudify system itself |
| `/drift-detect` | Detect config drift — stale rules, contradictions, orphans |
| `/retro [period]` | Sprint retrospective — analyze patterns, improve process |
| `/debt-map [dir]` | Map and prioritise technical debt |

### Problem Solving

| Command | Description |
|---|---|
| `/unstick [problem]` | Root-cause analysis when you're stuck |
| `/onboard [project]` | Scan and learn an unfamiliar codebase |

### Planning & Strategy

| Command | Description |
|---|---|
| `/competitive-intel [market]` | Deep competitive analysis |

### Communication & Delivery

| Command | Description |
|---|---|
| `/report [topic]` | Professional, audience-aware report |
| `/release [version]` | Auto-generate release notes |
| `/handoff [recipient]` | Structured context handoff |

### Autonomous Loops (Autoresearch)

| Command | Description |
|---|---|
| `/autoresearch [goal]` | Autonomous iteration loop — modify, verify, keep/discard |
| `/autoresearch:debug` | Scientific bug-hunting until root cause found |
| `/autoresearch:fix` | Iterative fix loop until zero errors |
| `/autoresearch:security [scope]` | STRIDE + OWASP + red-team personas |
| `/autoresearch:predict [scope]` | 5-persona architectural risk swarm |
| `/autoresearch:scenario [seed]` | 12-dimension edge case generator |
| `/autoresearch:ship [target]` | Universal shipping checklist |
| `/autoresearch:learn` | Scout → generate/update docs → validate cycle |

### System Building

| Command | Description |
|---|---|
| `/playbook [name]` | Record a workflow → auto-generate a reusable command |
| `/scaffold-cli [binary]` | Design a CLI tool spec-first with OpenCLI |
| `/generate-skills [category]` | Generate skill files on demand from manifests |

### Planned

| Command | Description |
|---|---|
| `/implement [feature]` | Multi-agent feature development — auto-profiles project, assigns parametric roles, builds + reviews |
| `/council [topic]` | Multi-perspective deliberation — dual-mode: subagents or real sessions via claude-peers-mcp |

---

## Memory Architecture

Kloudify uses a 6-tier memory system so context survives across sessions:

```
Tier 1 │ memory.md              → Active session context (what's happening now)
Tier 2 │ Agent Memory            → Per-agent persistent knowledge across sessions
Tier 3 │ Knowledge Base          → System-wide learned rules (auditor-gated)
Tier 4 │ Knowledge Nominations   → Candidate learnings pipeline
Tier 5 │ MCP Knowledge Graph     → Structured entities and relations (optional)
Tier 6 │ Daily Notes             → Chronological session history and handoffs
```

The **self-improvement loop**:

1. Claude (or an agent) observes a pattern or lesson during work
2. It writes a **knowledge nomination**
3. The **auditor agent** reviews nominations during `/audit` or `/wrap-up`
4. Confirmed learnings are **promoted** to the knowledge base
5. All agents and sessions read the knowledge base at startup → system improves

---

## Project Profiling

Kloudify automatically tracks your project's stack and structure:

- **`.claude/project-stack.md`** — Runtimes, dependencies, Docker files, config files. Updated by a PostToolUse hook whenever structural files change (package.json, requirements.txt, Dockerfile, etc.)
- **`.claude/project-structure.md`** — Directory tree (depth 4) + file counts by extension. Regenerated at every `/wrap-up`.

These files feed into `/deep-audit` and `/implement` so agents always know your stack without expensive re-scanning.

---

## Safety Hooks

Hooks run automatically — no user action needed:

| Hook | Trigger | What it does |
|---|---|---|
| `guard-bash.sh` | Before any shell command | Blocks destructive commands (`rm -rf /`, `DROP TABLE`, etc.) |
| `backup-before-write.sh` | Before any file write/edit | Creates a backup copy in `.claude/backups/` |
| `completeness-gate.sh` | Before writing system files | Validates: no TBDs, max line limits, valid JSON, provenance tags |
| `log-changes.sh` | After file write/edit | Appends to the audit trail |
| `update-project-stack.sh` | After writing structural files | Regenerates project stack profile |
| `log-failures.sh` | After any tool failure | Logs errors for pattern analysis |
| `log-stop-verdict.sh` | When session ends | Logs task completion verdict |
| `pre-compact-handoff.sh` | Before auto-compaction | Saves session state so nothing is lost |
| `post-compact-resume.sh` | After auto-compaction | Restores context seamlessly |
| `session-reset.sh` | On fresh session start | Resets stale gate files |

---

## Skills

Kloudify uses a **generator approach** — no pre-built library of thousands of identical files.

- **Manifests** (`.claude/skills/_generator/manifests/`) define skill categories and capabilities
- **Template** (`.claude/skills/_generator/SKILL.template.md`) provides the standard structure
- **`/generate-skills [category]`** produces focused skill files on demand

This keeps the system lean. Generate what you need, when you need it.

Categories cover: Development, AI/ML, DevOps, Security, Marketing, Design, Data, and 25+ more.

---

## AI Operations Registry (Optional)

For projects with AI agents, Kloudify includes a traceability framework:

```
ai-operations-registry/
├── template/                  # Copy these into your project and fill placeholders
│   ├── README.md              # Index + principles
│   ├── architecture-map.md    # Agent hierarchy + mental map
│   ├── decision-chain.md      # Request → result flow
│   ├── processes.md           # Active + planned processes
│   ├── traceability.md        # Event → log mapping
│   ├── escalation.md          # Escalation tree + HITL levels
│   └── gaps.md                # Known traceability gaps
```

Set up: copy `template/` contents to `ai-operations-registry/`, replace `{{placeholders}}`, and the wrap-up (Step 6d, Fridays) will keep them in sync with your code.

---

## Agents

| Agent | Role |
|---|---|
| **Auditor** | Quality gate. Reviews all work, promotes knowledge, proposes SOP revisions |
| **Unsticker** | Unblocks you when stuck. Root-cause analysis with fresh approaches |
| **Error Whisperer** | Translates cryptic errors into fixes. Pattern matching across sessions |
| **Rubber Duck** | Forces you to articulate the real problem. Socratic debugging |
| **PR Ghostwriter** | Writes PR descriptions, commit messages, and changelogs from diffs |
| **Yak-Shave Detector** | Catches scope creep. "You started doing X but now you're doing Y" |
| **Debt Collector** | Tracks tech debt. Catalogues shortcuts, suggests when to pay down |
| **Onboarding Sherpa** | Learns new codebases fast. Architecture maps, key-file identification |
| **Archaeologist** | Excavates *why* code exists. Git blame + context reconstruction |

---

## Tips

1. **Run `/clear` between unrelated tasks.** Context pollution is the #1 quality killer.
2. **Keep `memory.md` under 100 lines.** Prune aggressively.
3. **Let the knowledge base grow naturally.** Don't pre-fill it — let the auditor promote real learnings.
4. **Trust the hooks.** They catch what instructions miss.
5. **Try `/unstick` when you're blocked.** It's better than spinning.
6. **Run `/deep-audit` monthly.** It catches drift before it becomes debt.
7. **Generate skills as needed.** Don't generate everything upfront — context budget matters.

---

## Support

Open an issue on [GitHub](https://github.com/GravyaDev/kloudify/issues)

---

<p align="center">
  <em>Built by <a href="https://github.com/GravyaDev">GravyaDev</a></em>
</p>
