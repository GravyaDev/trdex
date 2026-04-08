---
description: End of day - sync memory, clear done list, externalize knowledge, prep tomorrow
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(date:*)
  - Bash(git:*)
  - Agent
---

End-of-day ritual. Externalize knowledge, clean up, prepare for tomorrow.

## Steps

### Step 1: Read current state (parallel)

Read simultaneously:
- `.claude/memory.md`
- `Daily Notes/YYYY-MM-DD.md` (today)
- `Scratchpad.md`
- `Task Board.md`

### Step 2: Process remaining scratchpad items

Same as /sync Step 2. Clear everything — scratchpad should be empty at end of day.

### Step 3: Sync memory

Edit `.claude/memory.md`:
- Update "Now" to reflect where things stand
- Resolve completed Open Threads
- Prune stale Recent Decisions (older than 1 week)
- Clear resolved Blockers

### Step 3b: Regenerate project profile files

Regenerate both project profile files used by `/implement` and other tools:

```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-stack.sh"
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-structure.sh"
```

These files are auto-generated snapshots — do NOT edit them manually:
- `.claude/project-stack.md` — runtimes, dependencies, Docker, config files
- `.claude/project-structure.md` — directory tree (depth 4) + file counts

Note: `project-stack.md` is also updated incrementally by a PostToolUse hook
whenever structural files (package.json, requirements.txt, Dockerfile, etc.) change.
The wrap-up regeneration ensures both files are complete and in sync.

### Step 3c: Deployable components inventory (MANDATORY)

**Why this step exists**: complement to `/start` Step 3 (Repo reality check).
Where `/start` catches gaps reactively each morning, `/wrap-up` persists the
inventory of what's deployable so future sessions inherit it instead of
rediscovering the repo every time. This closes the oversight pattern from
the 2026-04-08 Violation 3 report (dashboard component existed in code
but was never surfaced to the agent planning the deploy).

**3c-i. Enumerate deployable components.** Scan the source tree for each
runnable entry point: FastAPI apps, Streamlit/Gradio dashboards, CLI scripts
(`if __name__ == "__main__"` or `#!/usr/bin/env ...`), background workers,
Next.js/SvelteKit apps, Docker-defined services. For each, record:

- **Name** (directory or file)
- **Type** (api, dashboard, cli, worker, static, other)
- **Entry point** (e.g., `src/trdex/api/main.py`, `src/trdex/dashboard/app.py`)
- **Deploy status** — present in a manifest (compose/Dockerfile/CI) or NOT

**3c-ii. Update `.claude/project-structure.md`**. Append or replace a
section at the bottom titled `## Deployable Components` with a table:

```markdown
## Deployable Components

_Last updated by /wrap-up: YYYY-MM-DD_

| Name | Type | Entry point | In deploy? |
|---|---|---|---|
| `trdex-api` | api | `src/trdex/api/main.py` | ✅ docker-compose.yml |
| `trdex-dashboard` | dashboard | `src/trdex/dashboard/app.py` | ❌ not deployed |
| `trdex-cli` | cli | `src/trdex/cli.py` | N/A (dev tool) |
```

**3c-iii. Flag undeployed components in the daily note.** If any row has
`❌ not deployed`, append to today's Daily Note under a "Deploy gaps"
subsection:

```markdown
### Deploy gaps
- `trdex-dashboard` (dashboard) exists at `src/trdex/dashboard/app.py`
  but is not in any deploy manifest. Decide: deploy, archive, or
  document as dev-only.
```

This keeps the gap visible until it's resolved. Do NOT silently skip —
if there are zero gaps, write "Deploy gaps: none" so the check is
auditable.

### Step 4: Move completed tasks

In `Task Board.md`:
- Move all completed tasks from Today → Done
- Clear Done list if it's Friday
- Move incomplete Today items to This Week or Backlog with a note on why

### Step 4b: Security patch log cleanup (Fridays only)

If today is Friday, prune `.claude/logs/security-patches.md`:
- Read the file
- Remove any entry lines where the date prefix is older than 7 days from today
- Keep the header block and any `<!-- cleaned ... -->` comment
- Append at the bottom: `<!-- cleaned YYYY-MM-DD, removed entries older than YYYY-MM-DD -->`
- Do NOT run dependency audits here — vulnerability checks happen only at /start

### Step 5: Knowledge externalization

Review today's work for learnings:
- **User corrections**: Anything the user explicitly corrected → nominate to `.claude/knowledge-nominations.md`
- **Empirical discoveries**: Things proven through testing → nominate
- **Pattern observations**: Recurring patterns noticed → nominate
- **Failure lessons**: Root cause of any resolved failures → nominate

Format: `- [YYYY-MM-DD] /wrap-up: [learning] | Evidence: [source]`

### Step 6: Mandatory daily audit

Spawn the auditor agent to review today's work:

```
Agent(auditor): Review today's work in Daily Notes/YYYY-MM-DD.md. Check:
1. Were all tasks completed or properly deferred?
2. Were any knowledge-base rules violated?
3. Are there any pending nominations to review?
Tier: T1 (quick scan). Report findings.
```

### Step 6b: Security scan (if code was changed today)

Check `git diff --stat HEAD~1..HEAD`. If any source code files were modified today, invoke:

```
/autoresearch:security --diff --depth shallow
```

This scans only today's diff — fast STRIDE + OWASP pass. If findings are CRITICAL or HIGH, add to incident log and create a corrective task on the Task Board.

### Step 6c: Documentation update (Fridays only)

If today is Friday, invoke:

```
/autoresearch:learn --mode update --depth quick
```

Keeps project docs in sync with the week's changes. Output goes to the daily note.

### Step 7: Review incident log

Read `.claude/logs/incident-log.md`. Summarize any notable events.

### Step 8: Preview tomorrow

Based on Task Board and Open Threads, suggest 1-3 priorities for tomorrow.
Add them to Task Board → Today.

### Step 9: Update daily note

Add to `Daily Notes/YYYY-MM-DD.md` → End of Day Summary:
- Key accomplishments
- Decisions made
- Open items carried forward
- Tomorrow's priorities

### Step 10: Sign off

Brief message: what was accomplished today, what's next tomorrow.
