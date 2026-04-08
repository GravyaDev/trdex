#!/bin/bash
# SessionStart(user) hook — suggests /debt-map when 20+ new TODO/FIXME/HACK
# markers have accumulated since the last baseline.
#
# Trigger: counts TODO/FIXME/HACK/XXX/TEMP/WORKAROUND markers across
# source files (conservative file extension whitelist) and compares to
# the baseline stored in .claude/logs/.debt-count-baseline. If the delta
# is >= 20, surface a suggestion in today's daily note + incident log
# AND update the baseline so the user is not re-pestered immediately.
#
# Conservative scan strategy (option A from design discussion):
# - Only well-known source extensions
# - Excludes .claude/, node_modules/, .git/, vendor/, dist/, build/,
#   target/, .venv/, venv/, __pycache__/, everything-claude-code/
# - Bounded by find with -prune for speed on monorepos
#
# Idempotent via baseline file: every successful alert updates the
# baseline to the current count, so the next alert requires another
# +20 delta. Initial run (no baseline) seeds the baseline silently
# without alerting.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
BASELINE_FILE="$LOG_DIR/.debt-count-baseline"
DAILY_NOTES_DIR="$CLAUDE_PROJECT_DIR/Daily Notes"
TODAY=$(date +"%Y-%m-%d")
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
THRESHOLD=20

mkdir -p "$LOG_DIR"

# ═══════════════════════════════════════════════════════
# Count TODO/FIXME/HACK/XXX/TEMP/WORKAROUND across whitelisted extensions
# Use grep -c on each file via find -exec, then sum.
# ═══════════════════════════════════════════════════════
CURRENT_COUNT=$(find "$CLAUDE_PROJECT_DIR" \
  \( \
    -path "*/.claude" -o \
    -path "*/.git" -o \
    -path "*/node_modules" -o \
    -path "*/vendor" -o \
    -path "*/dist" -o \
    -path "*/build" -o \
    -path "*/target" -o \
    -path "*/.venv" -o \
    -path "*/venv" -o \
    -path "*/__pycache__" -o \
    -path "*/everything-claude-code" \
  \) -prune -o \
  -type f \( \
    -name "*.py" -o \
    -name "*.js" -o \
    -name "*.ts" -o \
    -name "*.tsx" -o \
    -name "*.jsx" -o \
    -name "*.go" -o \
    -name "*.rs" -o \
    -name "*.java" -o \
    -name "*.cs" -o \
    -name "*.rb" -o \
    -name "*.php" -o \
    -name "*.cpp" -o \
    -name "*.c" -o \
    -name "*.h" -o \
    -name "*.hpp" \
  \) -print 2>/dev/null \
  | xargs -r grep -cE '\b(TODO|FIXME|HACK|XXX|TEMP|WORKAROUND)\b' 2>/dev/null \
  | awk -F: '{ sum += $NF } END { print sum+0 }')

# Defensive: ensure CURRENT_COUNT is numeric
case "$CURRENT_COUNT" in
  ''|*[!0-9]*) CURRENT_COUNT=0 ;;
esac

# ═══════════════════════════════════════════════════════
# Read baseline (or seed it on first run, silently)
# ═══════════════════════════════════════════════════════
if [ ! -f "$BASELINE_FILE" ]; then
  # First run — seed baseline, do not alert
  echo "$CURRENT_COUNT" > "$BASELINE_FILE"
  echo "- \`$TIMESTAMP\` | DEBT | INFO | Baseline seeded at $CURRENT_COUNT TODO/FIXME markers" >> "$INCIDENT_LOG"
  exit 0
fi

BASELINE_COUNT=$(cat "$BASELINE_FILE" 2>/dev/null | tr -d '[:space:]')
case "$BASELINE_COUNT" in
  ''|*[!0-9]*) BASELINE_COUNT=0 ;;
esac

DELTA=$((CURRENT_COUNT - BASELINE_COUNT))

# ═══════════════════════════════════════════════════════
# Decide
# ═══════════════════════════════════════════════════════
if [ "$DELTA" -lt "$THRESHOLD" ]; then
  # Not enough new debt — exit silently. Do NOT update baseline (only
  # update on alert, so the count keeps accumulating).
  exit 0
fi

# ═══════════════════════════════════════════════════════
# Write alert (idempotent intra-day) and update baseline
# ═══════════════════════════════════════════════════════
mkdir -p "$DAILY_NOTES_DIR"
DAILY_NOTE="$DAILY_NOTES_DIR/$TODAY.md"

if [ ! -f "$DAILY_NOTE" ]; then
  cat > "$DAILY_NOTE" <<EOF
# $TODAY - Daily Work Log

## Decisions
-

## Meetings & Conversations
-

## Notes
-

## End of Day Summary
-
EOF
fi

if ! grep -q "DEBT SUGGESTED" "$DAILY_NOTE" 2>/dev/null; then
  cat >> "$DAILY_NOTE" <<EOF

## 📋 DEBT SUGGESTED — $TIMESTAMP
$DELTA new TODO/FIXME/HACK markers since last baseline ($BASELINE_COUNT → $CURRENT_COUNT). Threshold: $THRESHOLD.
**Action**: run \`/debt-map\` when convenient. Maps and prioritises technical debt with impact/effort scoring.
EOF

  echo "- \`$TIMESTAMP\` | DEBT | INFO | $DELTA new debt markers (threshold $THRESHOLD): baseline $BASELINE_COUNT → current $CURRENT_COUNT" >> "$INCIDENT_LOG"

  # Update baseline to current count so we don't re-alert immediately
  echo "$CURRENT_COUNT" > "$BASELINE_FILE"
fi

exit 0
