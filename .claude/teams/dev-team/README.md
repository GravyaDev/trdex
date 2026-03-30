# Dev Team — Reusable Code Review & Architecture Module

Professional team of specialized AI agents for code review, architectural analysis, and implementation planning.

## Quick Start

This module is self-contained and reusable across projects.

### For a new project:

1. Copy `.claude/teams/dev-team/` to your project's `.claude/teams/dev-team/`
2. Copy `.claude/commands/team.md` to your project's `.claude/commands/team.md` (see `commands/` in claudify root)
3. Create `PROJECT_CONTEXT.md` in `.claude/teams/dev-team/`:
   ```bash
   cp .claude/teams/dev-team/PROJECT_CONTEXT.template.md .claude/teams/dev-team/PROJECT_CONTEXT.md
   # Then edit PROJECT_CONTEXT.md with your project's stack, directory structure, patterns
   ```
4. Use `/team` commands:
   - `/team decompose [feature]` — break down tasks
   - `/team architect [feature]` — design API + DB
   - `/team review` — code review
   - `/team python [feature]` — AI/Python implementation
   - `/team build [feature]` — full workflow

## Agents

| Agent | Role | Tools |
|-------|------|-------|
| `task-decomposer` | Break complex features into atomic tasks | Read, Write, Edit, Glob, Grep, Bash |
| `backend-architect` | Design APIs, service boundaries, patterns | Read, Write, Edit, Bash, Grep, Glob |
| `database-architect` | Schema design, migrations, performance | Read, Write, Edit, Bash, Grep, Glob |
| `fullstack-developer` | Implement full-stack features (framework-agnostic) | Read, Write, Edit, Bash, Glob, Grep |
| `python-ai-developer` | LangGraph, LiteLLM, async Python, FastAPI | Read, Write, Edit, Bash, Glob, Grep |
| `code-reviewer` | Security, performance, correctness review | Read, Grep, Glob, Bash |
| `architect-review` | SOLID principles, dependencies, boundaries | Read, Grep, Glob |

## Context System

Agents communicate via file-based convention in `.claude/teams/dev-team/context/`:

- `current-feature.md` — Task decomposition output (from task-decomposer)
- `architecture.md` — Design decisions (from backend-architect, database-architect)
- `review-notes.md` — Code review findings (from code-reviewer)

See `context/README.md` for details.

## Project Context

Each project compiles `PROJECT_CONTEXT.md` with:
- Stack (backend, frontend, database, AI layer, auth, realtime, etc.)
- Directory structure
- Specific patterns (naming, conventions, logging, etc.)
- AI architecture (if applicable)
- Development commands

This single file injects all project-specific context into the agents.

## Usage Example

```bash
# Feature: "Implement Google Ads supervisor"
# Project: Gravya Platform (AI agency)

/team decompose Implement Google Ads supervisor
# Output: .claude/teams/dev-team/context/current-feature.md with 5 atomic tasks

/team architect Implement Google Ads supervisor
# Output: .claude/teams/dev-team/context/architecture.md with API design + DB schema

# Choose implementation path based on task type:
/team python Implement insights_fetcher for Google Ads
# (Python dev for LangGraph executor)

/team review
# Review the implementation
```

## Portability

This team is framework-agnostic and project-agnostic. It adapts to any:
- Backend (Express.js, FastAPI, Rails, Django, ...)
- Frontend (React, Vue, Angular, ...)
- Database (PostgreSQL, MySQL, MongoDB, ...)
- AI layer (LangGraph, LLaMA, native LLM, ...)

The `PROJECT_CONTEXT.md` template guides compilation for any project.

---

**Created:** 2026-03-30  
**Version:** 1.0 (Reusable)  
**Canonical source:** `GravyaDev/claudify`
