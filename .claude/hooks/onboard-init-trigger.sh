#!/bin/bash
# SessionStart(user) hook — detects pending onboarding and signals it.
#
# Trigger: presence of __NEEDS_ONBOARD sentinel file in project root.
# Action: append a high-visibility alert to today's daily note + incident log.
# Does NOT auto-execute /onboard-init (the command is interactive and needs the user).
#
# Rationale: replaces the manual "if __NEEDS_ONBOARD exists, run /onboard-init"
# instruction in CLAUDE.md with a deterministic artefact-triggered alert.

SENTINEL="$CLAUDE_PROJECT_DIR/__NEEDS_ONBOARD"
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
DAILY_NOTES_DIR="$CLAUDE_PROJECT_DIR/Daily Notes"
TODAY=$(date +"%Y-%m-%d")
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

# Fast exit: no sentinel, nothing to do
[ ! -f "$SENTINEL" ] && exit 0

mkdir -p "$LOG_DIR" "$DAILY_NOTES_DIR"

# Log to incident log (machine-readable trail)
echo "- \`$TIMESTAMP\` | ONBOARD | INFO | Pending onboarding detected (__NEEDS_ONBOARD present) — user should run /onboard-init" >> "$INCIDENT_LOG"

# Append visible alert to today's daily note (creates if missing)
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

# Only append the alert if it's not already there for today
if ! grep -q "ONBOARDING PENDING" "$DAILY_NOTE" 2>/dev/null; then
  cat >> "$DAILY_NOTE" <<EOF

## ⚠️ ONBOARDING PENDING — $TIMESTAMP
The sentinel file \`__NEEDS_ONBOARD\` is present in the project root.
This means first-time onboarding has not been completed.
**Action required**: run \`/onboard-init\` to scan the project, generate profile files, and configure the system.
EOF
fi

exit 0
