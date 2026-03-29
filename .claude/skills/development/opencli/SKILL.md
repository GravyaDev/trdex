---
description: Design, validate, and scaffold CLI tools using the OpenCLI spec-first approach
---

# OpenCLI — Spec-First CLI Design

## Purpose

Design CLI interfaces declaratively before writing implementation code, then auto-generate documentation and framework boilerplate using the `ocli` tool.

**Category**: Software Development

## What is OpenCLI

OpenCLI is a language-agnostic specification format for CLI interfaces, analogous to OpenAPI for REST APIs. The workflow is:

1. Write a `.ocli.yaml` spec defining commands, arguments, flags, and exit codes
2. Validate with `ocli specification check`
3. Generate framework code with `ocli generate cli`
4. Generate documentation with `ocli generate docs`

The `ocli` binary must be installed: `go install github.com/bcdxn/opencli/cmd/ocli@latest`

## Spec Format

```yaml
opencliVersion: 1.0.0-alpha.7
info:
  title: My Tool
  binary: mytool
  version: 1.0.0
install:
  - method: go
    value: go install github.com/org/mytool@latest
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
  mytool <subcommand> [flags]:
    summary: Root command
  mytool deploy <env> [flags]:
    summary: Deploy to an environment
    arguments:
      - name: env
        type: string
        required: true
        choices: [staging, production]
        summary: Target environment
    flags:
      - name: dry-run
        type: boolean
        summary: Preview changes without applying
        aliases: [d]
    exitCodes:
      - code: 2
        summary: Deployment failed
```

## Key Spec Rules

- `opencliVersion`: currently `1.0.0-alpha.7`
- Command keys use positional syntax: `binary subcommand <required-arg> [optional-arg] [flags]`
- Required arguments: `<name>`, optional arguments: `[name]`
- Argument types: `string`, `boolean`, `number`
- Flags can have `aliases`, `choices`, `default`, `required`
- `global.flags` apply to all commands; per-command flags are additive
- `global.exitCodes` are inherited; per-command exit codes extend them

## ocli Commands

| Command | Description |
|---------|-------------|
| `ocli specification check -f spec.ocli.yaml` | Validate spec against JSON Schema |
| `ocli specification versions` | List supported OpenCLI versions |
| `ocli generate cli -f spec.ocli.yaml --framework urfavecli` | Generate Go CLI boilerplate |
| `ocli generate cli -f spec.ocli.yaml --framework yargs` | Generate JS/Node CLI boilerplate |
| `ocli generate docs -f spec.ocli.yaml` | Generate Markdown documentation |

## Supported Frameworks

| Framework | Language | Generated Files |
|-----------|----------|-----------------|
| `urfavecli` | Go | `cli_interface.gen.go`, `cli_params.gen.go`, `cli_exitcodes.gen.go`, `cli.gen.go` |
| `yargs` | JavaScript/Node.js | `cli-interface.gen.js`, `cli.gen.js` |

Planned (not yet available): Cobra (Go), oclif (Node.js)

## Inputs

### Required
- **Binary name**: What users will type in the terminal
- **Command structure**: Subcommands, their arguments and flags
- **Language/framework**: Target implementation language

### Optional
- **Exit codes**: Custom exit codes beyond 0/1
- **Global flags**: Flags shared across all commands (e.g., `--verbose`, `--config`)
- **Install methods**: How users install the tool

## Process

### Step 1: Gather CLI requirements
Ask the user (or read from project context):
- What does each command do?
- What arguments are required vs optional?
- What flags exist? Which are boolean vs string?
- Are there global flags?
- What exit codes are meaningful?

### Step 2: Write the spec
Create `<binary-name>.ocli.yaml` in the project root (or `cli/` folder if the project has one).

Follow the spec format above. Use concrete `choices` arrays when values are enumerable.

### Step 3: Validate
```bash
ocli specification check -f <binary-name>.ocli.yaml
```
Fix any validation errors before proceeding.

### Step 4: Generate code
```bash
# For Go projects
ocli generate cli -f <binary-name>.ocli.yaml --framework urfavecli

# For JS/Node projects
ocli generate cli -f <binary-name>.ocli.yaml --framework yargs --module-type esm
```

Generated files have `.gen.` in their names — never edit them manually.

### Step 5: Generate docs
```bash
ocli generate docs -f <binary-name>.ocli.yaml
```
Output: `docs.gen.md` — commit this alongside the spec.

### Step 6: Wire up generated code
Implement the actual command logic by importing and calling the generated interface types. Keep business logic separate from CLI layer.

## Quality Checklist

- [ ] Every command has a `summary`
- [ ] Required arguments use `<name>`, optional use `[name]`
- [ ] Enumerable flag values have `choices` defined
- [ ] Exit codes are documented for non-zero outcomes
- [ ] `ocli specification check` passes with no errors
- [ ] Generated files are committed alongside the spec
- [ ] `.gen.` files are NOT manually edited

## After Completion

- Commit `*.ocli.yaml`, `docs.gen.md`, and all `*.gen.*` files together
- Add `*.gen.*` files to `.gitignore` only if you're regenerating on CI
- Note in `memory.md` which binary this project defines
- If the spec changes, regenerate both code and docs to keep them in sync
