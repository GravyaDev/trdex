# Skill Creator Procedure

> Self-contained guide for any LLM to create, validate, and register new skills.
> No prior context required — follow this document step by step.

## Architecture Overview

Skills are **virtual** — defined in YAML manifests, rendered on-demand from a template.
No individual `.md` files per skill. The system:

```
.claude/skills/_generator/
├── SKILL.template.md          # Mustache-style template for rendered skills
├── manifest-index.yaml        # Category index → points to manifests/<slug>.yaml
├── manifests/
│   ├── development.yaml       # Skills for Software Development
│   ├── marketing.yaml         # Skills for Marketing & Advertising
│   ├── security-pentesting.yaml
│   └── ... (46 category files)
└── SKILL-CREATOR.md           # This file (you are here)
```

## Step 1: Define the Skill

Collect these fields for each new skill:

| Field | Required | Example |
|-------|----------|---------|
| **slug** | Yes | `api-rate-limiting` |
| **title** | Yes | `"Api Rate Limiting"` |
| **category** | Yes | `development` |
| **description** | No (nice-to-have for reference) | `"Design rate limiting strategies for APIs."` |

### Slug Rules
- Lowercase, hyphen-separated: `my-skill-name`
- No special characters, no spaces
- Unique across ALL manifests (check before adding)

### Title Rules
- Title Case from slug: `my-skill-name` → `"My Skill Name"`
- Preserve acronyms: `api` → `API`, `llm` → `LLM`, `aws` → `AWS`
- Common acronyms: API, AWS, AI, CI, CD, CLI, CRM, CSS, DB, DDD, DNS, DOM, ERP, GCP, GIT, GPT, GPU, GRPC, HTML, HTTP, IDE, JSON, JWT, K8S, LLM, MCP, ML, MVC, NLP, ORM, PDF, RAG, REST, SDK, SEO, SQL, SSH, SSR, TDD, UI, URL, UX, YAML

### Description Rules
- One clear sentence, no roleplay ("You are a...")
- No trigger preambles ("This skill should be used when...")
- English only — translate non-English descriptions
- End with a period

## Step 2: Choose a Category

### Existing Categories (46)

Read `manifest-index.yaml` for the full list. Key categories:

| Category Slug | When to Use |
|--------------|-------------|
| `development` | Backend/frontend frameworks, architecture, testing, code quality |
| `devops-cloud` | Docker, K8s, Terraform, CI/CD, cloud platforms |
| `security-pentesting` | Offensive security, pentesting tools, SAST, OWASP |
| `database-engineering` | PostgreSQL, vector DB, migrations, query optimization |
| `programming-languages` | Per-language expert skills (`*-pro`) |
| `agent-systems` | Multi-agent, agent memory, tool building, orchestration |
| `nlp-llm` | LLM evaluation, RAG, prompt engineering, fine-tuning |
| `saas-integrations` | Per-SaaS tool automations (Slack, HubSpot, Jira, etc.) |
| `mobile-dev` | iOS, Android, Flutter, React Native, Expo |
| `3d-web` | Three.js, WebGL, Spline, shaders |
| `context-engineering` | Context window management, compression, degradation |
| `data-science-libs` | matplotlib, scikit-learn, pandas, seaborn, polars |

### Creating a New Category

If no existing category fits:

1. Add entry to `manifest-index.yaml`:
   ```yaml
   new-category: "Category Label — short description"
   ```

2. Create `manifests/new-category.yaml`:
   ```yaml
   # Category: Category Label (N skills)
   # Edit this file to add/remove skills or update shared category data.

   label: "Category Label"

   frameworks:
     - Relevant Framework 1
     - Relevant Framework 2

   metrics:
     - Relevant Metric 1
     - Relevant Metric 2

   best_practices:
     - Practice 1
     - Practice 2

   skills:
     - slug: first-skill
       title: "First Skill"
   ```

3. Update `INDEX.md` with the new category row.

## Step 3: Check for Duplicates

Before adding, verify the slug doesn't exist:

```bash
# Check all manifests for an existing slug
grep -r "slug: my-skill-name" .claude/skills/_generator/manifests/
```

Also check for **semantic duplicates** — skills that do the same thing under a different name.

## Step 4: Add the Skill

Append to the appropriate `manifests/<category>.yaml`:

```yaml
  - slug: my-skill-name
    title: "My Skill Name"
```

Skills are appended at the end of the `skills:` list. Alphabetical order is preferred but not enforced.

### Update the Header Comment

Update the skill count in the first line:
```yaml
# Category: Software Development (324 skills)
```

## Step 5: Update INDEX.md

Update the skill count for the category in `.claude/skills/INDEX.md`:

```markdown
| [Software Development](./development/) | 324 | Architecture, code review, APIs, testing |
```

Also update the total count at the top:
```markdown
> 2727+ professional skills across 46 categories.
```

## Step 6: Validate

Run these checks:

```bash
# 1. YAML syntax valid
python3 -c "import yaml; yaml.safe_load(open('manifests/development.yaml'))"

# 2. No duplicate slugs across ALL manifests
for f in manifests/*.yaml; do grep "slug:" "$f"; done | sort | uniq -d
# Should output NOTHING

# 3. Total count matches
for f in manifests/*.yaml; do grep -c "slug:" "$f"; done | paste -sd+ | bc
# Should match INDEX.md total
```

## Batch Import

To add many skills at once from a structured source:

### Input Format
One skill per line: `category|slug|title|description`

```
development|api-rate-limiting|Api Rate Limiting|Design rate limiting strategies for APIs.
security-pentesting|oauth-testing|OAuth Testing|Test OAuth 2.0 implementations for common vulnerabilities.
```

### Processing Script
```bash
while IFS='|' read -r cat slug title desc; do
  echo "  - slug: ${slug}" >> "manifests/${cat}.yaml"
  echo "    title: \"${title}\"" >> "manifests/${cat}.yaml"
done < new-skills.txt
```

Then update counts in all modified manifests and INDEX.md.

## Template Reference

When a skill is invoked, the system renders `SKILL.template.md` with:

| Placeholder | Source |
|-------------|--------|
| `{{TITLE}}` | Skill title from manifest |
| `{{TITLE_LOWER}}` | Lowercase title |
| `{{DESCRIPTION}}` | Generated from title + category context |
| `{{PURPOSE}}` | Generated from title + category context |
| `{{CATEGORY_LABEL}}` | Category label from manifest |
| `{{FRAMEWORKS_INLINE}}` | Category frameworks, comma-separated |
| `{{FRAMEWORKS_LIST}}` | Category frameworks, bulleted |
| `{{METRICS_INLINE}}` | Category metrics, comma-separated |
| `{{METRICS_LIST}}` | Category metrics, bulleted |
| `{{BEST_PRACTICES_LIST}}` | Category best practices, bulleted |
| `{{BEST_PRACTICE_1}}` | First best practice |

The template is shared across ALL skills. Category-specific frameworks, metrics, and best practices make each skill contextually relevant.

## Quick Reference Card

```
To add 1 skill:
  1. Pick category from manifest-index.yaml
  2. grep slug in all manifests → no dupe
  3. Append slug+title to manifests/<cat>.yaml
  4. Update count in INDEX.md
  5. Done — no SKILL.md file needed

To add a new category:
  1. Add to manifest-index.yaml
  2. Create manifests/<slug>.yaml with header + frameworks + metrics + skills
  3. Add row to INDEX.md table
  4. Done
```
