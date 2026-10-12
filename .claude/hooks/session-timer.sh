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

# Canonicalize project dir to prevent path traversal via symlinks or ..
TIMER_DIR="$(cd "${CLAUDE_PROJECT_DIR:-.}" && pwd)"
TIMER_FILE="$TIMER_DIR/.claude/session-timer.json"
ACTION="${1:-status}"

now_iso() {
  date -u +"%Y-%m-%dT%H:%M:%SZ"
}

now_epoch() {
  date +%s
}

iso_to_epoch() {
  local iso="$1"
  # Validate ISO 8601 format before passing to date to prevent injection
  if ! echo "$iso" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$'; then
    echo "0"
    return
  fi
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
    start_iso=$(now_iso)
    start_epoch=$(now_epoch)
    printf '{\n  "started_at": "%s",\n  "started_epoch": %d,\n  "status": "running"\n}\n' \
      "$start_iso" "$start_epoch" > "$TIMER_FILE"
    echo "Session timer started at $start_iso"
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
    stop_iso=$(now_iso)
    printf '{\n  "started_at": "%s",\n  "started_epoch": %d,\n  "stopped_at": "%s",\n  "stopped_epoch": %d,\n  "elapsed_seconds": %d,\n  "elapsed_formatted": "%s",\n  "status": "stopped"\n}\n' \
      "$STARTED_AT" "$START_EPOCH" "$stop_iso" "$NOW_EPOCH" "$ELAPSED" "$FORMATTED" > "$TIMER_FILE"
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
