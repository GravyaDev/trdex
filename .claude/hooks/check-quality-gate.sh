#!/bin/bash
# PreToolUse hook — enforces quality gate.
#
# When .quality-gate-active exists, stuck-detector.sh has flagged
# this session as having repeated tool failures (3+ of the same
# category). This hook intercepts tool calls to:
#   - HARD BLOCK dangerous/irreversible actions  → logged as "QGATE BLOCK"
#   - SOFT WARN on everything else               → logged as "QGATE WARN"
#   - AUTO-CLEAR when no new failure has landed  → logged as "QGATE CLEAR"
# The three categories are explicit log prefixes so wrap-up-digest.sh
# and weekly retros can compute the block-vs-warn ratio — a signal for
# whether the gate is catching real problems or just adding friction.
#
# Auto-recovery clock reads the `last_failure_ts` field written by
# stuck-detector.sh into the stuck marker. If no new same-category
# failure has been registered for >RECOVERY_WINDOW_SEC, clear the gate.
# This is evidence-based (last NEW failure), not file-mtime-based
# (marker re-touch), which previously kept the gate active across
# productive turns that happened after a resolved failure cluster.
# Manual clear: /clear | /resume | session-reset.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
GATE_FILE="$LOG_DIR/.quality-gate-active"
STUCK_MARKER="$LOG_DIR/.stuck-detected"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
# Per-session marker written after the first warning injection so that
# subsequent PreToolUse calls can emit a short reference instead of the
# full ~400-char rule. The agent reads the full rule once from the
# incident log entry when it was first activated, not repeatedly on
# every tool call while the gate remains active.
WARNING_CACHE="$LOG_DIR/.gate-warning-acknowledged"

# Recovery window: if no new failure has been recorded for this many
# seconds (based on stuck-detector's last_failure_ts), clear the gate.
# Default 600s (10 min). Tunable via env for deployments that want a
# stricter or looser clock.
RECOVERY_WINDOW_SEC="${KLOUDIFY_QGATE_RECOVERY_SEC:-600}"

# Fast path: gate not active → exit silently
[ ! -f "$GATE_FILE" ] && exit 0

# Auto-recovery: marker absent → nothing to gate on, clear immediately
if [ ! -f "$STUCK_MARKER" ]; then
  rm -f "$GATE_FILE" "$WARNING_CACHE"
  TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
  echo "- \`$TIMESTAMP\` | QGATE | CLEAR | Quality gate auto-cleared (stuck marker absent)" >> "$INCIDENT_LOG"
  exit 0
fi
# Evidence-based auto-recovery: read last_failure_ts from the marker
# (written by stuck-detector.sh on each detection). If unavailable,
# fall back to marker mtime for backwards compatibility with markers
# written by older versions of stuck-detector.
LAST_FAILURE_TS=$(grep -E '^last_failure_ts=' "$STUCK_MARKER" 2>/dev/null | head -1 | cut -d= -f2)
if [ -z "$LAST_FAILURE_TS" ]; then
  LAST_FAILURE_TS=$(stat -c %Y "$STUCK_MARKER" 2>/dev/null || stat -f %m "$STUCK_MARKER" 2>/dev/null || echo 0)
fi
TIME_SINCE_LAST_FAILURE=$(( $(date +%s) - LAST_FAILURE_TS ))
if [ "$TIME_SINCE_LAST_FAILURE" -gt "$RECOVERY_WINDOW_SEC" ]; then
  rm -f "$GATE_FILE" "$WARNING_CACHE"
  TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
  MIN_SINCE=$(( TIME_SINCE_LAST_FAILURE / 60 ))
  echo "- \`$TIMESTAMP\` | QGATE | CLEAR | Quality gate auto-cleared after ${MIN_SINCE}min without new failures (recovery window: ${RECOVERY_WINDOW_SEC}s)" >> "$INCIDENT_LOG"
  exit 0
fi

INPUT=$(cat)
TOOL_NAME=$(echo "$INPUT" | jq -r '.tool_name // empty')
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

mkdir -p "$LOG_DIR"

log_incident() {
  local SEVERITY="$1"
  local MSG="$2"
  echo "- \`$TIMESTAMP\` | QGATE | $SEVERITY | $MSG" >> "$INCIDENT_LOG"
}

