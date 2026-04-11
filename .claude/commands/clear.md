---
description: Distill session state to daily note handoff, then stop. User resumes in a fresh session.
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(date:*)
  - Bash(bash:*)
---

Save session state to a handoff and **stop**. Return control to the user.
This command does NOT auto-resume — resuming is a separate action the user
takes in a fresh session, by reading the handoff section of the daily note.

**Why this contract**: `/clear` is invoked when context is under pressure.
Loading additional files after distilling (to "seamlessly continue") makes
the pressure worse, not better. The only way to actually free context is
to persist state, stop, and let the user open a new session.

**Emergency mode** (compacting/prompt-too-long warning visible):
Skip Step 1 reads. Distill from in-context memory only. Go directly to Step 3.

---

## Steps

### Step 0: Reset gate files + get date

```bash
date +"%Y-%m-%d %H:%M" && rm -f ".claude/logs/.quality-gate-active" ".claude/logs/.session-blocks-$(date +"%Y-%m-%d-%H")" ".claude/logs/.clean-streak-$(date +"%Y-%m-%d-%H")" ".claude/logs/.tool-call-count" ".claude/logs/.compaction-occurred"
```

### Step 1: Read state (parallel, SKIP in emergency mode)

Read simultaneously:
- `.claude/memory.md`
- `Daily Notes/YYYY-MM-DD.md` (today's note, if it exists)

These reads are only to refresh your view of the persistent state before
distilling. In emergency mode, skip this step and distill only from what
is already in-context.

### Step 2: Distill session (from in-context memory)

Extract the essentials that the **next session** will need to pick up the work:

1. **Task** — one sentence: what was being worked on
2. **Done** — 2-4 bullets, conclusions not process
3. **Remaining** — 2-4 bullets, what is still open
4. **Decisions** — one line each, WHAT+WHY (not HOW)
5. **Learnings** — rules/facts worth promoting to `knowledge-nominations.md` or `knowledge-base.md`
6. **Files touched** — full paths of every file read or modified in this session (retrieval anchors for the next session)
7. **Active references** — URLs, API endpoints, external resources consulted. Pointers only, no content.
8. **Next action** — precise, actionable instruction including which file(s) to read first in the next session

### Step 3: Write handoff to daily note

Append to `Daily Notes/YYYY-MM-DD.md` (create the file if missing, using the standard daily note header):

```markdown
## Session Handoff — HH:MM

**Task:** [one sentence]
**Done:** [bullets]
**Remaining:** [bullets]
**Decisions:** [bullets]
**Files:** [full paths]
**Refs:** [URLs, external resources — pointers only]
**Next:** [precise action + which file(s) to read first in the next session]
```

### Step 4: Update memory.md (only if changed)

If the session produced new priorities, resolved open threads, or made
decisions that affect longer-term memory, edit `.claude/memory.md`.
If nothing changed, skip this step.

**Size discipline**: memory.md has a 100-line Write cap enforced by the
completeness gate. If your edit would push it over, prune stale items
FIRST, then add the new content.

### Step 5: Promote or nominate learnings (only if discovered)

**Tier 1 — Immediate promotion to `knowledge-base.md`** (high-confidence rules only):
- User overrides (user explicitly corrected something this session)
- Empirical facts (verified through testing or data this session)

Format with `[Source: User directive YYYY-MM-DD]` or `[Source: Empirical YYYY-MM-DD]`.
Respect the 200-line size cap and the `[Source:]` provenance gate.

**Tier 2 — Nominate to `knowledge-nominations.md`** (lower-confidence):
- Agent inferences (patterns observed but not fully confirmed)
- Hypotheses (things that seem true but need more evidence)

Format: `- [YYYY-MM-DD] /clear: [learning] | Evidence: [source]`

**Rule of thumb**: when in doubt, nominate rather than promote. The auditor
will review nominations on the next `/audit` or `/wrap-up`.

### Step 5b: Stop session timer

Stop the session timer so the elapsed time is recorded accurately:

```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-timer.sh" stop
```

If the output is a duration (e.g., "1h 23m"), include it in the handoff
section of the daily note by appending to the Session Handoff block:
```
**Session duration:** [elapsed time]
```

If the timer was not running, skip silently.

### Step 6: Stop and report

Output a **short** message to the user and **do not continue working**.
Do not re-read memory.md. Do not re-read knowledge-base.md. Do not read
the daily note you just wrote. Do not execute the "Next action" from the
handoff. **Just stop.**

Message template:

```
Session handoff saved.

Location: Daily Notes/YYYY-MM-DD.md § Session Handoff HH:MM

Next action recorded: [one-line summary of the Next field from the handoff]

To continue this work, open a fresh session and run /resume.
It will load the handoff, restart the timer, and pick up where you left off.
```

Then **stop**. Wait for the user to close the session or give a new
instruction. Do not volunteer additional work.

---

## Target performance

- Normal mode: 4-6 tool calls, <20 seconds.
- Emergency mode: 2-3 tool calls, <10 seconds (skip reads, distill from in-context only, write handoff, stop).

## Contract recap — what `/clear` is and is NOT

- ✅ Persist essential state to disk (daily note + memory.md).
- ✅ Promote validated learnings.
- ✅ Stop and return control to the user.
- ❌ NOT an auto-resume mechanism. Use a fresh session to continue.
- ❌ NOT a "seamless background operation". The user asked for `/clear` because something was wrong; they need to know it happened and where the state is.
- ❌ NOT a trigger to re-read memory.md + knowledge-base.md after distilling — that would re-inflate the context that `/clear` is supposed to release.
