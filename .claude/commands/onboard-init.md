---
description: First-time project onboarding — scan, profile, configure, and start
argument-hint: ""
allowed-tools:
  - Read
  - Edit
  - Write
  - Bash(date:*)
  - Bash(git:*)
  - Bash(find:*)
  - Bash(wc:*)
  - Agent
---

Automatic first-run onboarding. Triggered when `__NEEDS_ONBOARD` exists in the project root.
Scans the project, generates profile files, asks tailoring questions, and configures the system.

## Steps

### Step 1: Read the system

Read in parallel:
- `CLAUDE.md`
- `.claude/universal-rules.md`
- `.claude/command-index.md`

Note: we do NOT read `.claude/memory.md` or `.claude/knowledge-base.md` here.
Onboard-init is by definition a first-run — there is no prior session memory
to inherit, and knowledge-base.md does not exist yet (it will be created in
Step 6 from the template). universal-rules.md is the cross-project ruleset
that ships with Kloudify and is always present.

### Step 2: Scan the project

Use an Explore agent to map the project structure.

**Important:** The scan must exclude Kloudify's own infrastructure — only profile the user's project code. Kloudify files are a **closed, known set**: we list them explicitly below rather than relying on `.gitignore` (which contains project-specific exclusions that the scan may legitimately want to see).

**Kloudify-installed paths to exclude from scan** — UPDATE THIS LIST whenever a new Kloudify file or folder is added to the product:

- `.claude/` — entire Kloudify infrastructure (commands, hooks, agents, skills, settings, logs, backups, memory, knowledge-base, etc.)
- `CLAUDE.md` — Kloudify's main instructions file
- `CLAUDE.local.md` — personal overrides (gitignored)
- `Daily Notes/` — session history (created at runtime by `/start`)
- `Scratchpad.md` — quick capture (runtime)
- `Task Board.md` — today's priorities (runtime)
- `__NEEDS_ONBOARD` — first-run sentinel
- `README.md` — when present at root and is Kloudify's own (not the user project's README)

```
Agent(Explore): Scan this project thoroughly. EXCLUDE these Kloudify-installed paths from your scan:

  .claude/
  CLAUDE.md
  CLAUDE.local.md
  Daily Notes/
  Scratchpad.md
  Task Board.md
  __NEEDS_ONBOARD
  README.md (only if it is Kloudify's own)

These are NOT user project code — they are infrastructure that Kloudify
places into the project. Profiling them would contaminate the project
profile with Kloudify's own structure.

Only profile the user's actual project code. Report:
1. Languages and frameworks detected (with evidence: file extensions, config files)
2. Package managers and their manifest locations
3. Directory structure overview (depth 3)
4. Docker/container setup (if any)
5. Test framework and test locations (if any)
6. CI/CD configuration (if any)
7. Total file count by extension (top 10)
Do NOT read file contents — structure and metadata only.
```

### Step 3: Generate project profile files

Based on the scan, generate:

**`.claude/project-stack.md`** — run the hook:
```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-stack.sh"
```

**`.claude/project-structure.md`** — run the hook:
```bash
bash "$CLAUDE_PROJECT_DIR/.claude/hooks/update-project-structure.sh"
```

### Step 4: Show summary

Present a concise summary of what was detected:
- Project type (web app, CLI, library, monorepo, etc.)
- Languages and frameworks
- Key directories and their purposes
- Dependencies count
- Docker/CI status

### Step 5: Ask tailoring questions

Ask the user these questions (wait for answers before proceeding):

1. **Commit identity**: "What name and email should I use for Co-Authored-By on commits?"
   - Example: `Co-Authored-By: DevBot <bot@example.com>`
   - This will be saved as a hard rule in the knowledge base.

2. **Project goals**: "What are your main goals with this project?"

3. **Workflow**: "What does your typical workflow look like? (e.g., feature branches, trunk-based, solo dev)"

4. **Automation**: "What tasks do you spend the most time on, or want to automate?"

5. **Tools & services**: "Any external tools, platforms, or services you use regularly? (e.g., GitHub, Linear, Sentry, AWS)"

6. **Upstream**: "Does this project track an upstream repo? If so, what's the remote name and branch?" (skip if not applicable)

### Step 6: Configure the system

Based on the answers:

