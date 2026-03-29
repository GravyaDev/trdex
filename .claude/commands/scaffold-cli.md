---
description: Design and scaffold a CLI tool using the OpenCLI spec-first approach
argument-hint: "[binary-name or project description]"
allowed-tools:
  - Read
  - Write
  - Edit
  - Bash(ocli:*)
  - Glob
  - Bash(date:*)
---

Design a CLI interface spec-first using OpenCLI, then generate framework code and documentation.

## Prerequisites

`ocli` must be installed:
```bash
go install github.com/bcdxn/opencli/cmd/ocli@latest
```

If not installed, prompt the user before proceeding.

## Steps

### Step 1: Check ocli installation

```bash
ocli --version 2>/dev/null || echo "NOT_INSTALLED"
```

If not installed, output installation instructions and stop:
```
ocli is not installed. Run:
  go install github.com/bcdxn/opencli/cmd/ocli@latest

Then retry /scaffold-cli.
```

### Step 2: Gather CLI requirements

Read `memory.md` for project context. Then ask the user (if not already provided):

1. **Binary name**: What command users will type (e.g., `mytool`)
2. **Commands**: What subcommands does it have? List them.
3. **For each command**:
   - Required arguments `<name>` vs optional `[name]`
   - Flags with their types (boolean/string/number) and defaults
   - Meaningful non-zero exit codes
4. **Global flags**: Anything that applies to all commands (e.g., `--verbose`, `--config`)
5. **Language/framework**: Go (urfavecli) or JavaScript/Node (yargs)?
6. **Module type** (JS only): CommonJS or ESM?

If the user provided a project description in the argument, infer as much as possible and confirm before generating.

### Step 3: Draft the spec

Create `<binary-name>.ocli.yaml` in the project root (or `cli/` if that directory exists).

Template:
```yaml
opencliVersion: 1.0.0-alpha.7
info:
  title: <Title>
  binary: <binary-name>
  version: 0.1.0
install:
  - method: go
    value: go install github.com/<org>/<binary-name>@latest
global:
  exitCodes:
    - code: 0
      summary: Success
    - code: 1
      summary: General error
  flags:
    - name: verbose
      summary: Enable verbose output
      type: boolean
      aliases: [v]
commands:
  <binary-name> [flags]:
    summary: <root command description>
  <binary-name> <subcommand> [flags]:
    summary: <subcommand description>
    arguments:
      - name: <arg>
        type: string
        required: true
        summary: <description>
    flags:
      - name: <flag>
        type: string
        summary: <description>
        default: <value>
    exitCodes:
      - code: 2
        summary: <specific failure>
```

Rules:
- Required args use `<name>`, optional use `[name]`
- Use `choices: [a, b, c]` for enumerable values
- Keep summaries concise (one sentence)

### Step 4: Validate the spec

```bash
ocli specification check -f <binary-name>.ocli.yaml
```

If validation fails:
- Read the error message carefully
- Fix the spec
- Retry validation
- Do not proceed until it passes

### Step 5: Generate code

**Go (urfavecli):**
```bash
ocli generate cli -f <binary-name>.ocli.yaml --framework urfavecli --go-package main
```

**JavaScript (yargs, CommonJS):**
```bash
ocli generate cli -f <binary-name>.ocli.yaml --framework yargs --module-type commonjs
```

**JavaScript (yargs, ESM):**
```bash
ocli generate cli -f <binary-name>.ocli.yaml --framework yargs --module-type esm
```

Generated files contain `.gen.` in their names. Never edit them manually — edit the spec and regenerate.

### Step 6: Generate documentation

```bash
ocli generate docs -f <binary-name>.ocli.yaml
```

Output: `docs.gen.md` — commit alongside the spec.

### Step 7: Summarize

Output to the user:

```
## CLI scaffolded: <binary-name>

**Spec:** <binary-name>.ocli.yaml
**Docs:** docs.gen.md
**Generated code:** <list generated files>

### Next steps
1. Implement command logic — import the generated interface types
2. Keep business logic separate from the CLI layer (`.gen.` files are regenerated)
3. Regenerate after any spec changes: run /scaffold-cli again
4. Commit spec + generated files together
```

Update `memory.md` with the binary name and framework chosen.
