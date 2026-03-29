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

Create `Daily Notes/MMDDYY.md` (if it doesn't exist):

```markdown
# MMDDYY - Daily Work Log

## Decisions
-

## Meetings & Conversations
-

## Notes
-

## End of Day Summary
-
```

### Step 4: Paperclip upstream check

Run inside `app/`:
```bash
git -C app fetch upstream --quiet 2>/dev/null || git -C "$(find . -name '.git' -not -path '*/.git/*' | head -1 | xargs dirname)" fetch upstream --quiet
git log upstream/main..HEAD --oneline 2>/dev/null | head -20
```

Show a one-line summary:
- How many commits ahead of upstream we are
- Any new upstream commits since last check (commits on upstream/main not in our branch)
- Flag if upstream has security fixes or breaking changes in commit messages

### Step 5: Dependency vulnerability check + auto-patch

Run `pnpm audit` inside `app/` and classify findings:

```bash
cd app && pnpm audit --json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
advisories = data.get('advisories', {})
counts = {'critical':0,'high':0,'moderate':0,'low':0}
for v in advisories.values():
    s = v['severity'].lower()
    counts[s] = counts.get(s,0) + 1
    paths = []
    for f in v.get('findings',[]):
        for p in f.get('paths',[])[:1]:
            paths.append(p.split(' > ')[0])
    print(f\"[{v['severity'].upper():<8}] {v['module_name']:<22} patched={v.get('patched_versions','none'):<20} via={','.join(set(paths))[:60]}\")
total = sum(counts.values())
print(f'\nTOTAL: {total} | CRITICAL:{counts[\"critical\"]} HIGH:{counts[\"high\"]} MODERATE:{counts[\"moderate\"]} LOW:{counts[\"low\"]}')
" 2>/dev/null || echo "pnpm audit unavailable"
```

**Auto-patch logic** — apply immediately for each open advisory:

**Tier A — Apply automatically (no user confirmation needed):**
- Vulnerability is a transitive dep (not in any `package.json` directly)
- Fix = add/update a pnpm override in root `package.json` → `pnpm.overrides`
- No API or type signature change in the patched range

**Tier B — Apply automatically with simple direct bump:**
- Vulnerability is in a direct dep in `server/package.json` or `packages/db/package.json`
- Patched version is semver-compatible (same major) with current pinned version
- e.g. multer `^2.0.2` → `^2.1.1`

**Tier C — On Hold (add to Task Board "Security — On Hold"):**
- Requires major version bump
- Is a peer dep constrained by another package (e.g. kysely locked by drizzle-orm)
- Package is abandoned upstream (fix requires upstream to act first)
- Breaking API change confirmed in changelog

**After applying Tier A/B patches:**
1. Run `pnpm install` in `app/`
2. Run `pnpm audit` again to confirm reduction
3. Log every patch to `.claude/logs/security-patches.md`:
   ```
   - `YYYY-MM-DD` | PACKAGE | old→new | METHOD | COMMIT | APPLIED
   ```
   METHOD = `pnpm override` or `direct bump (path/to/package.json)`
4. Commit with message:
   ```
   security: auto-patch N vulnerabilities [MMDDYY]

   - pkg1: old→new (override)
   - pkg2: old→new (direct bump)

   Co-Authored-By: Kloud <kloud@gravya.it>
   ```
5. Show summary: how many fixed vs on-hold vs total

**Rollback procedure** (if a patch breaks something):
```bash
# Revert the security commit
git -C app revert HEAD --no-edit
# Then reinstall
cd app && pnpm install
```
The patch log at `.claude/logs/security-patches.md` records every change for traceability.

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
