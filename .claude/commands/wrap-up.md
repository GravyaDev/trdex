---
description: End of day - sync memory, clear done list, externalize knowledge, prep tomorrow
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(date:*)
  - Bash(git:*)
  - Bash(pnpm:*)
  - Agent
---

End-of-day ritual. Externalize knowledge, clean up, prepare for tomorrow.

## Steps

### Step 1: Read current state (parallel)

Read simultaneously:
- `.claude/memory.md`
- `Daily Notes/MMDDYY.md` (today)
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
- Do NOT run pnpm audit here — vulnerability checks happen only at /start

### Step 5: Knowledge externalization

Review today's work for learnings:
- **User corrections**: Anything the user explicitly corrected → nominate to `.claude/knowledge-nominations.md`
- **Empirical discoveries**: Things proven through testing → nominate
- **Pattern observations**: Recurring patterns noticed → nominate
- **Failure lessons**: Root cause of any resolved failures → nominate

Format: `- [MMDDYY] /wrap-up: [learning] | Evidence: [source]`

### Step 6: Mandatory daily audit

Spawn the auditor agent to review today's work:

```
Agent(auditor): Review today's work in Daily Notes/MMDDYY.md. Check:
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

### Step 6d: AI Operations Registry update (Fridays only)

If today is Friday, update the `AI Operations Registry/` files:

1. Read all 6 files in `AI Operations Registry/`
2. Read current state of:
   - `app/services/agents/src/kloud/graph.py` (flow chain)
   - `app/services/agents/src/api.py` (endpoints = processes)
   - `app/packages/db/src/migrations/` (latest migration number)
   - `Task Board.md` → planned processes section
3. For each registry file, check if content matches current reality:
   - **architecture-map.md**: agents/supervisors/executors/tools match DB seed + code
   - **decision-chain.md**: flow diagram matches graph.py node sequence
   - **processes.md**: active processes match api.py endpoints + current supervisor pipeline; planned match Task Board
   - **traceability.md**: tables match actual logging in code
   - **escalation.md**: HITL flow matches interrupt_check in graph.py
   - **gaps.md**: remove resolved gaps, add any new ones discovered this week
4. Update stale sections. Update `Ultimo aggiornamento` date in each modified file.
5. Update `README.md` → "Cambiamenti architetturali significativi" table if architecture changed this week.
6. Log in daily note: "AI Operations Registry updated: [list of files changed]"

### Step 7: Review incident log

Read `.claude/logs/incident-log.md`. Summarize any notable events.

### Step 8: Preview tomorrow

Based on Task Board and Open Threads, suggest 1-3 priorities for tomorrow.
Add them to Task Board → Today.

### Step 9: Update daily note

Add to `Daily Notes/MMDDYY.md` → End of Day Summary:
- Key accomplishments
- Decisions made
- Open items carried forward
- Tomorrow's priorities

### Step 10: Sign off

Brief message: what was accomplished today, what's next tomorrow.
