---
description: Start the day - load memory, open task board, ready to work
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(date:*)
  - Bash(git:*)
---

Begin a working session. Load context, create today's daily note, review tasks.

## Steps

### Step 1: Get today's date

```bash
date +"%Y-%m-%d %H:%M %A"
```

### Step 2: Load memory (parallel reads)

Read simultaneously, in this order of precedence:
- `.claude/memory.md` — active session context
- `.claude/universal-rules.md` — cross-project rules (shipped with Kloudify)
- `.claude/knowledge-base.md` — project-specific rules (gitignored, created at onboarding)

These are your working context. **Both rule files are mandatory constraints** — universal-rules apply to every Kloudify project, knowledge-base applies to this specific project. If they conflict, the project-specific rule wins unless the user explicitly says otherwise.

If `.claude/knowledge-base.md` does not exist, the project was not onboarded correctly — run `/onboard-init` first.

### Step 3: Repo reality check (MANDATORY — do not skip)

**Why this step exists**: an earlier session shipped a "deployment complete" verdict without noticing that a whole component existed in the code but not in the deploy manifest. The root cause was starting work without a wide-angle view of the repo. This step forces that view.

Do NOT skip this even if you think you already know the project. Memory and intuition are stale; the filesystem is not.

**3a. Map the source tree.** List the first- and second-level directories under the project's main source root (`src/`, `app/`, `packages/`, or whatever convention this repo uses — read `.claude/project-structure.md` to find out). For each directory report: name, file count, and whether it's referenced anywhere in a deploy manifest (compose, Dockerfile, k8s, CI config).

**3b. Find the deploy manifest(s).** Search for:
- `docker-compose.yml` / `docker-compose.*.yml` / `compose.yml`
- `Dockerfile` / `Dockerfile.*`
- `.github/workflows/*.yml` / `.gitlab-ci.yml`
- `k8s/*.yaml` / `kubernetes/*.yaml`
- `render.yaml` / `railway.toml` / `fly.toml` / `vercel.json` / `netlify.toml`

If none exist, state that explicitly and skip to 3d — there is no deploy to cross-reference against.

**3c. Compute the delta.** For each source directory found in 3a, check whether it appears in any manifest from 3b. Build a table:

| Component | In code? | In deploy? | Delta |
|---|---|---|---|
| `src/backend/` | ✅ | ✅ | — |
| `src/dashboard/` | ✅ | ❌ | **MISSING FROM DEPLOY** |
| `src/shared/` | ✅ | N/A (library) | — |

**3d. Write gaps to memory.md.** If the delta contains any `MISSING FROM DEPLOY` rows, append them to `.claude/memory.md` under **Open Threads**, with today's date. Example:
```
- [2026-04-08] `src/dashboard/` exists in code but not in any deploy manifest — verify whether this is intentional or an oversight before declaring any deploy task complete.
```
If the file is already at 100 lines, prune the oldest resolved "Now" / "Recent Decisions" item first.

**3e. Surface in orientation.** The Step 8 orientation output MUST include a line "Repo reality check: N directories scanned, K gaps vs deploy manifest" with the specific gap names if any. Do not hide this behind a neutral "all good" — be specific about what was checked and what was found.

### Step 4: Create daily note

Create `Daily Notes/YYYY-MM-DD.md` (if it doesn't exist):

```markdown
# YYYY-MM-DD - Daily Work Log

## Decisions
-

## Meetings & Conversations
-

## Notes
-

## End of Day Summary
-
```

### Step 4: Upstream check (if configured)

If `memory.md` mentions an upstream remote, check for new upstream commits:

```bash
git fetch upstream --quiet 2>/dev/null
git log upstream/main..HEAD --oneline 2>/dev/null | head -20
```

Show a one-line summary:
- How many commits ahead of upstream we are
- Any new upstream commits since last check
- Flag if upstream has security fixes or breaking changes in commit messages

If no upstream is configured, skip this step silently.

### Step 6: Dependency vulnerability check + auto-patch

Detect the project's package managers by scanning for manifest files, then run the appropriate audit tool(s).

**Detection logic:**
- `package.json` found → run `npm audit` (or `pnpm audit` / `yarn audit` based on lockfile)
- `requirements.txt` or `pyproject.toml` found → run `pip-audit`
- `Cargo.toml` found → run `cargo audit`
- `go.mod` found → run `govulncheck`
- No manifest found → skip with message "No dependency manifests detected"

Search up to depth 3 from project root (skip `node_modules`, `.git`, `vendor`).

**Auto-patch logic** — apply immediately for each open advisory:

**Tier A — Apply automatically (no user confirmation needed):**
- Vulnerability is a transitive dependency
- Patched version is semver-compatible (same major) with current version
- No API or type signature change in the patched range

**Tier B — Apply automatically with comment:**
- Vulnerability is in a direct dependency
- Patched version requires a minor version bump (same major)
- Note in log that integration test is advisable

**Tier C — On Hold (add to Task Board "Security — On Hold"):**
- Requires major version bump
- Is a peer dep constrained by another package
- Package is abandoned upstream
- Breaking API change confirmed in changelog

**After applying Tier A/B patches:**
1. Reinstall dependencies using the project's package manager
2. Re-run the audit tool to confirm reduction
3. Log every patch to `.claude/logs/security-patches.md`:
   ```
   - `YYYY-MM-DD` | PACKAGE | old→new | METHOD | APPLIED
   ```
4. Commit with the Co-Authored-By identity from the knowledge base
5. Show summary: how many fixed vs on-hold vs total

**Rollback procedure** (if a patch breaks something):
```bash
git revert HEAD --no-edit
# Then reinstall dependencies
```

### Step 7: Open task board

Read `Task Board.md`. Scan for:
- Overdue items (anything from previous days still open)
- Today's priorities
- Blocked items

### Step 8: Task review

For each task in Today:
1. Is it still relevant?
2. Do I have what I need to start?
3. Are there dependencies?

Move stale tasks to Backlog. Flag blocked items.

### Step 9: Ready to work

Output a brief orientation:
- What day it is
- Top 1-3 priorities for today
- Any blockers or open threads from memory.md
- "Ready to work. What's first?"

Keep it short. The user wants to start working, not read a report.
