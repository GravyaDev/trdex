#!/bin/bash
# PreToolUse hook — enforces quality gate.
#
# When .quality-gate-active exists, the stop-hook judge has flagged
# this session as low-quality (2+ blocks). This hook intercepts tool
# calls to:
#   - HARD BLOCK dangerous/irreversible actions
#   - SOFT WARN on everything else via additionalContext
#
# The gate clears automatically after 3 consecutive "allow" verdicts
# (handled in log-stop-verdict.sh), or manually via /clear | /resume.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
GATE_FILE="$LOG_DIR/.quality-gate-active"
INCIDENT_LOG="$LOG_DIR/incident-log.md"

# Fast path: gate not active → exit silently
[ ! -f "$GATE_FILE" ] && exit 0

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

mkdir -p "$LOG_DIR"

log_incident() {
  local SEVERITY="$1"
  local MSG="$2"
  echo "- \`$TIMESTAMP\` | QGATE | $SEVERITY | $MSG" >> "$INCIDENT_LOG"
}

deny() {
  local REASON="$1"
  local CONTEXT="$2"
  jq -n \
    --arg reason "$REASON" \
    --arg context "$CONTEXT" \
    '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason,
        additionalContext: $context
      }
    }'
  exit 0
}

warn() {
  local CONTEXT="$1"
  jq -n \
    --arg context "$CONTEXT" \
    '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        additionalContext: $context
      }
    }'
  exit 0
}

GATE_WARNING="QUALITY GATE ACTIVE: The session judge has flagged recent turns as low-quality (2+ verdict blocks). Operate with extreme caution: (1) explain the intended step before executing, (2) ask user confirmation for any non-trivial action, (3) prefer read-only verification over write operations, (4) do NOT batch multiple changes. The gate clears after 3 consecutive clean turns or via /clear | /resume."

# ═══════════════════════════════════════════════════════
# HARD BLOCK — dangerous actions forbidden while gate active
# ═══════════════════════════════════════════════════════

case "$TOOL_NAME" in
  Bash)
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

    # Irreversible / shared-state git operations
    if echo "$COMMAND" | grep -qE '\bgit\s+(push|commit|reset|merge|rebase|cherry-pick|revert|tag)\b'; then
      log_incident "HIGH" "QGATE BLOCK: git mutation → $COMMAND"
      deny "QUALITY GATE: git mutations are forbidden while the gate is active." "$GATE_WARNING Specifically blocked: git push/commit/reset/merge/rebase/cherry-pick/revert/tag. Resolve the gate first (3 clean turns or /clear)."
    fi

    # Destructive filesystem operations
    if echo "$COMMAND" | grep -qE '\b(rm|mv|cp)\s+-[a-zA-Z]*[rfR]'; then
      log_incident "HIGH" "QGATE BLOCK: destructive fs → $COMMAND"
      deny "QUALITY GATE: recursive/force filesystem operations are forbidden while the gate is active." "$GATE_WARNING"
    fi

    # Deploy / publish / release operations
    if echo "$COMMAND" | grep -qE '\b(docker\s+(run|build|push|compose)|kubectl\s+(apply|delete|create)|npm\s+publish|pnpm\s+publish|yarn\s+publish|cargo\s+publish|pip\s+(install|uninstall)|pipx\s+(install|uninstall)|uv\s+(add|remove))\b'; then
      log_incident "HIGH" "QGATE BLOCK: deploy/publish → $COMMAND"
      deny "QUALITY GATE: deploy/publish/package-management operations are forbidden while the gate is active." "$GATE_WARNING"
    fi
    ;;

  Write|Edit)
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

    # Critical config files — never write while gate active
    if echo "$FILE_PATH" | grep -qE '\.claude/settings\.json$|\.env$|\.env\.|package\.json$|Cargo\.toml$|pyproject\.toml$|pnpm-workspace\.yaml$'; then
      log_incident "HIGH" "QGATE BLOCK: critical config write → $FILE_PATH"
      deny "QUALITY GATE: writes to critical config files are forbidden while the gate is active." "$GATE_WARNING Blocked file: $FILE_PATH"
    fi
    ;;
esac

# ═══════════════════════════════════════════════════════
# SOFT WARN — everything else allowed with cautionary context
# ═══════════════════════════════════════════════════════

log_incident "LOW" "QGATE WARN: $TOOL_NAME allowed with warning"
warn "$GATE_WARNING"
