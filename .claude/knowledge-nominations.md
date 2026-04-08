# Knowledge Nominations

Candidate learnings from agents and sessions. The auditor reviews these
during each audit cycle and promotes valid ones to knowledge-base.md.

## Pending Nominations

### 2026-04-08 — Session violations (self-reported)

These are not *new* rules to promote. They are documented violations of
existing rules that the auditor should use to propose process changes
or SOP tightening, because the recurrence pattern matters.

---

**VIOLATION 1 — Knowledge-base not read at session start**

**Severity**: high (caused violation 2 below)

**What happened**: The session resumed from a context-compacted state
after a long handoff, and the `/start` ritual was executed. However,
`.claude/knowledge-base.md` was NOT actually read into context during
the start sequence — only `memory.md` and the handoff file were read.
The KB has a hard rule "Commit Identity: All commits must use
`Co-Authored-By: Kloud <kloud@gravya.it>`. Author is Daniele. Never
use a generic Claude attribution. [Source: onboarding config
2026-04-04]" which was therefore never loaded.

**Impact**: 4 commits in this session (`302da0b`, `be92b3f`, and two
earlier amend-replacements `ffe7c6e`, `04d19e3`) were created with
`Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>`
trailers. The user had to detect and call this out manually. A
force-push rewrite was required to clean history.

**Root cause**: the `/start` command definition reads memory.md and
knowledge-base.md in Step 2, but the in-session behaviour skipped the
KB read. This is likely because the session started in a compact-resume
state where SessionStart hooks restored context from a prior handoff
rather than executing the `/start` workflow from scratch.

**Proposed fix (for auditor to evaluate)**:
- `SessionStart(compact)` hook should always force-read
  `.claude/knowledge-base.md` as mandatory-context, regardless of
  whether a prior handoff is being restored.
- Add a hard gate to PreToolUse on `git commit` that greps the message
  body for `Claude` / `Anthropic` and blocks if found. Would have
  caught this at the first commit.
- CLAUDE.md mentions "Knowledge-base entries are mandatory constraints"
  but does not enforce — consider promoting KB load to a hook-enforced
  precondition.

---

**VIOLATION 2 — Claude attribution in commits**

**Severity**: high (consequence of violation 1)

**What happened**: 4 commits authored with the default global
`CLAUDE.md` trailer `Co-Authored-By: Claude Opus 4.6 (1M context)
<noreply@anthropic.com>`. This directly contradicts the explicit KB
rule requiring `Kloud <kloud@gravya.it>` as sole co-author trailer.

**Impact**: repo history hygiene; trust in agent adherence to
project-specific rules; force-push required to rewrite two of the
four commits (the other two were already replaced by the force-push).

**Resolution in-session**: commits `302da0b` and `be92b3f` rewritten
as `ffe7c6e` and `04d19e3` with `Co-Authored-By: Kloud <kloud@gravya.it>`
trailer, force-pushed to `origin/main` after user authorization.

**Proposed fix (for auditor to evaluate)**:
- User's global `~/.claude/CLAUDE.md` sets a default Claude trailer
  that overrides project-specific rules unless the assistant explicitly
  chooses Kloud. This is backwards: project rules should override
  global defaults. Consider documenting in CLAUDE.md that project KB
  rules TAKE PRECEDENCE over global user instructions for commit
  identity.
- Add a shell hook (`guard-commit-msg` or similar) that rejects commit
  messages containing "Claude Opus" / "noreply@anthropic.com" on
  projects where a Kloud identity is expected.

---

**VIOLATION 3 — Incomplete code inventory before deploy**

**Severity**: medium

**What happened**: Spent the session deploying trdex to Coolify and
declaring success without ever checking what was in `src/trdex/` at
a high level. The existence of a fully-implemented Streamlit dashboard
in `src/trdex/dashboard/app.py` (381 lines, 13 sections, wired to all
backend APIs, including `streamlit` and `plotly` as declared
dependencies in `pyproject.toml`) was discovered only when the user
asked "where do I SEE the UI?". The dashboard was committed yesterday
in `1310231 feat: ... dashboard expansion ...` but was never mentioned
in `memory.md`, the handoff file, or the Task Board, and I never read
it when planning the deploy.

**Impact**: the production deploy only included the backend. The user
has no UI to observe Phase 2 beyond `curl` and `inspect_runs` CLI. The
dashboard has to be deployed as a second step instead of being part
of the original deploy planning.

**Root cause**: relied on memory.md + handoff + Task Board as the sole
sources of truth about "what is in the repo". These documents were
written by prior sessions and were not exhaustive. There is no
automated "repo inventory" step in `/start` that would have surfaced
`src/trdex/dashboard/` as a first-class component.

**Proposed fix (for auditor to evaluate)**:
- Add a `/start` sub-step that runs `tree src/` (or equivalent) at
  depth 2 and diffs against a known `project-structure.md` snapshot,
  flagging any top-level modules the session has never touched.
- Every `/wrap-up` should update a `project-structure.md` file that
  lists every top-level module under `src/` with a one-line purpose,
  so future sessions inherit a complete inventory.
- Deploy planning skills should include a "deployable components
  checklist" that enumerates every runnable entry point in the repo
  (FastAPI app, Streamlit dashboards, CLI scripts, background
  workers) and asks which are in-scope for the deploy being planned.
