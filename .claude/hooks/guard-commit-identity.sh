#!/bin/bash
# PreToolUse(Bash) hook — enforces project-specific commit identity.
#
# Purpose: block `git commit` if the message contains a Co-Authored-By
# trailer that doesn't match the identity declared in knowledge-base.md.
# This prevents agents from using the global ~/.claude/CLAUDE.md default
# Co-Authored-By trailer when the project knowledge-base declares a
# different identity.
#
# Behavior:
# - fail-open if no Commit Identity entry is found in knowledge-base.md
#   (this is the base-repo case, where no project identity exists)
# - fail-open if the command is not a `git commit`
# - HARD BLOCK if the identity is configured and the commit message
#   contains a Co-Authored-By trailer with a different email
#
# This hook runs AFTER guard-bash.sh in the PreToolUse(Bash) chain.

# Limit stdin to 64KB to prevent OOM on pathological input
INPUT=$(head -c 65536)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
KB="$CLAUDE_PROJECT_DIR/.claude/knowledge-base.md"
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"

mkdir -p "$LOG_DIR"

# Fail-open: not a git commit, nothing to check
if ! echo "$COMMAND" | grep -qE '\bgit\s+commit\b'; then
  exit 0
fi

# Fail-open: knowledge-base doesn't exist (base repo, fresh clone, etc.)
if [ ! -f "$KB" ]; then
  exit 0
fi

# Extract the configured commit identity from knowledge-base.md.
# Format expected: `**Commit Identity**: ... Co-Authored-By: Name <email>`
# We look for the first email address appearing in a line that starts
# the Commit Identity entry.
IDENTITY_LINE=$(grep -i '\*\*Commit Identity\*\*' "$KB" | head -1)

# Fail-open: no Commit Identity entry configured
if [ -z "$IDENTITY_LINE" ]; then
  exit 0
fi

# Extract the email (first <...> token containing an @)
REQUIRED_EMAIL=$(echo "$IDENTITY_LINE" | grep -oE '<[^>]*@[^>]*>' | head -1 | tr -d '<>')

# Fail-open: couldn't parse an email out of the entry (malformed entry)
if [ -z "$REQUIRED_EMAIL" ]; then
  exit 0
fi

# Now check the commit message for Co-Authored-By trailers.
# The message can arrive in two forms:
#   1. -m "text" or -m 'text'
#   2. HEREDOC: -m "$(cat <<'EOF' ... EOF)"
# We extract every Co-Authored-By line from the ENTIRE command string
# (both forms leave the trailer visible in the raw command).
FOUND_TRAILERS=$(echo "$COMMAND" | grep -oE 'Co-Authored-By:[^"'"'"']*<[^>]+>' | sort -u)

# Fail-open: no Co-Authored-By trailer at all (plain commit, no attribution)
if [ -z "$FOUND_TRAILERS" ]; then
  exit 0
fi

# Check each found trailer. If any contains an email different from
# REQUIRED_EMAIL, block.
VIOLATION=""
while IFS= read -r trailer; do
  [ -z "$trailer" ] && continue
  TRAILER_EMAIL=$(echo "$trailer" | grep -oE '<[^>]+>' | tr -d '<>')
  if [ -n "$TRAILER_EMAIL" ] && [ "$TRAILER_EMAIL" != "$REQUIRED_EMAIL" ]; then
    VIOLATION="$trailer"
    break
  fi
done <<< "$FOUND_TRAILERS"

if [ -n "$VIOLATION" ]; then
  TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
  echo "- \`$TIMESTAMP\` | GUARD | CRITICAL | BLOCKED commit-identity mismatch: found '$VIOLATION', required email '$REQUIRED_EMAIL'" >> "$INCIDENT_LOG"

  jq -n \
    --arg reason "HARD BLOCK: commit identity mismatch. The project knowledge-base requires Co-Authored-By with email <$REQUIRED_EMAIL> but the commit message contains: $VIOLATION" \
    --arg context "Project rule source: .claude/knowledge-base.md → Commit Identity. This rule OVERRIDES any global default (~/.claude/CLAUDE.md). Remove the wrong trailer, use the required identity, and retry. If the required identity in the knowledge-base is itself wrong, update the knowledge-base first (not the commit)." \
    '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason,
        additionalContext: $context
      }
    }'
  exit 0
fi

exit 0
