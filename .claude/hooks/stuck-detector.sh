#!/bin/bash
# PostToolUseFailure async hook — detects "stuck" patterns and alerts.
#
# Trigger: any tool failure (runs alongside log-failures.sh).
# Action: scan recent failure-log.md entries for repeated failure patterns.
#         If 3+ failures of the SAME CATEGORY appear in a short window, raise
#         an alert in incident-log.md and create a marker file the next
#         SessionStart can consume.
#
# Aggressive mode (b): aggregates by CATEGORY (FILESYSTEM, API, NETWORK, etc.)
# rather than exact error message. False positives are cheap (just an alert),
# missed blocks are expensive (lost user time).
#
# Never blocks. Async. Replaces the manual "notice you're stuck → /unstick"
# with a deterministic detector.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
FAILURE_LOG="$LOG_DIR/failure-log.md"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
STUCK_MARKER="$LOG_DIR/.stuck-detected"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

# Fast exit: failure log doesn't exist yet
[ ! -f "$FAILURE_LOG" ] && exit 0

mkdir -p "$LOG_DIR"

# ═══════════════════════════════════════════════════════
# Window: last 30 entries (proxy for "recent activity").
# Tool failures don't fire constantly, so 30 entries usually
# spans the current working block, not historical noise.
# ═══════════════════════════════════════════════════════
WINDOW=$(tail -30 "$FAILURE_LOG" 2>/dev/null)
[ -z "$WINDOW" ] && exit 0

# ═══════════════════════════════════════════════════════
# Aggregate by CATEGORY (column 3 in pipe-separated format).
# Format reminder: - `TIMESTAMP` | SEVERITY | CATEGORY | TOOL | ERROR
# Single-pass awk: count per category, emit "count category" for the top one.
#
# OTHER is the unclassified-fallback bucket in log-failures.sh. Repeated
# OTHER entries almost always represent unrelated errors (generic exit
# code 1, unusual native errors, etc.) that happen to all miss the
# specific classifier rules — NOT a genuine stuck pattern. Counting OTHER
# caused the gate to fire spuriously whenever heterogeneous bash/read
# errors piled up in the window. We skip OTHER here; if a new error
# class becomes common, add it to log-failures.sh with its own category
# (like CONTEXT) so it can be tracked deliberately.
# ═══════════════════════════════════════════════════════
TOP_LINE=$(echo "$WINDOW" | awk -F'|' '
  {
    gsub(/^[ \t]+|[ \t]+$/, "", $3)
    if ($3 != "" && $3 != "OTHER") counts[$3]++
  }
  END {
    max = 0; top = ""
    for (c in counts) {
      if (counts[c] > max) { max = counts[c]; top = c }
    }
    if (top != "") print max " " top
  }
')
TOP_COUNT=$(echo "$TOP_LINE" | awk '{print $1+0}')
TOP_CATEGORY=$(echo "$TOP_LINE" | awk '{print $2}')

# ═══════════════════════════════════════════════════════
# Threshold: 3+ failures of the same category in the window.
# ═══════════════════════════════════════════════════════
if [ "$TOP_COUNT" -ge 3 ]; then
  # Avoid spamming: only alert if marker is older than 10 minutes (or absent)
  SHOULD_ALERT=1
  if [ -f "$STUCK_MARKER" ]; then
    MARKER_AGE_MIN=$(( ( $(date +%s) - $(stat -c %Y "$STUCK_MARKER" 2>/dev/null || stat -f %m "$STUCK_MARKER" 2>/dev/null || echo 0) ) / 60 ))
    if [ "$MARKER_AGE_MIN" -lt 10 ]; then
      SHOULD_ALERT=0
    fi
  fi

  if [ "$SHOULD_ALERT" -eq 1 ]; then
    # Sample tools involved (last 5)
    SAMPLE_TOOLS=$(echo "$WINDOW" | awk -F'|' -v c="$TOP_CATEGORY" '{gsub(/ /, "", $3); gsub(/^ /, "", $4); gsub(/ $/, "", $4); if ($3==c) print $4}' | tail -5 | tr '\n' ',' | sed 's/,$//')

    echo "- \`$TIMESTAMP\` | STUCK | HIGH | Repeated $TOP_CATEGORY failures detected ($TOP_COUNT in last 30 events) — tools: $SAMPLE_TOOLS — consider /unstick or step back" >> "$INCIDENT_LOG"

    # Activate quality gate — real tool failures are a stronger signal
    # than an LLM verdict. The gate is enforced by check-quality-gate.sh
    # (PreToolUse hook) which hard-blocks dangerous operations.
    GATE_FILE="$LOG_DIR/.quality-gate-active"
    if [ ! -f "$GATE_FILE" ]; then
      touch "$GATE_FILE"
      echo "- \`$TIMESTAMP\` | STUCK | WARN | Quality gate activated — $TOP_COUNT $TOP_CATEGORY failures" >> "$INCIDENT_LOG"
    fi

    # Touch marker so we don't re-alert for 10 minutes
    cat > "$STUCK_MARKER" <<EOF
$TIMESTAMP
category=$TOP_CATEGORY
count=$TOP_COUNT
tools=$SAMPLE_TOOLS
EOF
  fi
fi

exit 0
