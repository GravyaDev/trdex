#!/bin/bash
# PreToolUse(WebFetch) hook — enforces Jina Reader as the primary fetch path.
#
# Purpose: every WebFetch call must go through https://r.jina.ai/<url>
# instead of hitting the target URL directly. Jina Reader strips ads,
# converts HTML/PDF to clean markdown, handles SPAs, and is significantly
# cheaper in tokens than raw WebFetch on most pages. The .claude/skills/
# web-fetch/SKILL.md skill documents this contract, but a skill is only a
# semantic-triggered suggestion — agents that call WebFetch directly bypass
# it. This hook is the artefact-triggered enforcer.
#
# Behavior: HARD BLOCK any WebFetch whose URL is not already wrapped by
# r.jina.ai/. The denial message tells the agent how to fix it (just
# prepend r.jina.ai/ to the URL). Two exception channels exist for the
# rare cases where Jina genuinely cannot serve:
#   1. r.jina.ai-wrapped URLs are allowed unconditionally
#   2. Localhost / loopback URLs are allowed (Jina is a public proxy and
#      cannot reach private addresses anyway)
#
# Beyond those two, the only way to use raw WebFetch is for the user to
# explicitly authorize it in chat — at which point the agent should ask
# the user to grant a one-shot exception, and the user re-prompts with
# the bypass intent. This hook does not implement a token-based bypass
# channel: the user's natural-language authorization is the bypass.

INPUT=$(cat)
URL=$(echo "$INPUT" | jq -r '.tool_input.url // empty')
LOG_DIR="$CLAUDE_PROJECT_DIR/.claude/logs"
INCIDENT_LOG="$LOG_DIR/incident-log.md"
TIMESTAMP=$(date +"%Y-%m-%d %H:%M:%S")

mkdir -p "$LOG_DIR"

# Fail-open: no URL field, nothing to enforce
if [ -z "$URL" ]; then
  exit 0
fi

# ALLOWED: already going through Jina Reader
if echo "$URL" | grep -qE '^https?://r\.jina\.ai/'; then
  exit 0
fi

# ALLOWED: localhost / loopback (Jina cannot proxy private addresses)
if echo "$URL" | grep -qE '^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])(:|/|$)'; then
  exit 0
fi

# Everything else: HARD BLOCK with a fixable suggestion
SUGGESTED="https://r.jina.ai/$URL"

echo "- \`$TIMESTAMP\` | GUARD | MEDIUM | BLOCKED raw WebFetch (no Jina): $URL" >> "$INCIDENT_LOG"

jq -n \
  --arg reason "HARD BLOCK: WebFetch must go through Jina Reader. Direct WebFetch calls bypass the markdown conversion, ad stripping, and token savings provided by Jina. This is enforced by .claude/hooks/guard-webfetch-jina.sh and matches the contract in .claude/skills/web-fetch/SKILL.md." \
  --arg context "Retry with the URL wrapped in the Jina Reader proxy: $SUGGESTED — keep the same prompt, only change the URL field. If Jina genuinely cannot serve this page (login-required, private IP, binary download), STOP and ask the user for explicit authorization to use raw WebFetch for this specific URL. Do NOT retry the raw WebFetch on your own initiative — the user must grant the exception in chat first." \
  '{
    hookSpecificOutput: {
      hookEventName: "PreToolUse",
      permissionDecision: "deny",
      permissionDecisionReason: $reason,
      additionalContext: $context
    }
  }'
exit 0
