---
description: End of day - sync memory, clear done list, externalize knowledge, prep tomorrow
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(date:*)
  - Bash(git:*)
  - Bash(bash:*)
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
- **Entry point** (e.g., `src/backend/main.py`, `src/dashboard/app.py`)
- **Deploy status** — present in a manifest (compose/Dockerfile/CI) or NOT

**3c-ii. Update `.claude/project-structure.md`**. Append or replace a
section at the bottom titled `## Deployable Components` with a table:

```markdown
## Deployable Components

_Last updated by /wrap-up: YYYY-MM-DD_

| Name | Type | Entry point | In deploy? |
|---|---|---|---|
| `myapp-api` | api | `src/backend/main.py` | ✅ docker-compose.yml |
| `myapp-dashboard` | dashboard | `src/dashboard/app.py` | ❌ not deployed |
| `myapp-cli` | cli | `src/cli.py` | N/A (dev tool) |
```

**3c-iii. Flag undeployed components in the daily note.** If any row has
`❌ not deployed`, append to today's Daily Note under a "Deploy gaps"
subsection:

```markdown
### Deploy gaps
- `myapp-dashboard` (dashboard) exists at `src/dashboard/app.py`
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

### Step 6: Mandatory daily audit (NEVER SKIP)

**This step is MANDATORY. Do not skip it.** Do not estimate the cost
and then decide not to pay it. Do not invoke conciseness, efficiency,
or any other self-generated justification to bypass it. The
`allowed-tools` frontmatter includes `Agent` specifically for this
step. Only an explicit user override can waive it.

Spawn the auditor agent to review today's work:

```
Agent(auditor): Review today's work in Daily Notes/YYYY-MM-DD.md. Check:
1. Were all tasks completed or properly deferred?
2. Were any knowledge-base rules violated?
3. Are there any pending nominations to review?
Tier: T1 (quick scan). Report findings.
```

### Step 6b: Security scan (NEVER SKIP when code changed)

**This step is MANDATORY when code was changed today.** You MUST run
the check command below BEFORE deciding whether code was changed.
Do not rely on your memory of what was committed — your memory is
unreliable across long sessions, and the check exists precisely for
that reason. Only the output of the check determines scope, not
your recollection.

```bash
git diff --stat $(git log --format=%H --after="$(date +%Y-%m-%d) 00:00:00" --reverse | head -1)^..HEAD 2>/dev/null || git diff --stat HEAD~1..HEAD
```

If the output shows ANY source code files were modified today, spawn a
security-focused sub-agent to scan today's diff:

```
Agent(general-purpose): Run a shallow STRIDE + OWASP Top 10 security
review on today's code changes. Context:

1. Run: git diff $(git log --format=%H --after="$(date +%Y-%m-%d) 00:00:00" --reverse | head -1)^..HEAD
2. For each changed file, check for:
   - Injection risks (SQL, command, path traversal)
   - Authentication/authorization gaps
   - Secrets or credentials in code
   - Unsafe deserialization
   - Missing input validation at system boundaries
   - CORS/CSRF misconfigurations
   - Hardcoded URLs or IPs that should be config
3. Classify each finding as CRITICAL / HIGH / MEDIUM / LOW
4. Return a structured table: File | Line | Finding | Severity

Keep it fast — this is a daily hygiene scan, not a deep audit.
Do NOT read files outside the diff. Focus on what changed today.
```

If findings are CRITICAL or HIGH, add to `.claude/logs/incident-log.md`
and create a corrective task on the Task Board.

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

### Step 8b: Stop session timer

Stop the session timer and record the total working time:

```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-timer.sh" stop
```

The output is the formatted elapsed time (e.g., "2h 34m").
Add it to today's daily note under End of Day Summary as the first line:
```
- **Session duration**: [elapsed time]
```

If the timer was not running (e.g., /start was never called), note
"Session duration: unknown (timer was not started)" instead.

### Step 9: Update daily note

Add to `Daily Notes/YYYY-MM-DD.md` → End of Day Summary:
- Key accomplishments
- Decisions made
- Open items carried forward
- Tomorrow's priorities

### Step 10: Push day's work (user confirmation required)

Check if there are unpushed commits on the current branch:

```bash
git log @{upstream}..HEAD --oneline 2>/dev/null
```

If there are **no unpushed commits**, skip this step silently.

If there **are** unpushed commits, show the user a summary:

```
Unpushed commits (N):
<list of one-line commit summaries>

Push to origin/<branch>?
```

- **User says yes**: run `git push` and report the result.
- **User says no/skip**: note "Push skipped by user" in the daily note
  under Notes, and move on.

Do NOT push without explicit user confirmation. Do NOT use `--force`.

### Step 11: Sign off

Brief message: what was accomplished today, what's next tomorrow.
