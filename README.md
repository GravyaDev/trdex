# Kloudify

**A professional operating system for Claude Code.**

Kloudify transforms Claude Code from a powerful AI assistant into a persistent, self-improving development partner. It adds structured memory, specialist agents, automated safety hooks, and 1,700+ professional skills — all orchestrated through simple slash commands.

---

## ✨ Highlights

| Feature | What it does |
|---|---|
| **6-tier memory** | Claude remembers context across sessions, learns from mistakes, and gets smarter over time |
| **9 specialist agents** | Purpose-built subagents for quality, debugging, code review, onboarding, and more |
| **25+ commands** | Workflow rituals (`/start`, `/sync`, `/wrap-up`) plus tools for planning, review, and delivery |
| **1,727 skills** | Professional operational procedures across 31 categories — from marketing to DevOps |
| **10 automated hooks** | Deterministic safety nets: dangerous command blocking, file backup, completeness gates, full audit trail |
| **Self-improvement engine** | Knowledge nominations → auditor review → promoted rules. The system gets better the more you use it |

---

## 🚀 Quick Start

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
cp -r /path/to/Kloudify-download/* .
cp -r /path/to/Kloudify-download/.claude .
```

> **Note:** If you already have a `.claude/` directory, merge manually — don't overwrite existing settings or memory.

### Onboard

Launch Claude Code and paste the onboarding prompt:

```bash
claude
```

```
I just installed the Kloudify operating system into this project.
The system files are in .claude/ and the main instructions are in CLAUDE.md.

Please do the following:
1. Read CLAUDE.md to understand the full system architecture.
2. Read .claude/memory.md and .claude/knowledge-base.md.
3. Read .claude/command-index.md to learn all available commands.
4. Scan my project structure (files, folders, language, framework, dependencies).
5. Show me a summary of what you detected.
6. Ask me a few smart questions to tailor the system to my needs.
7. Based on my answers and your scan, update memory.md.
8. Review the skills in .claude/skills/ — recommend the most relevant ones.
9. Run /start to initialise the daily workflow.
```

That's it. You're running.

---

## 📁 Project Structure

```
your-project/
├── CLAUDE.md                    # System instructions (Claude reads this first)
├── CLAUDE.local.md              # Personal overrides (gitignored)
├── Task Board.md                # Kanban-style task tracking
├── Scratchpad.md                # Quick capture (processed during /sync)
├── Daily Notes/                 # Chronological session history
│
└── .claude/
    ├── memory.md                # Active session context (<100 lines)
    ├── knowledge-base.md        # System-wide learned rules (auditor-gated)
    ├── knowledge-nominations.md # Candidate learnings pipeline
    ├── command-index.md         # Full command catalog
    ├── settings.json            # Hook configuration
    ├── Kloudify.ocli.yaml       # OpenCLI specification
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
    ├── teams/                   # Reusable team modules
    │   └── dev-team/            # Code review & architecture team (7 agents)
    │       ├── agents/          #   Framework-agnostic specialists
    │       ├── PROJECT_CONTEXT.template.md
    │       ├── TEAM.md
    │       └── context/         #   Inter-agent communication files
    │
    ├── commands/                # 25 workflow commands
    │   ├── start.md             #   Begin work session
    │   ├── sync.md              #   Mid-day refresh
    │   ├── wrap-up.md           #   End-of-day ritual
    │   ├── clear.md             #   Flush context, resume fresh
    │   ├── audit.md             #   Quality review
    │   ├── review.md            #   Deep code review
    │   ├── unstick.md           #   Get unstuck
    │   ├── onboard.md           #   Scan new codebase
    │   ├── brief.md             #   Idea → project brief
    │   ├── launch.md            #   Full launch pipeline
    │   ├── proposal.md          #   Client proposal generator
    │   ├── report.md            #   Professional report
    │   ├── release.md           #   Release notes
    │   ├── handoff.md           #   Session handoff
    │   ├── retro.md             #   Sprint retrospective
    │   ├── autoresearch.md      #   Autonomous iteration loops
    │   └── ...                  #   + more
    │
    ├── hooks/                   # 10 automated safety hooks
    │   ├── guard-bash.sh        #   Blocks dangerous shell commands
    │   ├── backup-before-write.sh#  Backs up files before overwrites
    │   ├── completeness-gate.sh #   Validates content completeness
    │   ├── log-changes.sh       #   Logs all file modifications
    │   ├── log-failures.sh      #   Logs tool failures
    │   ├── log-stop-verdict.sh  #   Logs session verdicts
    │   ├── pre-compact-handoff.sh#  Saves state before auto-compaction
    │   ├── post-compact-resume.sh#  Restores context after compaction
    │   ├── session-reset.sh     #   Resets stale gate files
    │   └── validate-ocli-spec.sh#   Validates OpenCLI specifications
    │
    ├── skills/                  # 1,727+ professional skills
    │   └── INDEX.md             #   Full skill catalog
    │
    ├── agent-memory/            # Per-agent persistent knowledge (gitignored)
    ├── backups/                 # Automatic file backups (gitignored)
    └── logs/                    # Audit trail & incident log (gitignored)
```

---

## ⚡ Daily Workflow

```
Morning:    /start → work → /sync (if switching tasks)
Afternoon:  work → /clear (if context gets heavy) → work
Evening:    /wrap-up
```

---

## 👥 Dev-Team Module — Reusable Code Review & Architecture Team

The `teams/dev-team/` module is a **framework-agnostic team of 7 specialist agents** for code review, architecture, and full-stack development.

### What's Included

```
.claude/teams/dev-team/
├── agents/                           # 7 framework-agnostic agents
│   ├── task-decomposer.md           # Feature decomposition specialist
│   ├── backend-architect.md         # API & service boundary design
│   ├── database-architect.md        # Schema design & migrations
│   ├── fullstack-developer.md       # Adapts to any backend/frontend
│   ├── python-ai-developer.md       # LangGraph, LiteLLM, async Python
│   ├── code-reviewer.md             # Security, performance, correctness
│   └── architect-review.md          # SOLID, dependencies, boundaries
├── PROJECT_CONTEXT.template.md      # Template for project customization
├── TEAM.md                          # Team description & workflow
└── context/
    ├── README.md                    # Inter-agent communication convention
    ├── current-feature.md           # Active feature (created by task-decomposer)
    ├── architecture.md              # Design decisions (created by architects)
    └── review-notes.md              # Code review findings
```

### Quick Start — Using Dev-Team on a New Project

1. **Clone Kloudify into your project**:
   ```bash
   git clone https://github.com/GravyaDev/Kloudify.git
   # Copy into your project
   cp -r Kloudify/.claude .
   ```

2. **Compile PROJECT_CONTEXT.md for your project**:
   ```bash
   cp .claude/teams/dev-team/PROJECT_CONTEXT.template.md \
      .claude/teams/dev-team/PROJECT_CONTEXT.md

   # Edit PROJECT_CONTEXT.md with your stack:
   # - Backend framework (Express, FastAPI, Rails, etc.)
   # - Frontend framework (React, Vue, Next.js, etc.)
   # - Database & ORM
   # - AI architecture (if using LangGraph/LiteLLM)
   # - Directory structure
   # - Development commands
   # - Project-specific patterns & conventions
   ```

3. **Symlink agents to the canonical Kloudify copy** (keeps agents in sync):
   ```bash
   ln -s ../../path/to/Kloudify/.claude/teams/dev-team/agents \
         .claude/teams/dev-team/agents
   ```

4. **Use the `/team` command**:
   ```bash
   /team decompose "implement Google Ads integration"
   /team architect "implement Google Ads integration"
   /team python "implement Google Ads integration"
   /team review                    # Review current code changes
   /team build "implement..."      # Full workflow: decompose → architect → build → review
   ```

### How It Works

The team communicates via **file-based context**, not fragile JSON:

1. User requests a feature
2. **task-decomposer** → reads `PROJECT_CONTEXT.md` → writes `context/current-feature.md` (atomic tasks with deps)
3. **backend-architect** + **database-architect** → read feature scope → write `context/architecture.md`
4. **fullstack-developer** or **python-ai-developer** → read architecture → implement
5. **code-reviewer** + **architect-review** → write `context/review-notes.md`
6. Developer → fix issues → delete review notes → create PR

### Why This Works

- **Framework-agnostic**: Same agents work on Express/Django/Rails, React/Vue, PostgreSQL/MongoDB
- **Project-specific**: Each project compiles `PROJECT_CONTEXT.md` with its stack, patterns, conventions
- **Single source of truth**: Agent definitions live in Kloudify — all projects stay in sync
- **Human-readable**: All communication is Markdown, no JSON serialization bugs
- **Reusable**: Copy Kloudify once, symlink agents, customize via PROJECT_CONTEXT.md

### Example: PROJECT_CONTEXT.md Sections

```markdown
# Project Context — Your Project Name

## Stack
- Backend: Express.js + Node.js 20
- Frontend: React 19 SPA
- Database: PostgreSQL 17 + pgvector
- AI Layer: LangGraph + LiteLLM + Voyage AI
- Auth: BetterAuth + JWT
- ORM: Drizzle

## Struttura directory chiave
- Backend: `./app/services/`
- Frontend: `./app/src/`
- Database: `./app/db/`
- AI Service: `./services/agents/src/`

## Pattern specifici
- Table prefix: `gravya_`
- Supervisor > Executors architecture
- Co-author: Kloud <kloud@gravya.it>
- Memory: 6-tier system (pinned docs → agent memory → knowledge base → semantic search → knowledge graph → session logs)

## Comandi di sviluppo
- Dev: `pnpm dev`
- Test: `pnpm test`
- Migrate: `pnpm migrate:dev`
- Build: `pnpm build`
```

---

## 🔧 Commands

### Daily Rituals

| Command | Description |
|---|---|
| `/start` | Begin work session — load memory, create daily note, review tasks |
| `/sync` | Mid-day refresh — update memory, process scratchpad |
| `/wrap-up` | End of day — audit, externalize knowledge, prep tomorrow |
| `/standup` | Quick standup — yesterday/today/blockers from git + tasks |
| `/clear` | Flush context and resume fresh (use between unrelated tasks) |

### Quality & Review

| Command | Description |
|---|---|
| `/audit [scope]` | Quality review via the auditor agent |
| `/review [target]` | Deep code review — security + performance + architecture |
| `/system-audit` | Full infrastructure health check |
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
| `/brief [idea]` | Turn a rough idea into a structured project brief |
| `/launch [product]` | Full launch pipeline — competitive scan to GTM checklist |
| `/proposal [project]` | Generate a client proposal with scope and pricing |
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
| `/autoresearch:security [scope]` | STRIDE + OWASP + 4 red-team personas |
| `/autoresearch:predict [scope]` | 5-persona architectural swarm |
| `/autoresearch:scenario [seed]` | 12-dimension edge case generator |
| `/autoresearch:ship [target]` | 8-phase universal shipping checklist |
| `/autoresearch:learn` | Scout → generate/update docs → validate cycle |

### System Building

| Command | Description |
|---|---|
| `/playbook [name]` | Record a workflow → auto-generate a reusable command |
| `/scaffold-cli [binary]` | Design a CLI tool spec-first with OpenCLI |
| `/generate-skills` | Generate skill files from the manifest |

---

## 🧠 Memory Architecture

Kloudify uses a 6-tier memory system so context survives across sessions:

```
Tier 1 │ memory.md              → Active session context (what's happening now)
Tier 2 │ Agent Memory            → Per-agent persistent knowledge across sessions
Tier 3 │ Knowledge Base          → System-wide learned rules (auditor-gated)
Tier 4 │ Knowledge Nominations   → Candidate learnings pipeline
Tier 5 │ MCP Knowledge Graph     → Structured entities and relations (optional)
Tier 6 │ Daily Notes             → Chronological session history and handoffs
```

The **self-improvement loop** works like this:

1. Claude (or an agent) observes a pattern or lesson during work
2. It writes a **knowledge nomination**
3. The **auditor agent** reviews nominations during `/audit` or `/wrap-up`
4. Confirmed learnings are **promoted** to the knowledge base
5. All agents and sessions read the knowledge base at startup → system improves

---

## 🛡️ Safety Hooks

Hooks run automatically — no user action needed. They enforce safety at the tool level:

| Hook | Trigger | What it does |
|---|---|---|
| `guard-bash.sh` | Before any shell command | Blocks destructive commands (`rm -rf /`, `DROP TABLE`, etc.) |
| `backup-before-write.sh` | Before any file write/edit | Creates a backup copy in `.claude/backups/` |
| `completeness-gate.sh` | Before writing system files | Validates: no TBDs, max line limits, valid JSON, provenance tags |
| `log-changes.sh` | After file write/edit | Appends to the audit trail |
| `log-failures.sh` | After any tool failure | Logs errors for pattern analysis |
| `log-stop-verdict.sh` | When session ends | Logs task completion verdict |
| `pre-compact-handoff.sh` | Before auto-compaction | Saves session state so nothing is lost |
| `post-compact-resume.sh` | After auto-compaction | Restores context seamlessly |
| `session-reset.sh` | On fresh session start | Resets stale gate files |
| `validate-ocli-spec.sh` | After writing YAML specs | Validates OpenCLI specification format |

---

## 📚 Skills Library

1,727+ skills across 31 professional categories:

| Category | Count | | Category | Count |
|---|---|---|---|---|
| Marketing & Advertising | 76 | | Content & Copywriting | 88 |
| Social Media | 69 | | SEO & Search | 57 |
| Sales & Revenue | 66 | | Email Marketing | 51 |
| Finance & Accounting | 60 | | Legal & Compliance | 54 |
| Operations & PM | 60 | | HR & People | 57 |
| Product Management | 63 | | Software Development | 78 |
| Data & Analytics | 57 | | E-commerce | 54 |
| Customer Success | 48 | | Startup & Entrepreneurship | 60 |
| Education & Training | 51 | | Real Estate | 45 |
| Healthcare | 48 | | Travel & Hospitality | 54 |
| Design & Creative | 54 | | Consulting & Strategy | 54 |
| Personal Productivity | 57 | | AI & Automation | 54 |
| Nonprofit & Social Impact | 48 | | Media & Publishing | 45 |
| Construction & Trades | 42 | | Food & Beverage | 42 |
| Fitness & Wellness | 45 | | Agriculture & Farming | 45 |
| Energy & Sustainability | 45 | | | |

Skills are invoked automatically when Claude detects a relevant task, or manually with `Use the [skill-name] skill to...`

---

## 🤖 Agents

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

## 🔌 MCP Integrations

Kloudify ships with two MCP servers pre-configured in `.mcp.json`:

- **Context7** — Live library documentation (Next.js, React, any npm package) via `@upstash/context7-mcp`
- **Memory** — Persistent knowledge graph for cross-session facts via `@modelcontextprotocol/server-memory`

---

## 💡 Tips

1. **Run `/clear` between unrelated tasks.** Context pollution is the #1 quality killer.
2. **Keep `memory.md` under 100 lines.** Prune aggressively.
3. **Let the knowledge base grow naturally.** Don't pre-fill it — let the auditor promote real learnings.
4. **Trust the hooks.** They catch what instructions miss.
5. **Try `/unstick` when you're blocked.** It's better than spinning.
6. **No code required.** Everything is plain English — Kloudify works with any language, framework, or project.

---

## 📬 Support

Open an issue on [GitHub](https://github.com/GravyaDev/Kloudify/issues)

---

<p align="center">
  <em>Built by <a href="https://github.com/GravyaDev">GravyaDev</a></em>
</p>
