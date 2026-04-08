---
name: report-writing
description: "Use when the user wants to turn raw data, findings, research, or analysis into a polished narrative report tailored to a specific audience (executive, technical, client, board). Adapts tone, depth, and structure to the audience and produces a structured deliverable with summary, findings, analysis, and recommendations. Triggers on phrases like 'write a report', 'create an executive summary', 'turn this into a report', 'draft a report for [audience]'. Not for code review reports — use the /review command for that."
risk: low
source: kloudify
date_added: "2026-04-07"
---

# Audience-Aware Report Writing

## Purpose

Turn raw data, findings, or research into a **polished narrative report** that adapts tone and depth for the target audience. This skill exists to prevent the most common report failure: writing for the wrong reader.

This skill is appropriate when:
- The user has data, findings, research, or analysis that needs to be packaged into a report
- The report has a specific intended audience (executive, technical, client, board, general)
- The output is a deliverable, not a working note

This skill is **not** appropriate when:
- The task is a **code review** report → use the `/review` command
- The task is **competitive analysis** → use the `competitive-intel` skill
- The task is a **status update or standup** → use the `/standup` command
- The user just wants to dump unstructured notes → that is a working note, not a report

---

## Process

### 1. Clarify inputs

Identify, asking only what is missing:

- **Topic** — what is this report about?
- **Data sources** — which files, findings, or data feed into it?
- **Audience** — who reads this? (executive, technical team, client, board, general)
- **Format preference** — brief (1-2 pages), standard (3-5 pages), or comprehensive (5+ pages)

If the user did not specify an audience, default to **professional — clear, direct, no jargon**.

### 2. Gather source material

Read all relevant files and data. Scan for:

- Key findings and metrics
- Patterns and trends
- Comparisons (before/after, vs. benchmark, vs. competitor)
- Anomalies or concerns
- Recommendations that emerge from the data

### 3. Structure for the audience

Apply the audience-specific framework:

**Executive audience**:
- Lead with the bottom line (recommendation or key finding)
- Use bullet points over paragraphs
- Include only metrics that drive decisions
- Keep under 2 pages
- End with clear next steps

**Technical audience**:
- Lead with methodology
- Include detailed data and analysis
- Show your work (how you reached conclusions)
- Include caveats and limitations
- Reference source files

**Client audience**:
- Lead with what matters to them (results, ROI, impact)
- Use their language, not yours
- Contextualise numbers ("+15% vs industry average of +3%")
- Include visual formatting (tables, bold key numbers)
- End with what happens next

**Board audience**:
- Strategic framing only — no tactical detail
- Risks and mitigations explicit
- Financial impact quantified
- One-page executive summary first, appendix for depth

**General audience**:
- Plain language, define jargon on first use
- Lead with relevance ("why this matters to you")
- Use concrete examples over abstractions
- End with a clear takeaway

### 4. Write the report

Structure:

```markdown
# [Report Title]

**Date:** [date]
**Prepared for:** [audience]

---

## Summary

[2-3 sentences: key finding, core recommendation, bottom line]

## Key Findings

### [Finding 1]
[Data, context, significance]

### [Finding 2]
[Data, context, significance]

### [Finding 3]
[Data, context, significance]

## Analysis

[Deeper interpretation — what the findings mean, patterns, comparisons]

## Recommendations

1. **[Action]** — [rationale and expected impact]
2. **[Action]** — [rationale and expected impact]
3. **[Action]** — [rationale and expected impact]

## Next Steps

- [ ] [Specific action with owner/timeline]

---
Sources: [list data sources used]
```

### 5. Quality check

Before delivering, verify **all** of:

- [ ] Every claim has supporting data
- [ ] No jargon the audience wouldn't understand
- [ ] Recommendations are actionable (not vague)
- [ ] Numbers are consistent throughout
- [ ] Report answers "so what?" — not just "what"

### 6. Save and deliver

Save to `reports/[topic]-report.md` (create directory if missing). Output a brief summary so the user can verify accuracy without reading the whole file.

---

## Exit Criteria

This skill has completed successfully when **all** of the following are true:

- The audience is explicitly identified
- Every section is filled (no placeholders left)
- The 5-item quality check passes
- The report file is saved to `reports/`
- The user has been shown a summary

If any criterion is unmet, do not consider the task done.

---

## When to Use

Use this skill whenever the user needs to package data, research, or findings into a **deliverable** with an explicit audience. The conversational signals are direct ("write a report on X for the board") or indirect ("can you summarize this for the executives?", "draft something I can send to the client about Y"). If the conversation involves an audience and a deliverable, this skill applies.
