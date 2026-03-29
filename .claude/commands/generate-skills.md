---
description: Generate SKILL.md files from the manifest — add, update, or rebuild skill categories
argument-hint: "[category | skill-slug | --all]"
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
  manifest-index.yaml        # Level 1: 31 categories, ~35 lines — always read first
  manifests/<category>.yaml  # Level 2: skills list + category data, ~50-100 lines — read only when needed
  SKILL.template.md          # The boilerplate template with {{placeholders}}
```

**Read only what you need:**
- Level 1 (index) → to identify the right category
- Level 2 (category manifest) → only after confirming the category
- Never load all category manifests at once unless `--all`

## When to use

- Adding a new skill → add entry to `manifests/<category>.yaml`, run `/generate-skills <category>`
- Adding a new category → add to `manifest-index.yaml` + create `manifests/<category>.yaml`, run `/generate-skills <category>`
- Updating frameworks/metrics for a category → edit `manifests/<category>.yaml`, run `/generate-skills <category> --force`
- Rebuilding everything → `/generate-skills --all`

## Steps

### Step 1: Read the index

Read `.claude/skills/_generator/manifest-index.yaml`.

### Step 2: Determine scope

| Argument | Action |
|----------|--------|
| `--all` | Iterate all categories in index |
| `<category-slug>` | Use that category directly |
| `<skill-slug>` | Search index descriptions to identify category, then load that manifest |
| *(none)* | Ask user which category |

### Step 3: Load category manifest

For each category to process, read:
`.claude/skills/_generator/manifests/<category>.yaml`

### Step 4: Read template

Read `.claude/skills/_generator/SKILL.template.md` (once, reuse for all skills).

### Step 5: For each skill, apply substitutions

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
Category:  <name>
Skipped:   <N> already existed (use --force to overwrite)
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
3. Run `/generate-skills <category>`

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
