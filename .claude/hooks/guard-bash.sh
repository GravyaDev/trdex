#!/bin/bash
# PreToolUse hook for Bash commands.
# Uses structured JSON output for blocks (exit 0 + JSON stdout).
# Falls through with plain exit 0 for allowed commands.
#
# Three tiers:
#   HARD BLOCK  — always blocked, no override (permissionDecision: deny)
#   SOFT BLOCK  — blocked with explanation, user can re-request (permissionDecision: deny)
#   LOG WARNING — allowed but logged to incident log (exit 0, no JSON)

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"

mkdir -p "$LOG_DIR"

log_incident() {
  local SEVERITY="$1"
  local MSG="$2"
  echo "- \`$TIMESTAMP\` | GUARD | $SEVERITY | $MSG" >> "$INCIDENT_LOG"
}

deny() {
  local REASON="$1"
  local CONTEXT="$2"
  jq -n \
    --arg reason "$REASON" \
    --arg context "$CONTEXT" \
    '{
      hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "deny",
        permissionDecisionReason: $reason,
        additionalContext: $context
      }
    }'
  exit 0
}

# ═══════════════════════════════════════════════════════
# HARD BLOCK — never allowed, no exceptions
# ═══════════════════════════════════════════════════════

# rm -rf / or rm -rf ~ (catastrophic)
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+)?(/|~|\$HOME)\s*$'; then
  log_incident "CRITICAL" "BLOCKED: catastrophic rm → $COMMAND"
  deny "HARD BLOCK: This would delete your entire filesystem or home directory." "Command blocked: catastrophic rm detected. This command is never allowed under any circumstances."
fi

# git push --force (any branch)
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f'; then
  log_incident "CRITICAL" "BLOCKED: force push → $COMMAND"
  deny "HARD BLOCK: Force push rewrites shared history." "Command blocked: force push detected. Ask the user to confirm the specific branch if intentional."
fi

# git reset --hard (destroys uncommitted work)
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  log_incident "HIGH" "BLOCKED: git reset --hard → $COMMAND"
  deny "HARD BLOCK: git reset --hard destroys uncommitted changes." "Command blocked: git reset --hard. Suggest using git stash or git commit first."
fi

# git clean -f (deletes untracked files permanently)
if echo "$COMMAND" | grep -qE 'git\s+clean\s+(-[a-zA-Z]*f|-f)'; then
  log_incident "HIGH" "BLOCKED: git clean -f → $COMMAND"
  deny "HARD BLOCK: git clean -f permanently deletes untracked files." "Command blocked: git clean -f. Suggest using git stash instead."
fi

# chmod 777 (security risk)
if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
  log_incident "HIGH" "BLOCKED: chmod 777 → $COMMAND"
  deny "HARD BLOCK: chmod 777 grants full access to all users." "Command blocked: chmod 777. Use more restrictive permissions like 755 or 644."
fi

# Writing to files outside project directory.
# Covers redirects (`> /path`, `>> /path`), tee (`tee /path`, `tee -a /path`),
# and dd (`dd of=/path`). Excludes writes inside $CLAUDE_PROJECT_DIR and
# common safe temp sinks (/dev/null, /dev/stdout, /dev/stderr).
check_outside_write() {
  local target="$1"
  # Allow /dev/null and friends
  case "$target" in
    /dev/null|/dev/stdout|/dev/stderr|/dev/tty) return 1 ;;
  esac
  # Allow anything inside the project dir
  case "$target" in
    "$CLAUDE_PROJECT_DIR"/*|"$CLAUDE_PROJECT_DIR") return 1 ;;
  esac
  # Absolute path outside project → block
  case "$target" in
    /*) return 0 ;;
  esac
  return 1
}

# Redirect: > /path or >> /path
REDIR_TARGET=$(echo "$COMMAND" | grep -oE '>>?\s*/[^ ;|&]+' | head -1 | sed -E 's/^>>?\s*//')
if [ -n "$REDIR_TARGET" ] && check_outside_write "$REDIR_TARGET"; then
  log_incident "HIGH" "BLOCKED: redirect outside project dir → $COMMAND"
  deny "HARD BLOCK: writing outside project dir is strictly forbidden." "Redirect target: $REDIR_TARGET"
fi

# tee: tee /path or tee -a /path
TEE_TARGET=$(echo "$COMMAND" | grep -oE '\btee\s+(-[aA]\s+)?/[^ ;|&]+' | head -1 | sed -E 's/^tee\s+(-[aA]\s+)?//')
if [ -n "$TEE_TARGET" ] && check_outside_write "$TEE_TARGET"; then
  log_incident "HIGH" "BLOCKED: tee outside project dir → $COMMAND"
  deny "HARD BLOCK: writing outside project dir is strictly forbidden." "tee target: $TEE_TARGET"
fi

# dd: dd of=/path
DD_TARGET=$(echo "$COMMAND" | grep -oE '\bdd\s+.*\bof=/[^ ;|&]+' | head -1 | sed -E 's/.*\bof=//')
if [ -n "$DD_TARGET" ] && check_outside_write "$DD_TARGET"; then
  log_incident "HIGH" "BLOCKED: dd outside project dir → $COMMAND"
  deny "HARD BLOCK: writing outside project dir is strictly forbidden." "dd target: $DD_TARGET"
fi

# ═══════════════════════════════════════════════════════
# SECRET EXPOSURE — block commands that leak credentials
# ═══════════════════════════════════════════════════════

# Block cat/head/tail/less of .env files (prevents full credential dump)
if echo "$COMMAND" | grep -qE '(cat|head|tail|less|more|bat)\s+.*(\.(env|env\.local|env\.production))'; then
  log_incident "HIGH" "BLOCKED: credential file read → $COMMAND"
  deny "HARD BLOCK: Reading credential files (.env) via shell exposes secrets in output." "Use environment variable names (e.g., \$DATABASE_URL) instead of reading the file. If you need to verify a value exists, use: grep -c 'KEY_NAME' file"
