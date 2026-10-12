#!/bin/bash
# PostToolUse async hook — counts consecutive successful tool calls and
# clears the quality gate after a configurable streak of clean turns.
#
# Why this exists: check-quality-gate.sh clears the gate on elapsed time
# with no new failures (default 600s). That handles idle sessions well
# but is slow to react when the session is actively recovering with
# many successful calls in a short window. A 5-turn clean streak is a
# stronger positive signal than "10 minutes of silence" and lets the
# agent keep working without waiting for a clock.
#
# Counter file: $LOG_DIR/.success-streak-counter (plain integer).
# Reset rule: stuck-detector.sh writes `last_failure_ts` to the stuck
# marker on each new detection. This hook reads that timestamp and, if
# it changed since the last success tick, resets the counter to 1.
# Otherwise increments.
#
# Never blocks. Async. Pure shell.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
GATE_FILE="$LOG_DIR/.quality-gate-active"
STUCK_MARKER="$LOG_DIR/.stuck-detected"
COUNTER_FILE="$LOG_DIR/.success-streak-counter"
STATE_FILE="$LOG_DIR/.success-streak-state"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

# Configurable streak threshold. Default 5 successful turns clears gate.
STREAK_THRESHOLD="${KLOUDIFY_QGATE_STREAK_THRESHOLD:-5}"

# Fast path: gate not active → nothing to clear, skip work.
[ ! -f "$GATE_FILE" ] && exit 0

mkdir -p "$LOG_DIR"

# ═══════════════════════════════════════════════════════
# Read the last known last_failure_ts we reacted to. If the marker's
# current last_failure_ts is different, a new failure landed since our
# last tick → reset the streak. Otherwise increment.
# ═══════════════════════════════════════════════════════
CURRENT_LAST_FAILURE_TS=""
if [ -f "$STUCK_MARKER" ]; then
  CURRENT_LAST_FAILURE_TS=$(grep -E '^last_failure_ts=' "$STUCK_MARKER" 2>/dev/null | head -1 | cut -d= -f2)
fi

PREVIOUS_LAST_FAILURE_TS=""
if [ -f "$STATE_FILE" ]; then
  PREVIOUS_LAST_FAILURE_TS=$(cat "$STATE_FILE" 2>/dev/null)
fi

if [ "$CURRENT_LAST_FAILURE_TS" != "$PREVIOUS_LAST_FAILURE_TS" ]; then
  # A new failure landed (or the marker was rewritten). Reset.
  COUNTER=1
else
  COUNTER=$(cat "$COUNTER_FILE" 2>/dev/null || echo 0)
  COUNTER=$((COUNTER + 1))
fi

echo "$COUNTER" > "$COUNTER_FILE"
echo "$CURRENT_LAST_FAILURE_TS" > "$STATE_FILE"

# ═══════════════════════════════════════════════════════
# Clear gate when the streak threshold is reached.
# ═══════════════════════════════════════════════════════
if [ "$COUNTER" -ge "$STREAK_THRESHOLD" ]; then
  rm -f "$GATE_FILE"
  rm -f "$COUNTER_FILE"
  rm -f "$STATE_FILE"
  echo "- \`$TIMESTAMP\` | QGATE | CLEAR | Quality gate auto-cleared after $STREAK_THRESHOLD consecutive successful tool calls (streak recovery)" >> "$INCIDENT_LOG"
fi

exit 0
