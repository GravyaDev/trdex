#!/bin/bash
# Stop hook — pure deterministic observer. Zero LLM calls.
#
# Called by Claude Code as a type:command hook at turn end.
# Logs a structured verdict to verdicts.jsonl for trend analysis.
# All fields derived from local state (git, failure log) — no LLM.
#
# Quality gate activation has been moved to stuck-detector.sh,
# which fires on real tool failures (3+ of the same category),
# a more reliable signal than an LLM's opinion of "task completion".
#
# Key property: NO output is written to stdout. Anything printed
# here would be surfaced to the main model by Claude Code.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
VERDICT_LOG="$LOG_DIR/verdicts.jsonl"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

mkdir -p "$LOG_DIR"

# ═══════════════════════════════════════════════════════
# Derive task_type from the most recent git commit message
# in the current session (if any). Falls back to "other".
# ═══════════════════════════════════════════════════════
TASK_TYPE="other"
LAST_COMMIT_MSG=$(git -C "$CLAUDE_PROJECT_DIR" log -1 --format=%s 2>/dev/null || echo "")

if [ -n "$LAST_COMMIT_MSG" ]; then
  case "$LAST_COMMIT_MSG" in
    fix*)     TASK_TYPE="debug" ;;
    feat*)    TASK_TYPE="build" ;;
    test*)    TASK_TYPE="test" ;;
    refactor*) TASK_TYPE="refactor" ;;
    docs*)    TASK_TYPE="docs" ;;
    chore*)   TASK_TYPE="admin" ;;
    ci*)      TASK_TYPE="deploy" ;;
    style*)   TASK_TYPE="refactor" ;;
    perf*)    TASK_TYPE="build" ;;
  esac
fi

# ═══════════════════════════════════════════════════════
# Write JSONL verdict — decision is always "allow".
#
# Rationale for removing "block":
# - block was never actionable (the turn is already over)
# - block caused re-injection loops when used with type:prompt
# - block-based quality gate is replaced by stuck-detector.sh
#   which uses real tool failure data, not LLM opinion
# ═══════════════════════════════════════════════════════
jq -n \
  --arg ts "$TIMESTAMP" \
  --arg task_type "$TASK_TYPE" \
  '{timestamp: $ts, decision: "allow", learning: null, task_type: $task_type, reason: null}' \
  >> "$VERDICT_LOG"

# CRITICAL: exit silently. No stdout.
exit 0
