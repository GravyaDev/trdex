# Kloudify — Quick Start

You're 3 steps from a production-grade Claude Code system.

---

## 1. Install Claude Code

Skip this if you already have Claude Code installed (`claude --version` to check).

```bash
# Mac / Linux / WSL
curl -fsSL https://claude.ai/install.sh | bash

# Windows PowerShell
irm https://claude.ai/install.ps1 | iex
```

Requires a paid Anthropic plan (Pro $20/mo, Max $100-200/mo, or Teams/Enterprise).

> **Heads up:** If you have an `ANTHROPIC_API_KEY` environment variable set, Claude Code bills to your API account instead of your subscription. Run `unset ANTHROPIC_API_KEY` if that's not what you want.

> **Prerequisite:** The safety hooks require `jq` (a command-line JSON processor). Install it if you don't have it:
> ```bash
> # Mac
> brew install jq
>
> # Ubuntu / Debian
> sudo apt-get install jq
>
> # Windows (via Chocolatey)
> choco install jq
> ```
> Verify with `jq --version`. Without `jq`, hooks will still run but safety checks (backup verification, completeness gates, dangerous command blocking) will silently skip.

## 2. Copy files into your project

Unzip and copy everything into your project root:

```bash
cd /path/to/your/project
cp -r /path/to/kloudify-download/* .
cp -r /path/to/kloudify-download/.claude .
```

This adds the `.claude/` system directory, `CLAUDE.md`, `Task Board.md`, `Scratchpad.md`, and `Daily Notes/`.

If you already have a `.claude/` directory, merge manually — don't overwrite your existing settings or memory.

## 3. Start Claude Code and run the onboarding prompt

```bash
claude
```

Then paste the onboarding prompt below. This tells Claude to scan your project, adopt the Kloudify system, and configure everything for your specific setup.

---

## Onboarding Prompt (copy and paste this into Claude Code)

```
I just installed the Kloudify operating system into this project. The system files are in .claude/ and the main instructions are in CLAUDE.md.

Please do the following:

1. Read CLAUDE.md to understand the full system architecture.
2. Read .claude/memory.md and .claude/knowledge-base.md.
3. Read .claude/command-index.md to learn all available commands.
4. Scan my project structure (files, folders, language, framework, dependencies).
5. Based on what you find, generate the project profile files:
   - .claude/project-stack.md (runtimes, dependencies, Docker, config)
   - .claude/project-structure.md (directory tree + file counts)
6. Show me a summary of what you detected.
7. Then ask me a few smart questions to tailor the system to my needs:
   - What are my main goals with this project?
   - What does my typical workflow look like?
   - What tasks do I spend the most time on (or want to automate)?
   - Are there any tools, platforms, or services I use regularly?
8. Based on my answers and your scan, update memory.md with:
   - Project name and description
   - Language/framework/build tool
   - Key file paths
   - Any patterns you noticed
   - My goals and workflow preferences
9. Run /start to initialise the daily workflow.

Scan first, then ask questions — don't wait for me before doing the initial scan.
```

---

## What you just installed

### Memory & Context (6-layer)
Claude remembers context across sessions, learns from mistakes, and gets better over time. Memory tiers: active session → agent memory → knowledge rules → semantic search → entity graph → session logs.

### 9 Specialist Agents
Auditor (quality gate), Unsticker, Error Whisperer, Rubber Duck, PR Ghostwriter, Yak-Shave Detector, Debt Collector, Onboarding Sherpa, Archaeologist. They run automatically via commands — no manual configuration.

### Commands
Workflow rituals and utilities. Type them in Claude Code and the system handles the rest. See the full list below.

### Skills (on-demand, not pre-generated)
Skills are domain knowledge loaded when needed. Kloudify uses a **generator approach**: a template + manifests produce skill files on demand via `/generate-skills`. No bloated skill library — generate what you need, when you need it.

Categories cover: Development, AI/ML, DevOps, Security, Marketing, Design, Data, and more. Each skill is a focused prompt that gives Claude deep expertise in a specific domain.

### Automated Safety (hooks)
Deterministic checks that run every time: blocks dangerous shell commands, backs up files before overwriting, catches incomplete content, logs all changes. Plus automatic project stack tracking when structural files (package.json, Dockerfile, etc.) change.

### Self-Improvement Engine
Claude observes patterns, nominates learnings, and the auditor promotes confirmed rules to the knowledge base. Your system gets smarter the more you use it.

### Project Profile (auto-generated)
Two files maintained automatically:
- `.claude/project-stack.md` — runtimes, dependencies, Docker, config files (updated on structural file changes)
- `.claude/project-structure.md` — directory tree + file counts (updated at wrap-up)

These feed into `/deep-audit` and `/implement` so agents always know your project's stack without expensive re-scanning.

---

## Daily workflow

```
Morning:    /start → work → /sync (if switching tasks)
Afternoon:  work → /clear (if context gets heavy) → work
Evening:    /wrap-up
Weekly:     /retro (Friday)
Periodic:   /deep-audit (monthly or after major refactors)
```

