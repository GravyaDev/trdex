#!/bin/bash
# SessionStart(compact) hook — points Claude to recovery anchors after auto-compaction.
#
# Runs on a fresh session that Claude Code opens automatically after an
# auto-compact event. The previous session's PreCompact hook left a marker
# file and wrote an "Auto-compaction cut" placeholder in the daily note.
#
# This hook's job is MINIMAL:
#   1. Reset session counters (gate files)
#   2. Detect that compaction occurred
#   3. Inject a SHORT, HONEST prompt that points Claude to the right
#      recovery files — WITHOUT instructing a bulk re-read or a
#      "seamless resume" loop
#
# Critical design principle: this hook must NOT instruct Claude to
# "continue working on whatever task was in progress" or "resume
# seamlessly". Those instructions caused an observed incident
# (2026-04-08) where a fresh post-compact session re-loaded the daily
# note, read the old todo list, and restarted operations — re-saturating
# the context that compaction had just freed.
#
# Recovery is a USER DECISION, not an automatic behavior. This hook
# tells Claude "here is where state lives", not "go re-execute".

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
MARKER="$LOG_DIR/.compaction-occurred"

# Fast exit: no compaction occurred → nothing to do
if [ ! -f "$MARKER" ]; then
  exit 0
fi

# ═══════════════════════════════════════════════════════
# Reset session counters (these are per-session state that
# must start fresh after any session boundary, including post-compact)
# ═══════════════════════════════════════════════════════
# NOTE: we intentionally do NOT rm -f these files because the guard
# blocks rm -f on non-whitelisted paths. .claude/logs/ IS in the guard
# whitelist, so this is the legitimate allowed case.
rm -f "$LOG_DIR/.tool-call-count" "$LOG_DIR/.quality-gate-active" "$LOG_DIR/.stuck-detected" 2>/dev/null

# Read compaction timestamp from marker
COMPACT_TIME=$(cat "$MARKER" 2>/dev/null || echo "unknown time")

# Clean up the marker so the next fresh session doesn't re-trigger
rm -f "$MARKER" 2>/dev/null

# ═══════════════════════════════════════════════════════
# Inject a short, honest orientation prompt for Claude
# ═══════════════════════════════════════════════════════
cat <<EOF
POST-COMPACTION ORIENTATION

Auto-compaction cut the previous session at $COMPACT_TIME. The context you
are seeing now is fresh — most of the previous conversation is gone.

State recovery is NOT automatic. The previous session's bash PreCompact
hook cannot read Claude's in-context memory, so no distilled handoff was
written. An "Auto-compaction cut" placeholder was appended to today's
daily note marking exactly when the cut happened.

If the user wants to resume the previous task:
  - Read the daily note section above the "Auto-compaction cut" marker
    for any earlier Decisions, Notes, or Session Handoff entries.
  - Read .claude/memory.md for persistent "Now" / Open Threads / Recent
    Decisions (if the previous session wrote to it).
  - Wait for the user to tell you what to do next.

Do NOT bulk-re-read memory.md + universal-rules.md + knowledge-base.md
+ daily note + files from memory's "Files touched" list. That would
re-inflate the context compaction just freed. Only read what the user's
next instruction actually needs.

Do NOT "seamlessly resume" any task from the previous session. The user
may want to pivot to something else. Wait for their input before taking
any non-trivial action.
EOF

# ═══════════════════════════════════════════════════════
# Inject universal-rules.md + knowledge-base.md into post-compact context.
# This mirrors session-reset.sh — the compact boundary is a fresh session
# from the rules-loading perspective, and skipping this is exactly how the
# 2026-04-08 commit-identity violation happened (compact-resume bypassed
# the rule load that /start would have done on a cold session).
# ═══════════════════════════════════════════════════════
UNIVERSAL="$CLAUDE_PROJECT_DIR/.claude/universal-rules.md"
KB="$CLAUDE_PROJECT_DIR/.claude/knowledge-base.md"

if [ -f "$UNIVERSAL" ] || [ -f "$KB" ]; then
  echo ""
  echo "═══════════════════════════════════════════════════════"
  echo "MANDATORY RULES (auto-loaded after compaction)"
  echo "═══════════════════════════════════════════════════════"
  echo ""
  echo "These rules are re-injected at every compact boundary because"
  echo "the previous session's in-context rule awareness was lost with"
  echo "the compaction. You MUST respect them without needing to"
  echo "re-read the source files."
  echo ""

  if [ -f "$UNIVERSAL" ]; then
    echo "─── .claude/universal-rules.md (cross-project) ───"
    cat "$UNIVERSAL"
    echo ""
  fi

  if [ -f "$KB" ]; then
    echo "─── .claude/knowledge-base.md (project-specific) ───"
    cat "$KB"
    echo ""
  fi

  echo "═══════════════════════════════════════════════════════"
  echo "END OF MANDATORY RULES"
  echo "═══════════════════════════════════════════════════════"
fi

exit 0
