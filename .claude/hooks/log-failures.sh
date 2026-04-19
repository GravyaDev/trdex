#!/bin/bash
# PostToolUse hook — logs tool failures to incident log.
# Categories: BUILD, API, FS_PATH, FS_PERM, FS_SPACE, FS_LOCK,
#             NETWORK, PERMISSION, CONTEXT, OTHER
# Severities: CRITICAL, ERROR, WARN, INFO
#
# CONTEXT is reserved for failures where the agent exceeded a token /
# context budget (file too large, context window full, output too long).
# Repeated CONTEXT failures are a real stuck pattern — the agent should
# switch to offset/limit reads, grep, or smaller edits — and are counted
# by stuck-detector.sh. OTHER is an unclassified-fallback bucket and is
# intentionally excluded from stuck counting (unrelated errors in OTHER
# do not constitute a repeated pattern).
#
# FILESYSTEM is split into four sub-categories because the failure
# modes have wildly different root causes and deserve different stuck
# thresholds:
#   FS_PATH   — wrong path, file not found, is-a-directory. Normal
#               while an agent orients in a large repo; high threshold.
#   FS_PERM   — permission denied. Real infra problem; low threshold.
#   FS_SPACE  — disk full, quota exceeded. Catastrophic; lowest
#               threshold (fires almost immediately).
#   FS_LOCK   — file locked, already exists, resource busy. Concurrency;
#               medium threshold.
# Per-sub-category thresholds live in stuck-detector.sh.

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
  # FS_SPACE — disk / quota. Match first; highest impact.
  *"ENOSPC"*|*"No space left"*|*"disk full"*|*"quota exceeded"*|*"Disk quota"*)
    CATEGORY="FS_SPACE"
    SEVERITY="CRITICAL"
    ;;
  # FS_LOCK — concurrency / existence conflicts.
  *"EEXIST"*|*"File exists"*|*"EBUSY"*|*"resource busy"*|*"EAGAIN"*|*"lock held"*|*"already locked"*)
    CATEGORY="FS_LOCK"
    SEVERITY="ERROR"
    ;;
  # FS_PATH — wrong path, missing file, is-a-directory (benign).
  *"ENOENT"*|*"No such file"*|*"not found"*|*"EISDIR"*|*"Is a directory"*|*"illegal operation on a directory"*)
    CATEGORY="FS_PATH"
    SEVERITY="WARN"
    ;;
  # FS_PERM — permission on filesystem (distinct from PERMISSION which
  # is broader). Match after FS_PATH so benign directory-read failures
  # on restricted subtrees don't get tagged as PERM first.
  *"EACCES"*|*"Permission denied"*|*"EPERM"*|*"Operation not permitted"*)
    CATEGORY="FS_PERM"
    SEVERITY="ERROR"
    ;;
  # Legacy PERMISSION kept for non-filesystem auth failures (401-like
  # locally-raised errors that don't go through the API branch).
  *"unauthorized"*|*"not authorized"*)
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
  *"exceeds maximum allowed tokens"*|*"context window"*|*"too many tokens"*|*"prompt is too long"*|*"maximum context length"*)
    CATEGORY="CONTEXT"
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