**Bootstrap `.claude/knowledge-base.md`** from the template (this file is
gitignored in the Kloudify base repo and must be created fresh in every
deployment). If `.claude/knowledge-base.md` already exists, leave it alone.
Otherwise, copy `.claude/knowledge-base.md.template` to `.claude/knowledge-base.md`
and replace `{{PROJECT_NAME}}` with the project's actual name.

Then add the commit identity to the Hard Rules section:
```
- **Commit Identity**: All commits must use `Co-Authored-By: [Name] <[email]>`. [Source: onboarding config YYYY-MM-DD]
```

Note: cross-project rules live in `.claude/universal-rules.md` (shipped with
Kloudify, versioned in git) — do NOT touch that file during onboarding.
Only project-specific rules belong in `knowledge-base.md`.

**Update `.claude/memory.md`** with:
- Project name and description (from scan + user input)
- Language/framework/build tool
- Key file paths discovered
- Patterns noticed during scan
- User's goals and workflow preferences
- Upstream remote info (if provided)

### Step 7: Skill discovery and recommendations

Based on the project scan (Step 2) and user answers (Step 5), recommend relevant skills.

**7a. Match categories**

Read `.claude/skills/_generator/manifest-index.yaml`. From the detected stack, frameworks, and user goals, identify the 3–6 most relevant categories. Matching logic:

| Detected signal | Category to suggest |
|---|---|
| Node.js / TypeScript / React / Next.js / Vue / Angular | `development`, `mobile-dev` (if React Native/Expo) |
| Python / FastAPI / Django / Flask | `development`, `data-science-libs` (if numpy/pandas/etc.) |
| Docker / Kubernetes / Terraform / CI config | `devops-cloud` |
| LLM / LangChain / agent frameworks | `agent-systems`, `nlp-llm`, `ai-automation` |
| PostgreSQL / Redis / MongoDB / Drizzle / Prisma | `database-engineering` |
| Security keywords, pentesting tools | `security-pentesting` |
| E-commerce platform (Shopify, Stripe, etc.) | `ecommerce` |
| Mobile (iOS, Android, Flutter, Expo) | `mobile-dev` |
| Game engine (Unity, Unreal, Godot, Bevy) | `game-dev` |
| User mentioned SEO / marketing / content | `seo`, `marketing`, `content` |
| User mentioned sales / CRM | `sales`, `saas-integrations` |
| Three.js / WebGL / 3D | `3d-web` |

Also factor in the user's answers to questions 2 (goals), 4 (automation), and 5 (tools & services).

**7b. Load matched manifests and select relevant skills**

For each matched category, read `.claude/skills/_generator/manifests/<category>.yaml`.

**Do NOT recommend every skill in a category.** Filter each manifest to only skills that are relevant to the detected stack. For example:
- If the project uses React + TypeScript + PostgreSQL, from the `development` category pick only: `react-best-practices`, `react-patterns`, `typescript-*`, `nodejs-*`, `api-design`, `testing-patterns`, etc. — NOT `django-*`, `laravel-*`, `go-*`, `dotnet-*`.
- If the project uses Docker but not Kubernetes, pick `docker-setup` but NOT `kubernetes-deployment`.

Apply this relevance filter using the scan results from Step 2 and the user's answers from Step 5.

**7c. Present recommendations**

Show the user a curated, grouped recommendation of **individual skills** (not whole categories):

```
## Recommended Skills for Your Project

Based on your stack ([detected stack]) and goals ([user goals]):

### [Category 1 Label]
- **skill-a** — [title]
- **skill-b** — [title]

### [Category 2 Label]
- **skill-c** — [title]

[Total: N skills across M categories]

Options:
- "yes" / "all" → generate all recommended skills
- list specific slugs → generate only those (e.g., "react-patterns, api-design")
- "skip" → proceed without generating
```

**7d. Generate selected skills**

Based on user response, run `/generate-skills` with the appropriate granularity:
- "all" / "yes" → `/generate-skills <category>:<slug1>,<slug2>,...` for each category (only the recommended slugs, not the full category)
- specific slugs → `/generate-skills <slug1> <slug2> ...`
- "skip" / "no" → proceed without generating

Log generated skills in memory.md under a "Skills installed" section.

### Step 8: Delete sentinel and start

```bash
rm -f "$CLAUDE_PROJECT_DIR/__NEEDS_ONBOARD"
```

Then run `/start` to begin the first working session.

Output: "Kloudify is configured. Running /start..."