## Commands

### Daily Rituals

| Command | When to use |
|---|---|
| `/start` | Beginning of a work session — loads memory, creates daily note, runs security checks |
| `/sync` | Mid-session to refresh context and process scratchpad |
| `/wrap-up` | End of session — audit, knowledge externalization, project profile refresh |
| `/standup` | Quick daily standup from git + tasks |
| `/clear` | Between unrelated tasks or when quality drops |
| `/brainstorm-session [idea]` | Isolated idea mode — discuss, evaluate, promote to Task Board |

### Quality & Review

| Command | When to use |
|---|---|
| `/audit [scope]` | After completing something important — quality gate |
| `/review [target]` | Deep code review (security + performance + architecture) on file/PR/diff |
| `/deep-audit` | Full project audit — 6 specialist analysts in parallel, PASS/WARN/FAIL report |
| `/system-audit` | Deep infrastructure health check of the Kloudify system itself |
| `/drift-detect` | Detect config drift — stale rules, contradictions, orphaned files |
| `/retro [period]` | Sprint retrospective — analyze patterns, improve process |
| `/debt-map [dir]` | Map and prioritise technical debt across codebase |

### Problem Solving

| Command | When to use |
|---|---|
| `/unstick [problem]` | When stuck on a problem 10+ min — root-cause analysis |
| `/onboard [project]` | Scan a new codebase for orientation |

### Planning & Strategy

| Command | When to use |
|---|---|
| `/competitive-intel [market]` | Deep competitive analysis with strategic recommendations |

### Communication & Delivery

| Command | When to use |
|---|---|
| `/report [topic]` | Generate audience-aware professional report |
| `/release [version]` | Auto-generate release notes (technical + marketing + executive) |
| `/handoff [recipient]` | Structured session handoff with full context |

### Autoresearch (Autonomous Loops)

| Command | When to use |
|---|---|
| `/autoresearch [goal]` | Autonomous iteration loop with measurable metric |
| `/autoresearch:debug` | Scientific bug-hunting loop |
| `/autoresearch:fix` | Iterative fix loop until zero errors |
| `/autoresearch:security` | STRIDE + OWASP + red-team personas |
| `/autoresearch:predict` | 5-persona risk swarm |
| `/autoresearch:scenario` | 12-dimension edge case generator |
| `/autoresearch:ship` | Universal shipping checklist |
| `/autoresearch:learn` | Scout + generate/update docs |

### System Building

| Command | When to use |
|---|---|
| `/playbook [name]` | Record a workflow and auto-generate a reusable command |
| `/scaffold-cli [binary]` | Design CLI spec-first with OpenCLI |
| `/generate-skills [category]` | Generate skill files on demand from manifests |

### Planned (not yet available)

| Command | Description |
|---|---|
| `/implement [feature]` | Multi-agent feature development — auto-profiles project, assigns roles, builds + reviews |
| `/council [topic]` | Multi-perspective deliberation — dual-mode (subagents or real sessions via claude-peers-mcp) |

---

## Key Files

| File | Purpose |
|---|---|
| `CLAUDE.md` | Main instructions — Claude reads this first |
| `.claude/memory.md` | Active session context |
| `.claude/knowledge-base.md` | Validated rules (auditor-gated) |
| `Task Board.md` | Task tracking |
| `Scratchpad.md` | Quick capture (processed at /sync, cleared at /wrap-up) |
| `Daily Notes/` | Chronological session history |
| `.claude/command-index.md` | Full command catalog with triggers |
| `.claude/settings.json` | Hooks and automation config |
| `.claude/project-stack.md` | Auto-generated: runtimes, dependencies |
| `.claude/project-structure.md` | Auto-generated: directory tree |
| `AI Operations Registry/` | AI traceability: processes, escalation, gaps (if applicable) |

## FAQ

**Do I need to know how to code?**
No. Everything is plain English.

**Does this work with any project?**
Yes — any language, framework, or structure. The onboarding prompt adapts automatically. The project profile system detects your stack and configures agents accordingly.

**What about skills — are there thousands of pre-built ones?**
No. Kloudify uses a generator approach. Skill manifests define categories and capabilities; `/generate-skills` produces focused skill files on demand. This keeps the system lean — no 1,700 identical boilerplate files.

**How do I update?**
Re-download from your purchase link, or run `npx create-kloudify update` if you prefer the CLI.

## Tips

1. **Run `/clear` between unrelated tasks.** Context pollution is the #1 quality killer.
2. **Keep memory.md under 100 lines.** Prune aggressively.
3. **Let the knowledge base grow naturally.** Don't pre-fill it — let the auditor promote real learnings.
4. **Trust the hooks.** They catch what instructions miss.
5. **Try `/unstick` when you're blocked.** It's better than spinning.
6. **Run `/deep-audit` monthly.** It catches drift before it becomes debt.
7. **Generate skills as needed.** Don't generate everything upfront — context budget matters.
