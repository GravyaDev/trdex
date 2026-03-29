#!/bin/bash
# PostToolUse hook — logs tool failures to incident log.
# Categories: BUILD, API, FILESYSTEM, NETWORK, PERMISSION, OTHER
# Severities: CRITICAL, ERROR, WARN, INFO

INPUT=$(cat)
TOOL=$(echo "$INPUT" | jq -r '.tool_name // empty' 2>/dev/null)
# Claude Code may pass error in different fields depending on version
ERROR=$(echo "$INPUT" | jq -r '.error_message // .error // .tool_result // empty' 2>/dev/null | head -5)
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
FAILURE_LOG="$LOG_DIR/failure-log.md"
INCIDENT_LOG="$LOG_DIR/incident-log.md"

mkdir -p "$LOG_DIR"

# Skip entirely if both TOOL and ERROR are empty (hook fired spuriously)
if [ -z "$TOOL" ] && [ -z "$ERROR" ]; then
  # Write raw input to a debug file for investigation, then exit silently
  echo "[$TIMESTAMP] empty input: $(echo "$INPUT" | head -c 200)" >> "$LOG_DIR/hook-debug.log"
  exit 0
fi

# Categorize the failure
CATEGORY="OTHER"
SEVERITY="ERROR"

case "$ERROR" in
  *"ENOENT"*|*"No such file"*|*"not found"*)
    CATEGORY="FILESYSTEM"
    SEVERITY="WARN"
    ;;
  *"EACCES"*|*"Permission denied"*|*"EPERM"*)
    CATEGORY="PERMISSION"
    SEVERITY="ERROR"
    ;;
  *"ECONNREFUSED"*|*"ETIMEDOUT"*|*"fetch failed"*|*"network"*)
    CATEGORY="NETWORK"
    SEVERITY="ERROR"
    ;;
  *"401"*|*"403"*|*"429"*|*"500"*|*"API"*|*"rate limit"*)
    CATEGORY="API"
    SEVERITY="ERROR"
    ;;
  *"build"*|*"compile"*|*"syntax"*|*"TypeError"*|*"ReferenceError"*)
    CATEGORY="BUILD"
    SEVERITY="ERROR"
    ;;
  *"CRITICAL"*|*"fatal"*|*"panic"*)
    SEVERITY="CRITICAL"
    ;;
esac

# Truncate error for log readability
SHORT_ERROR=$(echo "$ERROR" | head -1 | cut -c1-200)

# Write to failure log
echo "- \`$TIMESTAMP\` | $SEVERITY | $CATEGORY | $TOOL | $SHORT_ERROR" >> "$FAILURE_LOG"

# Also write to incident log if ERROR or CRITICAL
if [ "$SEVERITY" = "ERROR" ] || [ "$SEVERITY" = "CRITICAL" ]; then
  echo "- \`$TIMESTAMP\` | FAILURE | $SEVERITY | $CATEGORY | $TOOL | $SHORT_ERROR" >> "$INCIDENT_LOG"
fi

exit 0