# Explicit BLOCK vs WARN outcome — single call-site per outcome so the
# log stream is unambiguous for aggregation (wrap-up digest, retro).
log_block() {
  local MSG="$1"
  echo "- \`$TIMESTAMP\` | QGATE | BLOCK | $MSG" >> "$INCIDENT_LOG"
}
log_warn() {
  local MSG="$1"
  echo "- \`$TIMESTAMP\` | QGATE | WARN | $MSG" >> "$INCIDENT_LOG"
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

GATE_WARNING_FULL="QUALITY GATE ACTIVE: stuck-detector.sh has logged 3+ tool failures of the same category in the recent window — the session is likely stuck in a pattern. Operate with extreme caution: (1) explain the intended step before executing, (2) ask user confirmation for any non-trivial action, (3) prefer read-only verification over write operations, (4) do NOT batch multiple changes. The gate auto-clears after 30 minutes without new same-category failures, or immediately via /clear | /resume (which trigger session-reset.sh at the next SessionStart)."
GATE_WARNING_SHORT="QUALITY GATE ACTIVE (see incident-log.md for full rule). Prefer read-only verification; no batched changes; ask before non-trivial writes."

# Pick the warning to inject. Long form on first trigger per session
# (first call while the cache marker is absent), short form thereafter.
# The cache marker is cleared when the gate clears (see auto-recovery
# branches above and on manual /clear via session-reset.sh).
if [ -f "$WARNING_CACHE" ]; then
  GATE_WARNING="$GATE_WARNING_SHORT"
else
  GATE_WARNING="$GATE_WARNING_FULL"
  touch "$WARNING_CACHE"
fi

# ═══════════════════════════════════════════════════════
# HARD BLOCK — dangerous actions forbidden while gate active
# ═══════════════════════════════════════════════════════

case "$TOOL_NAME" in
  Bash)
    COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

    # Escape hatch: always allow removing gate state files themselves,
    # otherwise the gate becomes unrecoverable without restarting the session.
    if echo "$COMMAND" | grep -qE '\.(quality-gate-active|stuck-detected)'; then
      exit 0
    fi

    # Irreversible / shared-state git operations
    if echo "$COMMAND" | grep -qE '\bgit\s+(push|commit|reset|merge|rebase|cherry-pick|revert|tag)\b'; then
      log_block "git mutation → $COMMAND"
      deny "QUALITY GATE: git mutations are forbidden while the gate is active." "$GATE_WARNING Specifically blocked: git push/commit/reset/merge/rebase/cherry-pick/revert/tag. Resolve the gate first (3 clean turns or /clear)."
    fi

    # Destructive filesystem operations
    if echo "$COMMAND" | grep -qE '\b(rm|mv|cp)\s+-[a-zA-Z]*[rfR]'; then
      log_block "destructive fs → $COMMAND"
      deny "QUALITY GATE: recursive/force filesystem operations are forbidden while the gate is active." "$GATE_WARNING"
    fi

    # Deploy / publish / release operations
    if echo "$COMMAND" | grep -qE '\b(docker\s+(run|build|push|compose)|kubectl\s+(apply|delete|create)|npm\s+publish|pnpm\s+publish|yarn\s+publish|cargo\s+publish|pip\s+(install|uninstall)|pipx\s+(install|uninstall)|uv\s+(add|remove))\b'; then
      log_block "deploy/publish → $COMMAND"
      deny "QUALITY GATE: deploy/publish/package-management operations are forbidden while the gate is active." "$GATE_WARNING"
    fi
    ;;

  Write|Edit)
    FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')

    # Critical config files — never write while gate active
    if echo "$FILE_PATH" | grep -qE '\.claude/settings\.json$|\.env$|\.env\.|package\.json$|Cargo\.toml$|pyproject\.toml$|pnpm-workspace\.yaml$'; then
      log_block "critical config write → $FILE_PATH"
      deny "QUALITY GATE: writes to critical config files are forbidden while the gate is active." "$GATE_WARNING Blocked file: $FILE_PATH"
    fi
    ;;
esac

# ═══════════════════════════════════════════════════════
# SOFT WARN — everything else allowed with cautionary context
# ═══════════════════════════════════════════════════════

log_warn "$TOOL_NAME allowed with warning"
warn "$GATE_WARNING"
