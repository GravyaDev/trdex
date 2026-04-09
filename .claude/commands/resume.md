---
description: Resume work after a /clear — load handoff, restart timer, pick up where you left off
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Bash(date:*)
  - Bash(bash:*)
---

Lightweight session resume after `/clear`. Skips the full `/start` ceremony
(repo scan, version check, dep audit) — those were already done earlier today.

**When to use**: after `/clear` + new session, same day.
**When NOT to use**: next morning or after overnight → use `/start` instead.

---

## Steps

### Step 1: Find today's handoff

```bash
date +"%Y-%m-%d"
```

Read `Daily Notes/YYYY-MM-DD.md`. Search for the **last** `## Session Handoff` section.

If no handoff section exists, output:

```
No handoff found in today's daily note. Use /start for a full session instead.
```

Then **stop**. Do not fall back to `/start` automatically.

### Step 2: Load context (parallel)

Read simultaneously:
- `.claude/memory.md`
- `.claude/universal-rules.md`
- `.claude/knowledge-base.md`

### Step 3: Restart session timer

```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/session-timer.sh" start
```

### Step 4: Orient and resume

Output a brief orientation from the handoff:
- **Resuming:** [Task from handoff]
- **Done so far:** [Done bullets, condensed]
- **Next action:** [Next field from handoff]
- **Files to re-read:** [Files field from handoff — read the most critical ones now]

Then read the file(s) indicated in the handoff's **Next** or **Files** field
that are needed to resume the work.

Output: "Resumed. What's next, or should I pick up from the handoff?"
