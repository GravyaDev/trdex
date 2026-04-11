#!/bin/bash
# Stop hook — pure observer mode.
#
# Called by Claude Code as a type: command hook at turn end. Receives
# the session transcript on stdin. Extracts the last user+assistant
# exchange, calls Haiku via `claude -p` with a tight JSON-only prompt,
# parses the verdict, logs it, updates quality-gate state.
#
# Key property: NO output is written to stdout. type: command hooks
# that print to stdout would have their output surfaced as additional
# context to the main model — exactly the re-injection loop we are
# fixing. Everything goes to log files only.
#
# Tracks session blocks and activates quality gate at >=2 blocks.
# Auto-clears the gate after 3 consecutive "allow" verdicts.

LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
VERDICT_LOG="$LOG_DIR/verdicts.jsonl"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
NOMINATIONS="$CLAUDE_PROJECT_DIR/.claude/knowledge-nominations.md"
GATE_FILE="$LOG_DIR/.quality-gate-active"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
SESSION_DATE=$(date +"%Y-%m-%d-%H")
BLOCK_FILE="$LOG_DIR/.session-blocks-$SESSION_DATE"
CLEAN_STREAK_FILE="$LOG_DIR/.clean-streak-$SESSION_DATE"

mkdir -p "$LOG_DIR"

# ═══════════════════════════════════════════════════════
# Read stdin and extract the last user+assistant exchange
# ═══════════════════════════════════════════════════════
# Claude Code passes a JSON object on stdin with a transcript_path
# field pointing to the session transcript (JSONL). We read the last
# few entries to keep the Haiku call cheap and focused on the most
# recent turn — not the whole session (which grows linearly and
# distracts the judge).
STDIN_JSON=$(cat)
TRANSCRIPT_PATH=$(echo "$STDIN_JSON" | jq -r '.transcript_path // empty' 2>/dev/null)

