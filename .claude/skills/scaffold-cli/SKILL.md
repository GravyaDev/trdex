---
name: scaffold-cli
description: "Use when the user wants to design or scaffold a command-line tool spec-first using OpenCLI (ocli). Generates a validated YAML spec, framework code (urfavecli for Go, yargs for JS/TS), and auto-documentation. Triggers on phrases like 'scaffold a CLI', 'design a command-line tool', 'create an ocli spec', 'generate CLI from spec'. Requires the ocli binary to be installed."
risk: low
source: kloudify
date_added: "2026-04-07"
---

# Scaffold a CLI Tool (OpenCLI Spec-First)

## Purpose

Design a CLI interface **spec-first** using OpenCLI, then generate framework code and documentation from the validated spec. This skill exists to make CLI design deliberate and contract-first instead of code-first.

This skill is appropriate when:
- The user wants a new command-line tool with structured commands, flags, and exit codes
- The user prefers a spec-driven workflow (design the interface, then generate the code)
- The target framework is `urfavecli` (Go) or `yargs` (JavaScript/Node)

This skill is **not** appropriate when:
- The user wants to add a single subcommand to an existing CLI built without ocli
- The framework requested is something else (cobra, clap, click, commander) — those need a different approach

---

## Prerequisites

`ocli` must be installed:

```bash
ocli --version
```

If the command fails, stop and instruct the user:

```
ocli is not installed. Run:
  go install github.com/bcdxn/opencli/cmd/ocli@latest

Then retry.
```

Do not proceed without a working ocli.

---

## Process

### 1. Read project context

Read `.claude/memory.md` for project goals and constraints. This may surface existing CLI naming conventions, target language preferences, or related tooling already in the project.

### 2. Gather requirements

Ask the user (in batched questions, not one-at-a-time) for anything not already provided:

1. **Binary name** — what users will type (e.g., `mytool`)
2. **Commands** — list of subcommands the tool exposes
3. **For each command**:
   - Required arguments `<name>` vs optional `[name]`
   - Flags: name, type (boolean/string/number), default
   - Meaningful non-zero exit codes
4. **Global flags** — anything applying to all commands (`--verbose`, `--config`)
5. **Language/framework** — Go (urfavecli) or JavaScript/Node (yargs)?
6. **Module type** (JS only) — CommonJS or ESM?

If the user provided a project description, infer as much as possible and confirm before generating.

### 3. Draft the spec

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

### 4. Validate the spec

```bash
ocli specification check -f <binary-name>.ocli.yaml
```

If validation fails:
- Read the error carefully
- Fix the spec
- Retry
- **Do not proceed until validation passes**

### 5. Generate code

**Go (urfavecli)**:

```bash
ocli generate cli -f <binary-name>.ocli.yaml --framework urfavecli --go-package main
```

**JavaScript (yargs, CommonJS)**:

```bash
ocli generate cli -f <binary-name>.ocli.yaml --framework yargs --module-type commonjs
```

**JavaScript (yargs, ESM)**:

```bash
ocli generate cli -f <binary-name>.ocli.yaml --framework yargs --module-type esm
```

Generated files contain `.gen.` in their names. **Never edit them manually** — edit the spec and regenerate.

### 6. Generate documentation

```bash
ocli generate docs -f <binary-name>.ocli.yaml
```

Output: `docs.gen.md` — commit alongside the spec.

### 7. Summarize

Output to the user:

```
## CLI scaffolded: <binary-name>

**Spec:** <binary-name>.ocli.yaml
**Docs:** docs.gen.md
**Generated code:** <list generated files>

### Next steps
1. Implement command logic — import the generated interface types
2. Keep business logic separate from the CLI layer (`.gen.` files are regenerated)
3. Regenerate after any spec changes
4. Commit spec + generated files together
```

Update `.claude/memory.md` with the binary name and framework chosen.

---

## Exit Criteria

This skill has completed successfully when **all** of the following are true:

- `ocli specification check` returned success
- The spec file is committed-ready (no TODO placeholders left)
- Generated code files exist in the expected location
- `docs.gen.md` exists
- The user knows the next implementation steps

If any criterion is unmet, do not consider the task done.

---

## When to Use

Use this skill when the user wants to **design** a CLI interface deliberately, validate it before writing code, and generate framework boilerplate from the spec. It is the right entry point whenever the conversation involves OpenCLI, ocli, spec-first CLI design, or scaffolding a new command-line tool with structured commands and flags.