fi

# Block echo/printf of environment variables containing common secret prefixes
if echo "$COMMAND" | grep -qE '(echo|printf)\s+.*\$(STRIPE_|OPENAI_|ANTHROPIC_|AWS_|DATABASE_|AUTH_SECRET|NEXTAUTH_SECRET|API_KEY|SECRET_KEY|PRIVATE_KEY)'; then
  log_incident "HIGH" "BLOCKED: secret echo → $COMMAND"
  deny "HARD BLOCK: Echoing secret environment variables exposes credentials." "Reference secrets by variable name only. Never echo their values."
fi

# Block piping credential files to network commands (curl, wget, nc, etc.)
if echo "$COMMAND" | grep -qE '\.env.*\|\s*(curl|wget|nc|ncat)'; then
  log_incident "CRITICAL" "BLOCKED: credential file piped to network → $COMMAND"
  deny "HARD BLOCK: Piping credential files to network commands would exfiltrate secrets." "Never pipe .env files to network commands."
fi

# Block git add of credential files.
# The pattern is anchored on either whitespace or end-of-command after
# the credential extension, so legitimate templates like .env.example /
# .env.sample / .env.template are never matched (they have characters
# beyond the recognised credential extensions and therefore fall
# through). Mixed arguments like "git add .env.example .env" still get
# blocked because the second token matches the trailing-anchor branch.
if echo "$COMMAND" | grep -qE 'git\s+add\s+.*\.env(\.local|\.production|\.dev|\.prod|\.staging)?(\s|$)'; then
  log_incident "CRITICAL" "BLOCKED: git add of credential file → $COMMAND"
  deny "HARD BLOCK: Staging credential files (.env) for git commit would expose secrets publicly." "These files must stay in .gitignore. Never commit credentials to git. Templates like .env.example are explicitly allowed."
fi

# ═══════════════════════════════════════════════════════
# SOFT BLOCK — blocked, but user can re-request
# ═══════════════════════════════════════════════════════

# rm with -r or -f flags (recursive/force delete)
if echo "$COMMAND" | grep -qE 'rm\s+(-[a-zA-Z]*[rf][a-zA-Z]*\s+)'; then
  # Allow rm on .claude/backups (rotation), .claude/logs temp files,
  # and the __NEEDS_ONBOARD sentinel (deleted at end of /onboard-init).
  if echo "$COMMAND" | grep -qE '\.claude/(backups|logs/\.(quality-gate-active|session-blocks|tool-call-count|compaction-occurred))|__NEEDS_ONBOARD'; then
    exit 0
  fi
  log_incident "MEDIUM" "SOFT BLOCKED: recursive/force rm → $COMMAND"
  deny "SOFT BLOCK: rm with -r or -f flags deletes files permanently." "Command blocked: recursive/force delete. If intentional, ask the user to confirm with specific file paths listed."
fi

# Overwriting system/config files
if echo "$COMMAND" | grep -qE '>\s*(~\/\.|\/etc\/|\.env|\.ssh|\.claude\/settings)'; then
  log_incident "HIGH" "SOFT BLOCKED: config/system file overwrite → $COMMAND"
  deny "SOFT BLOCK: Writing to a sensitive config/system file." "Command blocked: system file overwrite detected. Verify this is intentional with the user."
fi

# curl piped to shell (arbitrary code execution)
if echo "$COMMAND" | grep -qE 'curl\s.*\|\s*(bash|sh|zsh)'; then
  log_incident "HIGH" "SOFT BLOCKED: curl pipe to shell → $COMMAND"
  deny "SOFT BLOCK: Piping curl to a shell executes arbitrary remote code." "Command blocked: curl pipe to shell. Download the file first, inspect it, then run it."
fi

# curl/wget to external URLs (enforces CLAUDE.md hard rule: no direct third-party API calls).
# Excludes localhost, 127.0.0.1, 0.0.0.0, and context7 MCP (which is allowed).
if echo "$COMMAND" | grep -qE '\b(curl|wget)\s+.*https?://' && \
   ! echo "$COMMAND" | grep -qE 'https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])'; then
  log_incident "MEDIUM" "SOFT BLOCKED: curl/wget to external URL → $COMMAND"
  deny "SOFT BLOCK: Direct calls to third-party APIs via curl/wget are forbidden by CLAUDE.md hard rule." "Use a proper Python/Node tool with rate-limiting, retries, and auth handling. If this is a one-shot doc fetch, use the WebFetch tool instead."
fi

# ═══════════════════════════════════════════════════════
# LOG WARNING — allowed but recorded
# ═══════════════════════════════════════════════════════

# Any rm command (non-recursive, non-force)
if echo "$COMMAND" | grep -qE '\brm\b'; then
  log_incident "LOW" "WARNING: rm command allowed → $COMMAND"
fi

# Any mv command (could lose data if target exists)
if echo "$COMMAND" | grep -qE '\bmv\b'; then
  log_incident "LOW" "WARNING: mv command allowed → $COMMAND"
fi

# Any git checkout that discards changes
if echo "$COMMAND" | grep -qE 'git\s+checkout\s+\.'; then
  log_incident "MEDIUM" "WARNING: git checkout . discards changes → $COMMAND"
fi

# git commit with -F / --file / --template (message sourced from file, bypasses HEREDOC review)
if echo "$COMMAND" | grep -qE 'git\s+commit\s+.*(-F\b|--file\b|--template\b)'; then
  log_incident "MEDIUM" "WARNING: git commit from file → $COMMAND"
fi

exit 0
