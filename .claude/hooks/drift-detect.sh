#!/bin/bash
# PostToolUse async hook — incremental drift detection on critical config files.
#
# Trigger: Write|Edit|NotebookEdit on any of:
#   - CLAUDE.md
#   - .claude/knowledge-base.md
#   - .claude/settings.json
#   - .claude/command-index.md
#
# Action: run lightweight, deterministic checks (no LLM, no agents) and
# log any drift/issues to incident-log.md and a dedicated drift-log.md.
# Never blocks. Async. Replaces the manual /drift-detect command for
# the incremental case (full sweeps remain a deliberate command).

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | jq -r '.tool_input.file_path // empty')
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
DRIFT_LOG="$LOG_DIR/drift-log.md"

# Fast exit: no file path
[ -z "$FILE_PATH" ] && exit 0

# Resolve to relative for matching
RELATIVE_PATH="${FILE_PATH#$CLAUDE_PROJECT_DIR/}"
RELATIVE_PATH="${RELATIVE_PATH#./}"

# Fast exit: not a tracked config file
case "$RELATIVE_PATH" in
  CLAUDE.md|.claude/knowledge-base.md|.claude/universal-rules.md|.claude/settings.json|.claude/command-index.md)
    ;;
  *)
    exit 0
    ;;
esac

mkdir -p "$LOG_DIR"

log_drift() {
  local SEVERITY="$1"
  local MSG="$2"
  echo "- \`$TIMESTAMP\` | DRIFT | $SEVERITY | $RELATIVE_PATH | $MSG" >> "$INCIDENT_LOG"
  echo "- \`$TIMESTAMP\` | $SEVERITY | $RELATIVE_PATH | $MSG" >> "$DRIFT_LOG"
}

# ═══════════════════════════════════════════════════════
# Check 1: settings.json must remain valid JSON
# ═══════════════════════════════════════════════════════
if [ "$RELATIVE_PATH" = ".claude/settings.json" ] && [ -f "$FILE_PATH" ]; then
  if ! jq empty "$FILE_PATH" 2>/dev/null; then
    log_drift "CRITICAL" "settings.json is no longer valid JSON — hooks will break on next session"
  fi
fi

# ═══════════════════════════════════════════════════════
# Check 2: knowledge-base.md / universal-rules.md — size limit (200) + provenance
# ═══════════════════════════════════════════════════════
case "$RELATIVE_PATH" in
  .claude/knowledge-base.md|.claude/universal-rules.md)
    if [ -f "$FILE_PATH" ]; then
      KB_LINES=$(wc -l < "$FILE_PATH" | tr -d ' ')
      if [ "$KB_LINES" -gt 200 ]; then
        log_drift "HIGH" "$RELATIVE_PATH exceeds 200 line limit ($KB_LINES lines) — prune stale entries"
      fi
      # Check entries without provenance
      MISSING_SOURCE=$(grep -c '^- ' "$FILE_PATH" 2>/dev/null || echo 0)
      WITH_SOURCE=$(grep -c '\[Source:' "$FILE_PATH" 2>/dev/null || echo 0)
      if [ "$MISSING_SOURCE" -gt "$WITH_SOURCE" ]; then
        DIFF=$((MISSING_SOURCE - WITH_SOURCE))
        log_drift "MEDIUM" "$RELATIVE_PATH has $DIFF entries without [Source:] provenance"
      fi
    fi
    ;;
esac

# ═══════════════════════════════════════════════════════
# Check 3: CLAUDE.md size sanity (warning at 500 lines)
# ═══════════════════════════════════════════════════════
if [ "$RELATIVE_PATH" = "CLAUDE.md" ] && [ -f "$FILE_PATH" ]; then
  CL_LINES=$(wc -l < "$FILE_PATH" | tr -d ' ')
  if [ "$CL_LINES" -gt 500 ]; then
    log_drift "MEDIUM" "CLAUDE.md exceeds 500 line warning threshold ($CL_LINES lines) — consider splitting"
  fi
fi

# ═══════════════════════════════════════════════════════
# Check 4: command-index.md vs actual commands directory
# Detects orphans (file referenced but missing) and unindexed commands.
# ═══════════════════════════════════════════════════════
if [ "$RELATIVE_PATH" = ".claude/command-index.md" ] && [ -f "$FILE_PATH" ]; then
  COMMANDS_DIR="$CLAUDE_PROJECT_DIR/.claude/commands"
  if [ -d "$COMMANDS_DIR" ]; then
    # Find commands referenced in index but missing on disk
    MISSING=""
    while IFS= read -r CMD; do
      [ -z "$CMD" ] && continue
      if [ ! -f "$COMMANDS_DIR/$CMD.md" ] && [ ! -f "$COMMANDS_DIR/$CMD" ]; then
        MISSING="$MISSING $CMD"
      fi
    done < <(grep -oE '/[a-z][a-z0-9-]*' "$FILE_PATH" 2>/dev/null | sed 's|^/||' | sort -u)
    if [ -n "$MISSING" ]; then
      log_drift "HIGH" "command-index references missing commands:$MISSING"
    fi
  fi
fi

# ═══════════════════════════════════════════════════════
# Check 5: Cross-file orphan reference (CLAUDE.md → file paths)
# Detects file paths mentioned in CLAUDE.md that no longer exist.
# Conservative: only checks paths starting with .claude/ or Daily Notes/
# ═══════════════════════════════════════════════════════
if [ "$RELATIVE_PATH" = "CLAUDE.md" ] && [ -f "$FILE_PATH" ]; then
  ORPHANS=""
  while IFS= read -r REF; do
    [ -z "$REF" ] && continue
    # Strip backticks and trailing punctuation
    CLEAN=$(echo "$REF" | sed 's/`//g' | sed 's/[).,;:]*$//')
    [ -z "$CLEAN" ] && continue
    # Only check things that look like file paths inside the project
    case "$CLEAN" in
      .claude/*|"Daily Notes/"*)
        # Allow glob-like patterns ending with / or *
        case "$CLEAN" in
          */|*\*) continue ;;
        esac
        if [ ! -e "$CLAUDE_PROJECT_DIR/$CLEAN" ]; then
          ORPHANS="$ORPHANS $CLEAN"
        fi
        ;;
    esac
  done < <(grep -oE '`\.claude/[^`]+`|`Daily Notes/[^`]+`' "$FILE_PATH" 2>/dev/null)
  if [ -n "$ORPHANS" ]; then
    log_drift "MEDIUM" "CLAUDE.md references missing paths:$ORPHANS"
  fi
fi

exit 0
