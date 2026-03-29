#!/bin/bash
# PostToolUse hook: validate OpenCLI spec files after Write or Edit.
#
# Triggers on any *.ocli.yaml or *.ocli.json file.
# Runs `ocli specification check` and logs the result.
# Non-blocking: warns on failure but does not prevent the write from landing.
#
# Requires: ocli installed and on PATH
#   go install github.com/bcdxn/opencli/cmd/ocli@latest

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"

mkdir -p "$LOG_DIR"

# Only act on .ocli.yaml / .ocli.json files
case "$FILE_PATH" in
  *.ocli.yaml|*.ocli.json) ;;
  *) exit 0 ;;
esac

# Check that ocli is available
if ! command -v ocli &>/dev/null; then
  echo "⚠️  ocli not found — skipping spec validation for $FILE_PATH" >&2
  echo "   Install with: go install github.com/bcdxn/opencli/cmd/ocli@latest" >&2
  exit 0
fi

# Run validation
RESULT=$(ocli specification check -f "$FILE_PATH" 2>&1)
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
  echo "✓ OpenCLI spec valid: $FILE_PATH" >&2
  echo "- \`$TIMESTAMP\` | OCLI-VALIDATE | OK | Spec valid → $FILE_PATH" >> "$INCIDENT_LOG"
else
  echo "⚠️  OpenCLI spec validation failed: $FILE_PATH" >&2
  echo "$RESULT" >&2
  echo "" >&2
  echo "Fix the spec and save again. Run: ocli specification check -f $FILE_PATH" >&2
  echo "- \`$TIMESTAMP\` | OCLI-VALIDATE | WARN | Spec invalid → $FILE_PATH | $RESULT" >> "$INCIDENT_LOG"
fi

exit 0
