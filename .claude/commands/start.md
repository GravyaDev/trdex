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

### Step 5: Kloudify version check

Check whether this project's Kloudify installation is up to date.

**5a. Read the version marker.** Read `.claude/kloudify-version.json`.
If the file does not exist, skip this step silently (the project was
set up before versioning was introduced, or Kloudify was copied
manually without install.sh).

**5b. Query the remote for the latest version.** Extract `source_repo`
from the version marker. If it is a GitHub URL, run:

```bash
gh release view --repo <source_repo> --json tagName,publishedAt,body 2>/dev/null
```

If `gh` is not available or the repo is not accessible, try:

```bash
git ls-remote --tags <source_repo> 2>/dev/null | tail -5
```

If neither works, skip with a note: "Could not check Kloudify
upstream — verify manually."

**5c. Compare versions.** Compare the `version` field in the marker
against the latest remote tag. If they match, output one line:
"Kloudify: up to date (vX.Y.Z)" and move on.

**5d. If an update is available**, show the user:

```
Kloudify update available: vX.Y.Z → vA.B.C
  Released: YYYY-MM-DD
  Changes: <first 3 lines of the release body, or "see release notes">

Update now? This will:
  1. Run install.sh --upgrade to copy new infrastructure files
  2. Deduplicate your knowledge-base.md against the new universal-rules.md
  3. Preserve all project-specific rules and session state

Type "yes" to update, or "skip" to continue without updating.
```

**5e. If the user says yes**, execute the upgrade:

1. Run `bash <kloudify-source>/install.sh <project-dir> --upgrade`
   (the source path is NOT in the version marker — the agent must
   ask the user where the Kloudify repo is cloned, or check if it
   is a known path from memory.md or the user's environment).

2. After install.sh finishes, perform **knowledge-base migration**:
   - Read `.claude/universal-rules.md` (the new version just installed)
   - Read `.claude/knowledge-base.md` (the project's existing rules)
   - For each rule in the KB, check if it is **already covered** by a
     universal rule (same intent, same constraint, possibly different
     wording). If yes, remove it from the KB — it is now redundant.
   - Show the user what was removed and what was kept, with a brief
     explanation for each decision.
   - If any `.kloudify-new` files were created by install.sh (conflict
     markers), show them to the user and ask how to resolve each one.

3. Re-read `.claude/kloudify-version.json` to confirm the new version
   is written. Output: "Kloudify upgraded to vA.B.C. KB migrated:
   N rules removed (now in universal-rules), M rules kept
   (project-specific)."

**5f. If the user says skip**, continue with the rest of /start
normally. Do not nag — the user has decided. Add one line to the
daily note: "Kloudify update vA.B.C available, skipped by user."

### Step 6: Upstream check (if configured)

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

### Step 7: Dependency vulnerability check + auto-patch

**7a. Read the project stack.** Read `.claude/project-stack.md`. This
file is maintained by the PostToolUse hook `update-project-stack.sh`
(incremental, on every structural file edit) and by `/wrap-up` Step 3b
(full regeneration, end of day). It contains the authoritative list of
runtimes, package managers, dependency manifests, Docker files, and
config files for this project.

If `.claude/project-stack.md` does not exist or is older than 48 hours
(check the "Last updated" timestamp in its header), regenerate it now:

```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-stack.sh"
```

**7b. Derive audit targets from project-stack.md.** Do NOT re-scan
the filesystem. Read the "Runtimes Detected" and "Dependencies"
sections of project-stack.md and derive which audit tools to run:

- "Node.js (npm)" or Node dependency sections present → `npm audit`
- "Node.js (pnpm)" → `pnpm audit`
- "Node.js (yarn)" → `yarn audit`
- "Python (pip)" or Python dependency sections present → `pip-audit`
- "Python (pyproject)" → `pip-audit` (via pyproject.toml)
- "Rust (cargo)" → `cargo audit`
- "Go (modules)" → `govulncheck`
- No runtimes detected → skip with "No dependency manifests in project-stack.md"

This ensures /start and /wrap-up agree on what the project contains,
instead of running independent filesystem scans that can diverge.

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

### Step 8: Open task board

Read `Task Board.md`. Scan for:
- Overdue items (anything from previous days still open)
- Today's priorities
- Blocked items

### Step 9: Task review

For each task in Today:
1. Is it still relevant?
2. Do I have what I need to start?
3. Are there dependencies?

Move stale tasks to Backlog. Flag blocked items.

### Step 10: Ready to work

Output a brief orientation:
- What day it is
- Top 1-3 priorities for today
- Any blockers or open threads from memory.md
- "Ready to work. What's first?"

Keep it short. The user wants to start working, not read a report.
