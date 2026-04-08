---
name: ai-operations-audit
description: "On-demand audit of how AI operates in this project — maps AI components, classifies HITL levels, traces logging paths, inspects escalation, tracks cost, surfaces traceability gaps. Produces a persistent report and promotes recurring findings as knowledge nominations. Use when the user asks to audit AI operations, check AI traceability, verify HITL coverage, or review how agents/LLMs are wired into the project."
risk: safe
source: internal
date_added: "2026-04-08"
---

# AI Operations Audit

## Purpose

Answer the question "**how does AI operate in this project, and can we trust it?**"
on demand, with a persistent report that can be compared against previous audits
to detect drift, new gaps, and improvement over time.

This skill replaces the deprecated `ai-operations-registry/` directory
convention (removed in commit `e53b398`). Where the registry tried to be
a living document maintained by a Friday cron, this skill is an **on-request
audit** that produces fresh, accurate, agent-generated findings every time
it is invoked — with no maintenance debt between runs.

## When to Use

Invoke when the user asks to:
- audit AI operations in the project
- check AI traceability / observability coverage
- verify HITL (human-in-the-loop) levels on AI processes
- inspect escalation policies for AI-triggered actions
- identify cost-tracking gaps on LLM calls
- review how agents, models, or AI services are wired into the project
- compare current AI-operations posture against a previous audit

Do **not** invoke for: debugging a specific AI call failure (use
`autoresearch:debug`), writing AI feature code (use the normal
implementation path), or auditing non-AI parts of the project (use
`/audit` or `/system-audit`).

---

## Operating Model

- **One orchestrator** — the main agent running this skill. It brokers the
  user conversation, reads the previous audit, briefs the sub-agents,
  aggregates their findings, writes the report, and proposes nominations.
- **Six parallel sub-agents** — spawned via the Agent tool as
  general-purpose subagents. Each one answers **one specific question**
  about how AI operates in the project. They run in parallel and do not
  talk to each other.
- **Axis of decomposition**: this skill decomposes the audit **by question**
  (axis 2), not by project area (axis 1). For small-to-medium projects
  (single-service or modest monorepo) this is enough. Debt: scaling to
  large monorepos will need axis 1 decomposition or a matrix mode — see
  the "Future work" section at the bottom.

---

## Procedure

### Step 0: Interactive briefing (MANDATORY, never skip)

The orchestrator must have a correct mental model of the project's AI
surface before spawning any sub-agent. A wrong briefing produces a
confident wrong report, which is worse than no report. Never assume
you know the project — always ask.

**0a. Show the user the questions you are about to ask.** Do not ask
them one at a time. Present them as a bullet list so the user can
answer in one pass:

```
Before I start the audit, I need your input on the following. Answer
them all in one message (or tell me to use my best guess for any
specific item):

1. Which directories contain AI-relevant code? (e.g., agents, LLM
   wrappers, RAG pipelines, embedding stores, prompt templates)
2. Which external AI services does the project call? (OpenAI,
   Anthropic, local LLM, embedding APIs, etc.)
3. Are there any AI processes that should be fully autonomous
   (full_auto) vs. always human-gated (full_manual)? If the answer is
   "I don't know, that's why I'm asking for the audit", say so.
4. Is there a specific area you want me to focus on, or is this a
   full-surface audit?
5. Do you want me to compare against the previous audit (if one
   exists) and highlight deltas?
```

**0b. Wait for the user's response.** Do not proceed without it. If the
user says "use best guesses everywhere", that is a valid answer —
record it in the briefing and flag every guess explicitly in the final
report so the reader knows which findings are user-confirmed vs.
orchestrator-assumed.

**0c. Read previous audit if present.** Check
`.claude/reports/ai-operations-audit-LATEST.md`. If it exists, read
it completely. This is the "historical context" that feeds into every
sub-agent brief, so the new audit can detect continuity, resolution
of previous gaps, and new gaps introduced since last run. If the file
does not exist, this is the first audit — note that in the report
header.

### Step 1: Spawn six sub-agents in parallel

All six sub-agents are spawned in a **single message with multiple
Agent tool calls** so they run in parallel. Each uses
`subagent_type=general-purpose`. Each gets a prompt that includes:

- The user's briefing from Step 0a-0b (verbatim)
- The previous audit contents from Step 0c (if any) — explicitly
  labeled as historical context, NOT as ground truth
- The specific question that sub-agent is responsible for
- An instruction to return a structured answer in a specific format
  (see below)

The six sub-agents and their questions:

