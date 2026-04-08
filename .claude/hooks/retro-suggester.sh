#!/bin/bash
# SessionStart(user) hook — suggests /retro when 7+ days have passed since the last one.
#
# Trigger: scans Daily Notes/*.md for the most recent occurrence of
# "## Retrospective" (the section header /retro produces). If the most
# recent retro is older than 7 days OR no retro exists at all and there
# are 7+ daily notes accumulated, surface a visible suggestion in
# today's daily note + incident log.
#
# Rationale: the user reports always forgetting /retro. Manual invocation
# is not working — needs an artefact-triggered nudge.
#
# Idempotent intra-day: will not duplicate the suggestion if it has
# already been written to today's daily note.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
DAILY_NOTES_DIR="$CLAUDE_PROJECT_DIR/Daily Notes"
TODAY=$(date +"%Y-%m-%d")
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
THRESHOLD_DAYS=7

# Fast exit: no daily notes directory at all → nothing to suggest
[ ! -d "$DAILY_NOTES_DIR" ] && exit 0

mkdir -p "$LOG_DIR"

# ═══════════════════════════════════════════════════════
# Find the most recent daily note containing "## Retrospective"
# Daily notes use ISO 8601: YYYY-MM-DD.md, sortable lexicographically.
# ═══════════════════════════════════════════════════════
LAST_RETRO_FILE=$(grep -l "^## Retrospective" "$DAILY_NOTES_DIR"/*.md 2>/dev/null | sort -r | head -1)

# Count total daily notes (proxy for "how long has Kloudify been used here")
TOTAL_NOTES=$(find "$DAILY_NOTES_DIR" -maxdepth 1 -name "*.md" -type f 2>/dev/null | wc -l | tr -d ' ')

# ═══════════════════════════════════════════════════════
# Decide whether to suggest
# ═══════════════════════════════════════════════════════
SHOULD_SUGGEST=0
REASON=""

if [ -z "$LAST_RETRO_FILE" ]; then
  # No retro ever — only nudge if there are enough daily notes to warrant it
  if [ "$TOTAL_NOTES" -ge "$THRESHOLD_DAYS" ]; then
    SHOULD_SUGGEST=1
    REASON="No retrospective ever recorded across $TOTAL_NOTES daily notes — first /retro is overdue"
  fi
else
  # Extract the date from the filename (basename without .md)
  LAST_RETRO_DATE=$(basename "$LAST_RETRO_FILE" .md)
  # Validate it looks like YYYY-MM-DD
  if echo "$LAST_RETRO_DATE" | grep -qE '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'; then
    # Compute days elapsed (date arithmetic is portable enough on git-bash/wsl/linux/macos)
    LAST_EPOCH=$(date -d "$LAST_RETRO_DATE" +%s 2>/dev/null || date -j -f "%Y-%m-%d" "$LAST_RETRO_DATE" +%s 2>/dev/null || echo 0)
    NOW_EPOCH=$(date +%s)
    if [ "$LAST_EPOCH" -gt 0 ]; then
      DAYS_ELAPSED=$(( (NOW_EPOCH - LAST_EPOCH) / 86400 ))
      if [ "$DAYS_ELAPSED" -ge "$THRESHOLD_DAYS" ]; then
        SHOULD_SUGGEST=1
        REASON="Last retrospective was $DAYS_ELAPSED days ago ($LAST_RETRO_DATE) — overdue (threshold: $THRESHOLD_DAYS days)"
      fi
    fi
  fi
fi

[ "$SHOULD_SUGGEST" -eq 0 ] && exit 0

# ═══════════════════════════════════════════════════════
# Write alert (idempotent intra-day)
# ═══════════════════════════════════════════════════════
DAILY_NOTE="$DAILY_NOTES_DIR/$TODAY.md"

# Create today's note if missing (mirrors onboard-init-trigger style)
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

# Idempotency: do not duplicate if already alerted today
if ! grep -q "RETRO SUGGESTED" "$DAILY_NOTE" 2>/dev/null; then
  cat >> "$DAILY_NOTE" <<EOF

## ⏰ RETRO SUGGESTED — $TIMESTAMP
$REASON.
**Action**: run \`/retro\` when you have a moment. Reviews patterns, captures learnings, improves the system.
EOF

  echo "- \`$TIMESTAMP\` | RETRO | INFO | $REASON" >> "$INCIDENT_LOG"
fi

exit 0
