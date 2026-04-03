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
date +"%m%d%y %H:%M %A"
```

### Step 2: Load memory (parallel reads)

Read simultaneously:
- `.claude/memory.md`
- `.claude/knowledge-base.md`

These are your working context. Knowledge-base entries are mandatory constraints.

### Step 3: Create daily note

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

### Step 5: Dependency vulnerability check + auto-patch

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

### Step 6: Open task board

Read `Task Board.md`. Scan for:
- Overdue items (anything from previous days still open)
- Today's priorities
- Blocked items

### Step 7: Task review

For each task in Today:
1. Is it still relevant?
2. Do I have what I need to start?
3. Are there dependencies?

Move stale tasks to Backlog. Flag blocked items.

### Step 8: Ready to work

Output a brief orientation:
- What day it is
- Top 1-3 priorities for today
- Any blockers or open threads from memory.md
- "Ready to work. What's first?"

Keep it short. The user wants to start working, not read a report.
