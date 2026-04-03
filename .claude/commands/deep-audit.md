# /deep-audit

Full multi-agent architectural audit of the project.
Team of 6 specialist analysts. Produces a PASS/WARN/FAIL report.
Reproducible methodology — run periodically or after major refactors.

## Trigger
- Explicit invocation: `/deep-audit`
- Recommended after: architectural refactors, upstream merges, new external integrations
- Suggested frequency: monthly or every 5+ sessions of intensive development

---

## Phase 1 — Codebase snapshot

Read `.claude/project-stack.md` and `.claude/project-structure.md` to understand the current stack.
If these files are missing or stale, regenerate them first:

```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-stack.sh"
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-structure.sh"
```

Then use an Explore agent to map the current structure:

```
Agent(Explore): Map the project structure — list source files by category
(backend, frontend, config, tests, migrations, Docker).
Do not read file contents — structure only. Return counts per category.
```

---

## Phase 2 — Launch 6 analysts in parallel

Launch ALL in a single message (parallel tool calls).
Each analyst receives: exact file paths to read, evaluation criteria, output format.

Output format for each analyst:
```
## [Analyst Name]
### PASS
- [criterion]: [evidence]
### WARN
- [criterion]: [issue] → [suggestion]
### FAIL
- [criterion]: [critical issue] → [required fix]
```

---

### Analyst 1 — Schema Analyst

**Scope**: Database schema integrity, migrations, indexes, FK constraints, consistency.

**What to check** (adapt paths to actual project structure from Phase 1):
- Migration files and their journal/history
- Schema definition files
- Seed data scripts

**Criteria**:
1. Migration journal is complete — every SQL file has a corresponding entry
2. FK constraints are correct — references existing tables, ON DELETE semantics appropriate
3. Indexes present on columns used in critical queries
4. Seed data is idempotent (ON CONFLICT DO NOTHING or DO UPDATE)
5. Schema definition files are consistent with migration SQL
6. No orphaned migrations (referenced in journal but file missing, or vice versa)

---

### Analyst 2 — Backend Analyst

**Scope**: Code quality, import integrity, async correctness, error handling, architecture patterns.

**What to check** (adapt to detected backend language/framework):
- Main entry point and API routes
- Core business logic modules
- Configuration/settings files
- Utility modules

**Criteria**:
1. No broken imports (nonexistent paths, references to renamed modules)
2. Dead code identified — unused files, unreachable functions
3. Async/await correctness — no sync calls in async context (especially DB and external APIs)
4. Error handling: every external call has try/except with fallback or explicit re-raise
5. No hardcoded secrets
6. Configuration loaded from environment, not hardcoded
7. Clean separation of concerns (routes vs business logic vs data access)

---

### Analyst 3 — Infrastructure Analyst

**Scope**: Docker, port mappings, env vars, healthchecks, deployment config.

**What to check**:
- Docker Compose files and Dockerfiles
- `.env.example` or equivalent
- CI/CD configuration files
- Server entry points

**Criteria**:
1. Port mapping is consistent — internal port in Dockerfile matches compose mapping
2. All env vars used in code are documented in .env.example
3. Healthcheck configured for services in Docker Compose
4. Database URLs consistent across all services
5. No Windows-specific paths in Docker config
6. CORS is configured (not wildcard `*` in production)
7. Volumes are correctly mounted

---

### Analyst 4 — Security Analyst

**Scope**: Auth, input validation, API keys, injection risks, secrets management.

**What to check**:
- Authentication/authorization modules
- API endpoint definitions
- Configuration and secrets handling
- User input processing paths

**Criteria**:
1. Authentication is verified on all non-public endpoints
2. Input sanitization before processing
3. No secrets in code, logs, or response bodies
4. SQL queries are parameterized (no f-string or string concatenation)
5. API keys loaded from environment, never committed
6. Rate limiting active on critical endpoints
7. File path validation (no traversal, extension whitelist) where applicable

---

### Analyst 5 — Architecture Analyst

**Scope**: Failure isolation, SPOF, architectural consistency, modularity, SOLID principles.

**What to check**:
- Core architectural modules
- Service boundaries and dependencies
- State management
- Error propagation paths

**Criteria**:
1. Failure isolation — crash of one component does not block others
2. Cache failures handled gracefully (fallback to direct source)
3. SPOF identified — single external dependency without fallback?
4. No shared mutable state between concurrent operations
5. Clean module boundaries — no circular imports
6. Configuration separated from business logic
7. Backward compatibility considered for API changes

---

### Analyst 6 — Frontend Analyst

**Scope**: Frontend code quality, API integration, UX patterns, error handling.

**What to check** (skip if no frontend detected):
- Page/component structure
- API integration layer
- State management
- Routing and authentication

**Criteria**:
1. Pages use consistent routing and auth patterns
2. API calls use configured base URL (not hardcoded)
3. No sensitive data exposed in the frontend bundle
4. Error states handled (loading, error, empty) on every page
5. State management is centralized and consistent
6. No business logic in the frontend (presentation + API calls only)

---

## Phase 3 — Compile report

Aggregate all results in:
```
.claude/reports/deep-audit-YYYY-MM-DD.md
```

Report structure:
```markdown
# Deep Audit — [Project Name] — YYYY-MM-DD

## Executive Summary

| Analyst | PASS | WARN | FAIL |
|---|---|---|---|
| Schema | X | Y | Z |
| Backend | ... | ... | ... |
| Infrastructure | ... | ... | ... |
| Security | ... | ... | ... |
| Architecture | ... | ... | ... |
| Frontend | ... | ... | ... |
| **TOTAL** | ... | ... | ... |

## Findings per analyst
[Section for each analyst with PASS/WARN/FAIL details]

## Prioritized fixes
### P0 — Critical (blocks correctness or startup)
### P1 — Warning (degrades reliability)
### P2 — Improvements (not urgent)

## Comparison with previous audit
[Delta: new FAILs, WARN→PASS, regressions]
```

---

## Phase 4 — System update

On completion:
- P0 fixes → Task Board "Priority Fix"
- P1 fixes → Task Board "This Week"
- P2 fixes → Backlog
- Update `memory.md` with audit status
- Nominate any learnings to `knowledge-nominations.md`
- If FAIL count > 3: recommend NOT proceeding with feature work until fixes are applied
