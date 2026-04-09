#!/usr/bin/env bash
# Session timer — tracks real working hours.
#
# Usage:
#   session-timer.sh start   — record session start time
#   session-timer.sh stop    — compute elapsed, return summary
#   session-timer.sh status  — show current elapsed (if running)
#   session-timer.sh guard   — check if a previous session was not stopped
#
# Timer file: .claude/session-timer.json
# Format: {"started_at":"ISO8601","status":"running|stopped","elapsed_seconds":N}

set -euo pipefail

TIMER_FILE="${CLAUDE_PROJECT_DIR:-.}/.claude/session-timer.json"
ACTION="${1:-status}"

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

now_epoch() {
  date +%s
}

iso_to_epoch() {
  local iso="$1"
  # Handle both GNU and BSD date
  if date -d "$iso" +%s 2>/dev/null; then
    return
  fi
  # BSD/macOS fallback
  date -jf "%Y-%m-%dT%H:%M:%SZ" "$iso" +%s 2>/dev/null || echo "0"
}

format_duration() {
  local total_seconds="$1"
  local hours=$((total_seconds / 3600))
  local minutes=$(( (total_seconds % 3600) / 60 ))

  if [ "$hours" -gt 0 ]; then
    printf "%dh %02dm" "$hours" "$minutes"
  else
    printf "%dm" "$minutes"
  fi
}

case "$ACTION" in
  start)
    cat > "$TIMER_FILE" << EOF
{
  "started_at": "$(now_iso)",
  "started_epoch": $(now_epoch),
  "status": "running"
}
EOF
    echo "Session timer started at $(now_iso)"
    ;;

  stop)
    if [ ! -f "$TIMER_FILE" ]; then
      echo "No timer running."
      exit 0
    fi

    STATUS=$(grep -o '"status" *: *"[^"]*"' "$TIMER_FILE" | grep -o '"[^"]*"$' | tr -d '"')
    if [ "$STATUS" != "running" ]; then
      echo "Timer is not running (status: $STATUS)."
      exit 0
    fi

    START_EPOCH=$(grep -o '"started_epoch" *: *[0-9]*' "$TIMER_FILE" | grep -o '[0-9]*$')
    NOW_EPOCH=$(now_epoch)
    ELAPSED=$((NOW_EPOCH - START_EPOCH))
    FORMATTED=$(format_duration "$ELAPSED")

    # Update the timer file with final state
    STARTED_AT=$(grep -o '"started_at" *: *"[^"]*"' "$TIMER_FILE" | grep -o '"[^"]*"$' | tr -d '"')
    cat > "$TIMER_FILE" << EOF
{
  "started_at": "$STARTED_AT",
  "started_epoch": $START_EPOCH,
  "stopped_at": "$(now_iso)",
  "stopped_epoch": $NOW_EPOCH,
  "elapsed_seconds": $ELAPSED,
  "elapsed_formatted": "$FORMATTED",
  "status": "stopped"
}
EOF
    echo "$FORMATTED"
    ;;

  status)
    if [ ! -f "$TIMER_FILE" ]; then
      echo "No timer file found."
      exit 0
    fi

    STATUS=$(grep -o '"status" *: *"[^"]*"' "$TIMER_FILE" | grep -o '"[^"]*"$' | tr -d '"')
    if [ "$STATUS" != "running" ]; then
      # Show last session's elapsed if available
      LAST=$(grep -o '"elapsed_formatted" *: *"[^"]*"' "$TIMER_FILE" | grep -o '"[^"]*"$' | tr -d '"' || echo "")
      if [ -n "$LAST" ]; then
        echo "Timer stopped. Last session: $LAST"
      else
        echo "Timer not running."
      fi
      exit 0
    fi

    START_EPOCH=$(grep -o '"started_epoch" *: *[0-9]*' "$TIMER_FILE" | grep -o '[0-9]*$')
    NOW_EPOCH=$(now_epoch)
    ELAPSED=$((NOW_EPOCH - START_EPOCH))
    FORMATTED=$(format_duration "$ELAPSED")
    echo "Running: $FORMATTED"
    ;;

  guard)
    # Called by /start — checks if previous session was not properly closed
    if [ ! -f "$TIMER_FILE" ]; then
      exit 0
    fi

    STATUS=$(grep -o '"status" *: *"[^"]*"' "$TIMER_FILE" | grep -o '"[^"]*"$' | tr -d '"')
    if [ "$STATUS" = "running" ]; then
      START_EPOCH=$(grep -o '"started_epoch" *: *[0-9]*' "$TIMER_FILE" | grep -o '[0-9]*$')
      STARTED_AT=$(grep -o '"started_at" *: *"[^"]*"' "$TIMER_FILE" | grep -o '"[^"]*"$' | tr -d '"')
      NOW_EPOCH=$(now_epoch)
      ELAPSED=$((NOW_EPOCH - START_EPOCH))
      FORMATTED=$(format_duration "$ELAPSED")
      echo "WARNING: Previous session started at $STARTED_AT was never stopped ($FORMATTED elapsed)."
      echo "STALE_SESSION|$STARTED_AT|$ELAPSED|$FORMATTED"
    fi
    ;;

  *)
    echo "Usage: session-timer.sh {start|stop|status|guard}"
    exit 1
    ;;
esac
