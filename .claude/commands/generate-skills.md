---
description: Generate SKILL.md files from the manifest — by category, by slug, or by pattern
argument-hint: "[category | slug | category:slug1,slug2 | slug-pattern* | --all]"
allowed-tools:
  - Read
  - Write
  - Bash(find:*, ls:*, mkdir:*)
---

Generate SKILL.md files from the 3-level manifest hierarchy.
Use this instead of hand-crafting individual SKILL.md files.

## Manifest structure

```
.claude/skills/_generator/
  manifest-index.yaml        # Level 1: categories — always read first
  manifests/<category>.yaml  # Level 2: skills list + category data — read only when needed
  SKILL.template.md          # The boilerplate template with {{placeholders}}
```

**Read only what you need:**
- Level 1 (index) → to identify the right category
- Level 2 (category manifest) → only after confirming the category
- Never load all category manifests at once unless `--all`

## When to use

- Generate one skill → `/generate-skills react-patterns`
- Generate specific skills from a category → `/generate-skills development:react-patterns,nextjs-best-practices`
- Generate by pattern → `/generate-skills react-*`
- Generate entire category → `/generate-skills development`
- Rebuild everything → `/generate-skills --all`

## Steps

### Step 1: Read the index

Read `.claude/skills/_generator/manifest-index.yaml`.

### Step 2: Determine scope

Parse the argument to determine what to generate:

| Argument format | Action |
|-----------------|--------|
| `--all` | Iterate all categories in index |
| `<category>` | Load that category manifest, generate **all** its skills |
| `<category>:<slug1>,<slug2>,...` | Load that category manifest, generate **only** the listed slugs |
| `<slug>` (not a category name) | Search all category manifests to find which contains this slug, generate only that skill |
| `<pattern*>` (contains `*` or `?`) | Search all category manifests, generate skills whose slug matches the glob pattern |
| `<slug1> <slug2> ...` (multiple space-separated) | Resolve each slug individually, generate each |
| *(none)* | Ask user which category, then list its skills and ask which to generate |

**Interactive selection (no argument):**
1. Show categories with skill counts
2. User picks a category
3. Show all skills in that category as a numbered list
4. User picks: "all", specific numbers, or a range (e.g., "1-5, 8, 12")
5. Generate only selected skills

### Step 3: Load category manifest(s)

For each category involved, read:
`.claude/skills/_generator/manifests/<category>.yaml`

If resolving individual slugs, search manifests until the slug is found. Cache already-loaded manifests to avoid re-reading.

### Step 4: Read template

Read `.claude/skills/_generator/SKILL.template.md` (once, reuse for all skills).

### Step 5: For each skill to generate, apply substitutions

Filter the `skills:` list from the manifest to only include skills that match the resolved scope from Step 2.

| Placeholder | Value |
|---|---|
| `{{TITLE}}` | `title` from skill entry |
| `{{TITLE_LOWER}}` | title lowercased |
| `{{DESCRIPTION}}` | `"Create a {{TITLE_LOWER}} with structured process, quality checks, and system integration"` |
| `{{PURPOSE}}` | `"Create a comprehensive {{TITLE_LOWER}} that delivers actionable, measurable results. This skill provides a structured process with quality validation, ensuring professional-grade output every time."` |
| `{{CATEGORY_LABEL}}` | `label` from category manifest |
| `{{FRAMEWORKS_INLINE}}` | first 3 frameworks joined by `, ` |
| `{{FRAMEWORKS_LIST}}` | all frameworks as `- item` lines |
| `{{METRICS_INLINE}}` | first 3 metrics joined by `, ` |
| `{{METRICS_LIST}}` | all metrics as `- item` lines |
| `{{BEST_PRACTICES_LIST}}` | all best_practices as `- item` lines |
| `{{BEST_PRACTICE_1}}` | first item of best_practices |

Write to `.claude/skills/<category>/<slug>/SKILL.md`.
Create directory if missing. Skip existing files unless `--force`.

### Step 6: Report

```
Generated: <N> skill files
Category:  <name> (or "multiple")
Skipped:   <N> already existed (use --force to overwrite)

Skills generated:
  - <slug-1>
  - <slug-2>
  ...
```

## Flags

| Flag | Effect |
|------|--------|
| `--all` | Generate all skills across all categories |
| `--force` | Overwrite existing SKILL.md files |
| `--dry-run` | Show what would be generated without writing |

## Adding a new skill

1. Open `manifests/<category>.yaml`
2. Add under `skills:`:
   ```yaml
     - slug: my-new-skill
       title: "My New Skill"
   ```
3. Run `/generate-skills <category>:my-new-skill`

## Adding a new category

1. Add to `manifest-index.yaml`:
   ```yaml
     my-category: "My Category — description"
   ```
2. Create `manifests/my-category.yaml`:
   ```yaml
   label: "My Category"
   frameworks:
     - Framework A
     - Framework B
     - Framework C
   metrics:
     - Metric 1
     - Metric 2
   best_practices:
     - Best practice 1
     - Best practice 2
   skills:
     - slug: first-skill
       title: "First Skill"
   ```
3. Run `/generate-skills my-category`

## Important

- Never edit individual SKILL.md files directly — changes lost on next generation
- Manually-crafted skills (autoresearch, etc.) are excluded from manifests and never regenerated
- The manifest hierarchy is the single source of truth for all boilerplate skills