1. **`architecture-mapper`** — "Enumerate every place in this project
   where AI is invoked. For each: file path, invocation type (LLM
   call, agent spawn, embedding lookup, RAG query, classification,
   etc.), model/service used, and the human-facing purpose. Output as
   a table."

2. **`hitl-classifier`** — "For every AI invocation found by the
   architecture-mapper (or that you find independently if no prior
   map is available), classify the HITL level on this scale:
   `full_manual` (human must approve every call), `escalation`
   (human approves only when triggers fire), `low_risk` (human
   notified but not gating), `full_auto` (no human involvement).
   Report mismatches between the current classification and what
   the code actually does."

3. **`traceability-auditor`** — "For every AI invocation, identify
   where — if anywhere — the following are logged: input prompt,
   model identifier, token count in/out, cost, latency, output,
   errors. Report every invocation that has gaps."

4. **`escalation-inspector`** — "Identify every AI invocation whose
   failure, cost, or output quality should trigger a human escalation
   (e.g., real money spent, irreversible action, creative judgment).
   For each, check whether the escalation mechanism actually exists
   in code. Report discrepancies between 'should escalate' and 'does
   escalate'."

5. **`cost-tracker`** — "For every LLM call path in the project,
   verify whether model, input tokens, output tokens, and cost are
   logged per call. Report call paths that do not log cost. Aggregate
   an estimated monthly spend if you can derive it from logs or
   metering code; otherwise say so explicitly."

6. **`gap-finder`** — "Independent sweep. Read all AI-relevant code
   you can find and enumerate traceability, reliability, safety, or
   governance gaps that the other five sub-agents might have missed.
   Priority tag each finding as HIGH / MEDIUM / LOW. This is the
   'what else?' sub-agent — be suspicious and broad."

**Output format required from each sub-agent** — every sub-agent
must return exactly:

```markdown
## [sub-agent name]

### Summary
[2-3 sentences: what was examined, what was found]

### Findings
| # | Finding | Priority | Evidence (file:line) |
|---|---------|----------|---------------------|
| 1 | ... | HIGH/MEDIUM/LOW | src/foo.py:42 |

### Delta vs. previous audit
[Only if a previous audit was provided. Otherwise: "N/A — first audit."]
- Resolved since last audit: [list]
- New since last audit: [list]
- Still open: [list]

### Nominated patterns
[Zero or more. Each must be a finding the sub-agent believes is not
a one-off bug but a PATTERN worth tracking across future audits.
Format: "- PATTERN: [description] | Rationale: [why this is a pattern,
not an accident]".]
```

### Step 2: Aggregate into the report

The orchestrator collects all six sub-agent responses and merges them
into a single report with this exact structure:

```markdown
# AI Operations Audit — {{PROJECT_NAME}}

**Audit timestamp**: YYYY-MM-DD HH:MM
**Previous audit**: {{path to prior -LATEST archive, or "none — first audit"}}
**Orchestrator**: {{Claude model identifier}}
**User briefing confirmed**: {{yes / partial / best-guess}}

## Executive summary
- Total AI invocation sites: N
- HIGH priority findings: N
- MEDIUM priority findings: N
- LOW priority findings: N
- New since previous audit: N
- Resolved since previous audit: N
- Nominated patterns: N

## Architecture map
[from architecture-mapper sub-agent, verbatim]

## HITL classification
[from hitl-classifier]

## Traceability
[from traceability-auditor]

## Escalation
[from escalation-inspector]

## Cost tracking
[from cost-tracker]

## Gap sweep
[from gap-finder]

## Aggregated delta vs. previous audit
### Resolved
- ...
### New
- ...
### Still open (carried forward)
- ...

## Nominated patterns
[Union of every sub-agent's "Nominated patterns" section, deduplicated
by the orchestrator. Each entry is a candidate for promotion to
knowledge-nominations.md.]

## Orchestrator notes
[Anything the orchestrator noticed while aggregating — contradictions
between sub-agents, areas where sub-agents disagreed, areas where the
user's briefing was ambiguous, etc. This is the "meta" section.]
```

### Step 3: Archive the previous LATEST, then write the new one

The archiving uses the previous file's **own timestamp**, not "now",
so the archive names reflect when each audit actually ran.

**3a. Archive the previous LATEST (if present).**
- Read `.claude/reports/ai-operations-audit-LATEST.md`
- Extract the `**Audit timestamp**: YYYY-MM-DD HH:MM` line from its
  header
- Rename it to `ai-operations-audit-YYYY-MM-DD-HHMM.md` using that
  timestamp
- If no LATEST file existed, skip this step silently

**3b. Write the new report** to
`.claude/reports/ai-operations-audit-LATEST.md`.

