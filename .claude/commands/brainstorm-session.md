---
description: Brainstorm ideas in isolation — discuss, evaluate, promote to tomorrow's Task Board
argument-hint: "[optional seed idea]"
allowed-tools:
  - Read
  - Edit
  - Bash(date:*)
---

Isolated brainstorm mode. Discuss ideas freely without touching work in progress. Promoted ideas go to Task Board → Today for the next session.

## Steps

### Step 1: Setup (read-only)

Read in parallel:
- `Task Board.md` — to see what's already in Today/This Week and avoid duplicates
- `.claude/memory.md` — to contextualize ideas relative to current work

**Do not modify anything. No writes in this step.**

Keep the loaded context in mind but don't mention it unless relevant to the ideas being discussed.

### Step 2: Mode opening

Announce with a brief message:

> **Brainstorm mode active.** Everything we discuss here is isolated from current work — nothing touches memory, scratchpad, or daily notes. Ideas we promote will land on the Task Board tomorrow morning.

If there's a seed topic (`$ARGUMENTS`), use it as an immediate starting point.
Otherwise ask: "What's on your mind?"

### Step 3: Conversation loop

For each idea introduced by the user, follow this framework — adapt the tone to the conversation, don't be mechanical:

1. **Understand the real goal**
   - "What are you trying to solve with this?"
   - "What's the concrete outcome you expect?"

2. **Expand and connect**
   - Propose variants or alternative angles
   - Connect to things already in progress (use the loaded context)
   - Flag non-obvious risks or dependencies

3. **Evaluate together**
   - Size: single task / feature / architectural refactor / experiment
   - Urgency: blocking / useful now / backlog
   - Expected value vs. complexity

4. **Tentatively classify**
   - `[CANDIDATE]` — makes sense to do, clear value, feasible
   - `[PARKED]` — good idea but wrong timing or missing context
   - `[DISCARDED]` — yak shaving, duplicate, or too low value

Continue the loop until the user closes the session with "done", "close", "end", or similar.

Claude can propose promotion or discard of an idea if there are concrete reasons — the user always decides.

### Step 4: Summary

When the user closes, produce a summary in output (NOT written to any file):

```
## Brainstorm Session — [DATE TIME]

### Promoted → Task Board tomorrow
- **[idea title]**: [concise description — one line]
...

### Parked
- **[idea title]**: [why parked]
...

### Discarded
- **[idea title]**: [why]
...
```

If there are no ideas in a category, omit that section.

### Step 5: Promotion to Task Board

For each idea classified as "promoted":

1. Read `Task Board.md`
2. Add each promoted idea to the **Today** section with the `[idea]` prefix:
   ```
   - [ ] [idea] <concise title> — <one line of context>
   ```
3. Insert entries at the end of the Today section (after existing tasks)

**Do not touch**: `memory.md`, `Scratchpad.md`, `Daily Notes/`, or any other file.
**No commits.** Writing to Task Board is the only output action.

If there are no promoted ideas, don't write anything — close with the summary and that's it.

### Operational notes

- The `[idea]` prefix allows `/start` to distinguish promoted ideas from operational tasks and handle them separately (ask whether to start them, move to This Week, or keep in Today)
- If an idea already exists in Task Board or This Week, flag it during discussion instead of duplicating at promotion time
- No Agent calls — this mode is synchronous and lightweight by design