# Build a compact "last exchange" string from the transcript
LAST_EXCHANGE=""
if [ -n "$TRANSCRIPT_PATH" ] && [ -f "$TRANSCRIPT_PATH" ]; then
  # Take last 6 lines (roughly 2-3 turns of user/assistant). Each line
  # is a JSON entry with a .type (user|assistant|...) and .message field.
  LAST_EXCHANGE=$(tail -n 6 "$TRANSCRIPT_PATH" 2>/dev/null | jq -r '
    select(.type == "user" or .type == "assistant") |
    if .type == "user" then
      "USER: " + (.message.content // "" | tostring)
    else
      "ASSISTANT: " + (.message.content // "" | tostring)
    end' 2>/dev/null | head -c 4000)
fi

# If we could not reconstruct an exchange, bail gracefully — log a
# neutral "unknown" verdict and exit. No Haiku call, no output.
if [ -z "$LAST_EXCHANGE" ]; then
  jq -n \
    --arg ts "$TIMESTAMP" \
    --arg decision "unknown" \
    --arg reason "transcript unavailable" \
    '{timestamp: $ts, decision: $decision, learning: null, task_type: "other", reason: $reason}' \
    >> "$VERDICT_LOG"
  exit 0
fi

# ═══════════════════════════════════════════════════════
# Call Haiku directly via claude -p. Use --output-format json
# and a tight system-level instruction. Redirect stderr to null
# so hook noise never leaks to stdout.
# ═══════════════════════════════════════════════════════
JUDGE_PROMPT=$(cat <<'EOF'
You are a JSON-only response bot. Review the recent exchange below and return exactly one JSON object with these fields:
- decision: "allow" if the assistant's last turn addressed what the user asked, "block" if something was clearly missed, "unknown" if you cannot tell.
- reason: a brief string if decision is "block" or "unknown", otherwise null.
- learning: a one-sentence root-cause-plus-fix lesson if an error was resolved in this exchange, otherwise null.
- task_type: one of build, debug, refactor, test, docs, research, deploy, admin, setup, other.

Do NOT output anything except the raw JSON object. No markdown, no code fences, no prose.

RECENT EXCHANGE:
EOF
)

# Use --model haiku for speed. Timeout hard at 10s to avoid hanging sessions.
RAW_VERDICT=$(timeout 10 claude -p --model claude-haiku-4-5 --output-format text "$JUDGE_PROMPT

$LAST_EXCHANGE" 2>/dev/null || echo "")

# Strip any stray markdown fences
VERDICT=$(echo "$RAW_VERDICT" | sed -n '/^{/,/^}/p' | head -c 2000)
if [ -z "$VERDICT" ]; then
  VERDICT="$RAW_VERDICT"
fi

# Parse as JSON
DECISION=$(echo "$VERDICT" | jq -r '.decision // empty' 2>/dev/null)
LEARNING=$(echo "$VERDICT" | jq -r '.learning // empty' 2>/dev/null)
TASK_TYPE=$(echo "$VERDICT" | jq -r '.task_type // "other"' 2>/dev/null)
REASON=$(echo "$VERDICT" | jq -r '.reason // empty' 2>/dev/null)

if [ -z "$DECISION" ]; then
  DECISION="unknown"
  TASK_TYPE="other"
fi

# ═══════════════════════════════════════════════════════
# Log the verdict (JSONL)
# ═══════════════════════════════════════════════════════
jq -n \
  --arg ts "$TIMESTAMP" \
  --arg decision "$DECISION" \
  --arg learning "$LEARNING" \
  --arg task_type "$TASK_TYPE" \
  --arg reason "$REASON" \
  '{timestamp: $ts, decision: $decision, learning: $learning, task_type: $task_type, reason: $reason}' \
  >> "$VERDICT_LOG"

# ═══════════════════════════════════════════════════════
# Track blocks and clean streak for quality gate
# ═══════════════════════════════════════════════════════
if [ "$DECISION" = "block" ]; then
  BLOCK_COUNT=1
  if [ -f "$BLOCK_FILE" ]; then
    BLOCK_COUNT=$(( $(cat "$BLOCK_FILE") + 1 ))
  fi
  echo "$BLOCK_COUNT" > "$BLOCK_FILE"

  rm -f "$CLEAN_STREAK_FILE"

  echo "- \`$TIMESTAMP\` | VERDICT | BLOCK | $REASON" >> "$INCIDENT_LOG"

  if [ "$BLOCK_COUNT" -ge 2 ]; then
    touch "$GATE_FILE"
    echo "- \`$TIMESTAMP\` | VERDICT | WARN | Quality gate activated — $BLOCK_COUNT blocks this session" >> "$INCIDENT_LOG"
  fi
elif [ "$DECISION" = "allow" ]; then
  CLEAN_STREAK=1
  if [ -f "$CLEAN_STREAK_FILE" ]; then
    CLEAN_STREAK=$(( $(cat "$CLEAN_STREAK_FILE") + 1 ))
  fi
  echo "$CLEAN_STREAK" > "$CLEAN_STREAK_FILE"

  if [ -f "$GATE_FILE" ] && [ "$CLEAN_STREAK" -ge 3 ]; then
    rm -f "$GATE_FILE" "$BLOCK_FILE" "$CLEAN_STREAK_FILE"
    echo "- \`$TIMESTAMP\` | VERDICT | INFO | Quality gate auto-cleared after 3 clean turns" >> "$INCIDENT_LOG"
  fi
fi

# ═══════════════════════════════════════════════════════
# Nominate learning if present
# ═══════════════════════════════════════════════════════
if [ -n "$LEARNING" ] && [ "$LEARNING" != "null" ]; then
  NOMINATION_DATE=$(date +"%Y-%m-%d")
  echo "- [$NOMINATION_DATE] stop-hook: $LEARNING | Evidence: session verdict ($TASK_TYPE)" >> "$NOMINATIONS"
fi

# CRITICAL: exit silently. No stdout. Anything printed here gets
# surfaced to the main model and reopens the re-injection loop.
exit 0