Always use the LATEST filename for the newest report. This is the
contract: future audits know exactly which file to read (LATEST), and
the Daily Note link (Step 4) always points at a stable datestamped
archive, not at LATEST.

### Step 4: Link in the daily note

Append one line to today's `Daily Notes/YYYY-MM-DD.md` under a new
section `## AI Operations Audit`:

```markdown
## AI Operations Audit

- [YYYY-MM-DD HH:MM] Audit completed — N HIGH, M MEDIUM, K LOW findings.
  See [report](.claude/reports/ai-operations-audit-YYYY-MM-DD-HHMM.md)
  (datestamped archive, not the rolling LATEST).
```

**Important**: the daily note link must point at the **datestamped
archive filename that the NEW report will have after the NEXT audit
archives it**, not at `-LATEST.md`. Use today's audit timestamp to
construct that filename. This way the link does not break when the
next audit rotates LATEST out of the way.

Rationale: daily notes are read as historical record. A link to
`-LATEST.md` in an old daily note would silently change meaning every
time a new audit runs. Pointing at the stable archive name keeps the
historical record honest.

### Step 5: Nominate patterns to knowledge-nominations.md

For each entry in the report's "Nominated patterns" section, append
a line to `.claude/knowledge-nominations.md` with the tag
`AI_OPERATIONS_PATTERN`:

```markdown
- [YYYY-MM-DD] ai-operations-audit: AI_OPERATIONS_PATTERN: [description] | Evidence: [report path + finding number]
```

The auditor agent (via the normal Friday wrap-up flow or a manual
`/audit`) will later decide whether to:
- Promote the nomination to `.claude/knowledge-base.md` (project-
  specific pattern)
- Tag it as `UNIVERSAL_CANDIDATE` and leave it for user migration to
  `.claude/universal-rules.md` (cross-project pattern)
- Reject it as noise

This reuses the existing knowledge nomination flow — no new
accumulation mechanism is introduced by this skill.

### Step 6: Prune old archives

Final step, run after everything above is written.

Walk `.claude/reports/ai-operations-audit-YYYY-MM-DD-HHMM.md` files
(exclude `-LATEST.md`). For each file, check two conditions:

- **count condition**: is this file OUTSIDE the 5 most recent
  archives (by filename sort)?
- **age condition**: is this file older than 60 days (by the date
  embedded in the filename, not filesystem mtime — filenames are the
  ground truth)?

Delete the file **only if both conditions are true** (`prune = count > 5 AND age > 60`).

This means:
- You always have at least the 5 most recent audits, even if they
  are old (e.g., project has been dormant)
- You never carry audits older than 60 days AT the same time as
  having more than 5 archives
- Whichever policy is "stricter" wins per-file

Log the prune result in one line to the daily note under the
"AI Operations Audit" section if any files were deleted.

### Step 7: Report to the user

Summarise to the user in 5-10 lines:
- Where the report was written
- Counts: HIGH / MEDIUM / LOW / Nominated patterns
- Top 3 HIGH findings, one-liner each
- Whether a delta section exists and key movements (resolved vs. new)
- Next action suggestion (usually: "review the HIGH findings and
  decide which to fix, defer, or mark as known-accepted")

Do NOT read the full report back — the user can open it. Keep the
summary tight.

---

## Non-goals (explicit)

- **No auto-fix.** The skill reports findings. It does not change code,
  reconfigure services, or open PRs. Those are separate flows.
- **No comparison across projects.** Each project's audit archives
  are independent. Cross-project pattern recognition would require a
  memory channel Kloudify does not have and should not invent ad-hoc.
- **No Friday cron.** This is on-demand only. The deprecated registry
  failed because it promised automatic Friday updates with no
  mechanism to deliver them. This skill makes no such promise.
- **No HITL classification policy.** The skill reports the current
  HITL state and flags mismatches vs. intent, but it does not
  prescribe what the HITL level of a given process SHOULD be. That
  is a human judgement.

## Future work (tracked as debt, not implemented)

- **Axis 1 decomposition** — for large monorepos where "audit the
  whole project at once" is too much for six sub-agents, introduce
  a mode where each functional area (backend, frontend, infra,
  workflows) is audited separately by its own set of six sub-agents,
  and the orchestrator aggregates the per-area reports. Triggered
  by a project-size heuristic or by explicit user request.
- **Matrix mode** — axis 1 crossed with axis 2. Six sub-agents per
  area, each answering one question. Parallelism scales but so does
  token cost; needs cost-awareness in the orchestrator before
  enabling.
- **Comparison across projects** — only if Kloudify grows a
  first-class cross-project memory channel, which it does not have
  today. Do not build this ad-hoc.
