#!/bin/bash
# Deterministic daily digest — replaces the LLM-driven verdict log that was
# removed in refactor/drop-verdicts-log. Called from /wrap-up Step 7b.
#
# Reads today's failure-log, incident-log, and git commits; emits a markdown
# block suitable for appending to the daily note. Zero LLM calls, zero cost.
#
# Usage: wrap-up-digest.sh  (prints markdown to stdout)

set -euo pipefail

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"
TODAY=$(date +%Y-%m-%d)
FAILURE_LOG="$PROJECT_DIR/.claude/logs/failure-log.md"
INCIDENT_LOG="$PROJECT_DIR/.claude/logs/incident-log.md"

# Commits today: count + list
COMMITS_TODAY=$(git -C "$PROJECT_DIR" log \
  --format="- %h %s" \
  --after="$TODAY 00:00:00" \
  --before="$TODAY 23:59:59" \
  2>/dev/null || echo "")
COMMITS_COUNT=$(echo "$COMMITS_TODAY" | grep -c '^-' 2>/dev/null || echo 0)
# Force numeric (grep -c may emit trailing whitespace on some platforms)
COMMITS_COUNT=$((COMMITS_COUNT + 0))

# Failures today: count + top category. Log lines look like
# `- \`YYYY-MM-DD HH:MM:SS\` | FAIL | <TOOL> | <category> | <detail>`
# Single-pass awk builds the category histogram and picks the max.
FAILURES_TODAY=0
TOP_CATEGORY="none"
if [ -f "$FAILURE_LOG" ]; then
  FAILURE_STATS=$(awk -v today="$TODAY" -F'|' '
    $0 ~ "`" today " " {
      gsub(/^ +| +$/, "", $4)
      counts[$4]++
      total++
    }
    END {
      max = 0; top = "none"
      for (c in counts) if (counts[c] > max) { max = counts[c]; top = c }
      printf "%d|%s", total+0, top
    }
  ' "$FAILURE_LOG")
  FAILURES_TODAY="${FAILURE_STATS%%|*}"
  TOP_CATEGORY="${FAILURE_STATS#*|}"
  [ -z "$TOP_CATEGORY" ] && TOP_CATEGORY="none"
fi

# Incidents today: count by severity. Log lines look like
# `- \`YYYY-MM-DD HH:MM:SS\` | <SOURCE> | <SEVERITY> | <msg>`
INC_CRITICAL=0; INC_HIGH=0; INC_MEDIUM=0; INC_LOW=0
if [ -f "$INCIDENT_LOG" ]; then
  INC_STATS=$(awk -v today="$TODAY" -F'|' '
    $0 ~ "`" today " " {
      gsub(/^ +| +$/, "", $3)
      sev[$3]++
    }
    END {
      printf "%d|%d|%d|%d", sev["CRITICAL"]+0, sev["HIGH"]+0, sev["MEDIUM"]+0, sev["LOW"]+0
    }
  ' "$INCIDENT_LOG")
  IFS='|' read -r INC_CRITICAL INC_HIGH INC_MEDIUM INC_LOW <<< "$INC_STATS"
fi

cat <<EOF
### Daily digest ($TODAY)

- **Commits:** $COMMITS_COUNT
- **Tool failures:** $FAILURES_TODAY (top category: \`$TOP_CATEGORY\`)
- **Incidents:** CRITICAL=$INC_CRITICAL, HIGH=$INC_HIGH, MEDIUM=$INC_MEDIUM, LOW=$INC_LOW

<details>
<summary>Commits today</summary>

$COMMITS_TODAY
</details>
EOF
