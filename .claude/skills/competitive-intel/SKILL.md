---
name: competitive-intel
description: "Use when the user wants a deep competitive analysis of a product, service, or market — researching direct and adjacent competitors, building a comparison matrix, identifying gaps and threats, and producing strategic recommendations. Combines web search, parallel research agents, and structured comparison output. Triggers on phrases like 'analyze competitors', 'competitive analysis', 'who else does X', 'how do we compare against', 'competitive landscape for'. Not for general market research without competitor focus — this skill is competitor-centric."
risk: low
source: kloudify
date_added: "2026-04-07"
---

# Competitive Intelligence

## Purpose

Run a **deep competitive analysis** of a product or market: research direct and adjacent competitors, extract their positioning and pricing, build a structured comparison, and produce actionable strategic recommendations. This skill exists to turn noisy market signals into a decision-grade comparison.

This skill is appropriate when:
- The user wants to understand the competitive landscape around a specific product or market
- The output needs to support a strategic decision (positioning, pricing, feature priority, GTM)
- The analysis must be **competitor-centric** (named competitors, side-by-side comparison)

This skill is **not** appropriate when:
- The user wants general **market research** without competitor focus → use a market research approach
- The user wants a **single competitor profile** without comparison → that is a research task, not competitive intelligence
- The user wants **customer research** (interviews, surveys) → different methodology entirely

---

## Process

### 1. Define the competitive frame

Clarify, asking only what is missing:

- **Your product/service** — what are we competing with?
- **Market category** — what space is this?
- **Known competitors** — any the user already knows about?
- **Decision context** — what decision will this analysis inform? (positioning, pricing, feature priority, GTM)

The decision context is critical: it determines which dimensions of comparison matter most. Without it, the analysis becomes a list of facts instead of a recommendation.

### 2. Research competitors (parallel)

Run research in parallel across three angles:

**Angle 1 — Direct competitors**:
- Search for products/services in the same category
- For each: name, URL, pricing, key features, target customer, funding/size
- Read landing pages, pricing pages, feature pages

**Angle 2 — Adjacent competitors**:
- Alternative approaches to the same problem
- Products in adjacent categories that could expand into this space
- Open-source alternatives

**Angle 3 — Market context**:
- Recent news, launches, shutdowns in this space
- Analyst reports or market sizing data
- Customer sentiment (reviews, Reddit, Twitter, Hacker News)

### 3. Build the comparison matrix

Create a structured side-by-side comparison:

| Dimension | Your Product | Competitor A | Competitor B | Competitor C |
|-----------|-------------|-------------|-------------|-------------|
| **Price** | | | | |
| **Target customer** | | | | |
| **Key differentiator** | | | | |
| **Strengths** | | | | |
| **Weaknesses** | | | | |
| **Feature 1** | | | | |
| **Feature 2** | | | | |

Add or remove dimensions based on the decision context from step 1. A pricing decision needs pricing tiers and margin signals; a positioning decision needs differentiator and target customer rows.

### 4. Identify strategic insights

Analyse the matrix for:

**Gaps you can exploit**:
- Features competitors lack that customers want
- Price points nobody serves
- Customer segments being ignored
- Positioning angles nobody owns

**Threats to watch**:
- Well-funded competitors making moves
- Feature convergence (everyone building the same thing)
- Platform risk (dependency on a platform that could compete)

**Your unfair advantages**:
- What do you have that's hard to replicate?
- Speed, expertise, network, data, positioning?

### 5. Strategic recommendations

Produce 3-5 recommendations directly tied to the decision context:

1. **Positioning** — how to position against the field
2. **Pricing** — where to price and why
3. **Feature priority** — what to build (and not build) based on competitive gaps
4. **Messaging** — key claims that differentiate you
5. **Watch list** — competitors to monitor closely and triggers for action

### 6. Write the intel report

Save to `competitive-intel-[market].md`:

```markdown
# Competitive Intelligence — [Market/Product]

**Date:** [date]
**Decision context:** [what this informs]

## Market Overview
[2-3 sentences on the competitive landscape]

## Competitor Profiles

### [Competitor 1]
- **URL:** [url]
- **Pricing:** [pricing model and range]
- **Target:** [who they serve]
- **Strengths:** [bullets]
- **Weaknesses:** [bullets]

[Repeat for each competitor]

## Comparison Matrix
[Table from step 3]

## Strategic Insights

### Gaps to Exploit
[bullets]

### Threats to Watch
[bullets]

### Your Advantages
[bullets]

## Recommendations
1. [Specific, actionable recommendation tied to decision context]
2. [Specific, actionable recommendation tied to decision context]
3. [Specific, actionable recommendation tied to decision context]

---
Sources: [list all URLs and sources used]
```

### 7. Output a summary

Print the **Strategic Insights** and **top recommendation** sections to the user. Do not dump the full file — point them to it.

---

## Exit Criteria

This skill has completed successfully when **all** of the following are true:

- The decision context is explicit in the report
- At least 3 competitors are profiled with sourced data
- The comparison matrix has the dimensions that matter for the decision context
- Each recommendation is actionable (not vague) and tied to a specific finding
- The report file is saved
- Sources are cited

If any criterion is unmet, do not consider the task done.

---

## When to Use

Use this skill whenever the user wants to **make a strategic decision based on competitive context**. Conversational signals: explicit ("competitive analysis of X", "analyze our competitors") or indirect ("who else does this?", "how do we compare against Y?", "should we lower our price compared to the market?"). The skill applies whenever the answer requires looking at named competitors side by side.
