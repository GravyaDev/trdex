#!/bin/bash
# PreCompact hook — writes an honest compaction marker and a placeholder
# handoff section in today's daily note.
#
# IMPORTANT: bash hooks cannot read Claude's in-context memory. This hook
# cannot distill session state — only the `/clear` command (run by Claude
# before compaction is triggered) can do that. What this hook CAN do:
#
#   1. Log the compaction event with a precise timestamp
#   2. Write a structured placeholder in the daily note so the next session
#      sees exactly when the cut happened and has a pointer to memory.md /
#      knowledge-base.md / recent daily note entries
#   3. Leave a marker file so post-compact-resume.sh knows it ran
#
# The placeholder is intentionally NOT called a "Session Handoff" — it is
# called "Auto-compaction cut" to distinguish it from the explicit handoff
# produced by `/clear`. If the user wants a real distilled handoff, they
# must run `/clear` BEFORE the auto-compact fires.

TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
TIME_SHORT=$(date +"%H:%M")
TODAY=$(date +"%Y-%m-%d")
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
DAILY_NOTES_DIR="$CLAUDE_PROJECT_DIR/Daily Notes"
DAILY_NOTE="$DAILY_NOTES_DIR/$TODAY.md"
MARKER="$LOG_DIR/.compaction-occurred"

mkdir -p "$LOG_DIR" "$DAILY_NOTES_DIR"

# ═══════════════════════════════════════════════════════
# 1. Write the marker file (consumed by post-compact-resume.sh)
# ═══════════════════════════════════════════════════════
echo "$TIMESTAMP" > "$MARKER"

# ═══════════════════════════════════════════════════════
# 2. Log the event
# ═══════════════════════════════════════════════════════
echo "- \`$TIMESTAMP\` | COMPACTION | INFO | Auto-compaction triggered — bash hook cannot distill state; see daily note placeholder" >> "$INCIDENT_LOG"

# ═══════════════════════════════════════════════════════
# 3. Create today's daily note if missing
# ═══════════════════════════════════════════════════════
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

# ═══════════════════════════════════════════════════════
# 4. Append the auto-compaction placeholder — only once per compaction event
# ═══════════════════════════════════════════════════════
PLACEHOLDER_HEADER="## ⚠️ Auto-compaction cut — $TIME_SHORT"

# Idempotency guard: if the exact same header already exists for this minute,
# do not duplicate. Compaction within the same minute is rare but possible.
if ! grep -qF "$PLACEHOLDER_HEADER" "$DAILY_NOTE" 2>/dev/null; then
  cat >> "$DAILY_NOTE" <<EOF

$PLACEHOLDER_HEADER

**What happened**: auto-compaction was triggered at $TIMESTAMP because context
was full. Kloudify's bash PreCompact hook cannot read Claude's in-context
memory, so **no distilled handoff was written** for this cut.

**To recover session state in the next session, read (in this order)**:
1. \`.claude/memory.md\` — persistent "Now" / Open Threads / Recent Decisions
2. \`.claude/universal-rules.md\` — cross-project rules in effect
3. \`.claude/knowledge-base.md\` — project-specific rules in effect
4. This daily note above this cut — any Decisions / Notes / Session Handoff
   sections written earlier today
5. \`Task Board.md\` — today's priorities and blocked items

**To avoid this next time**: run \`/clear\` BEFORE the context gets full.
\`/clear\` is a Claude-level command that CAN distill state (because it runs
in-context) and will write a real Session Handoff section to this daily note
before stopping. Auto-compaction is a fallback, not a substitute for \`/clear\`.
EOF
fi

exit 0
