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
- `.claude/memory.md`
- `.claude/knowledge-base.md`
- `.claude/command-index.md`

### Step 2: Scan the project

Use an Explore agent to map the project structure.

**Important:** The scan must exclude Kloudify's own infrastructure — only profile the user's project code. Ignore these paths: `.claude/`, `ai-operations-registry/`, `Daily Notes/`, `CLAUDE.md`, `CLAUDE.local.md`, `__NEEDS_ONBOARD`, `Task Board.md`, `Scratchpad.md`, `SETUP.md`, `README.md` (Kloudify's own).

```
Agent(Explore): Scan this project thoroughly. EXCLUDE these Kloudify infrastructure paths from your scan:
.claude/, ai-operations-registry/, Daily Notes/, CLAUDE.md, CLAUDE.local.md,
__NEEDS_ONBOARD, Task Board.md, Scratchpad.md, SETUP.md, README.md (root-level Kloudify docs).

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

**Update `.claude/knowledge-base.md`** — add under Hard Rules:
```
- **Commit Identity**: All commits must use `Co-Authored-By: [Name] <[email]>`. [Source: onboarding config]
```

**Update `.claude/memory.md`** with:
- Project name and description (from scan + user input)
- Language/framework/build tool
- Key file paths discovered
- Patterns noticed during scan
- User's goals and workflow preferences
- Upstream remote info (if provided)

### Step 7: Delete sentinel and start

```bash
rm -f "$CLAUDE_PROJECT_DIR/__NEEDS_ONBOARD"
```

Then run `/start` to begin the first working session.

Output: "Kloudify is configured. Running /start..."
