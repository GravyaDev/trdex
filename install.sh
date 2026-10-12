#!/usr/bin/env bash
# Kloudify installer — installs or upgrades Kloudify in a target project.
#
# Usage:
#   First install:  ./install.sh /path/to/my-project
#   Upgrade:        ./install.sh /path/to/my-project --upgrade
#   From remote:    ./install.sh /path/to/my-project --upgrade --from-remote
#
# What it does:
#   1. Resolves the Kloudify source (this repo, or a fresh clone of the
#      latest tagged release when --from-remote is specified)
#   2. Copies infrastructure files to the target project
#   3. Writes .claude/kloudify-version.json with the installed version
#   4. Creates __NEEDS_ONBOARD sentinel for first installs
#   5. On upgrade: preserves project-specific files (knowledge-base,
#      memory, daily notes, reports, agent-memory, logs)
#
# What it does NOT do:
#   - It does not touch your source code
#   - It does not modify .git/ or git config
#   - It does not run /onboard-init (that happens on next /start)
#   - It does not auto-migrate knowledge-base (that is /upgrade's job)

set -euo pipefail

# ═══════════════════════════════════════════════════════
# Arguments
# ═══════════════════════════════════════════════════════
TARGET=""
MODE="install"
FROM_REMOTE=0
REMOTE_REPO_URL="https://github.com/GravyaDev/Kloudify.git"

for arg in "$@"; do
  case "$arg" in
    --upgrade) MODE="upgrade" ;;
    --from-remote) FROM_REMOTE=1 ;;
    --help|-h)
      echo "Usage: ./install.sh <target-project-dir> [--upgrade] [--from-remote]"
      echo ""
      echo "Examples:"
      echo "  ./install.sh /path/to/my-project                           # First install from this clone"
      echo "  ./install.sh /path/to/my-project --upgrade                 # Upgrade from this clone"
      echo "  ./install.sh /path/to/my-project --upgrade --from-remote   # Upgrade from latest GitHub tag"
      exit 0
      ;;
    *)
      if [ -z "$TARGET" ]; then
        TARGET="$arg"
      fi
      ;;
  esac
done

if [ -z "$TARGET" ]; then
  echo "Usage: ./install.sh <target-project-dir> [--upgrade] [--from-remote]"
  echo ""
  echo "Examples:"
  echo "  ./install.sh /path/to/my-project                           # First install"
  echo "  ./install.sh /path/to/my-project --upgrade                 # Upgrade from this clone"
  echo "  ./install.sh /path/to/my-project --upgrade --from-remote   # Upgrade from latest GitHub tag"
  exit 1
fi

if [ ! -d "$TARGET" ]; then
  echo "Error: target directory '$TARGET' does not exist."
  exit 1
fi

# ═══════════════════════════════════════════════════════
# Source resolution — local clone OR fresh clone from remote
# ═══════════════════════════════════════════════════════
TEMP_CLONE=""
cleanup() {
  if [ -n "$TEMP_CLONE" ] && [ -d "$TEMP_CLONE" ]; then
    rm -rf "$TEMP_CLONE"
  fi
}
trap cleanup EXIT

if [ "$FROM_REMOTE" = "1" ]; then
  if ! command -v git &>/dev/null; then
    echo "Error: --from-remote requires git to be installed."
    exit 1
  fi
  echo "Fetching latest Kloudify release from $REMOTE_REPO_URL..."
  TEMP_CLONE=$(mktemp -d)
  # Shallow clone with tags, then checkout the latest tag
  git clone --quiet --depth 50 "$REMOTE_REPO_URL" "$TEMP_CLONE"
  LATEST_TAG=$(git -C "$TEMP_CLONE" describe --tags --abbrev=0 2>/dev/null || echo "")
  if [ -z "$LATEST_TAG" ]; then
    echo "Warning: no tags found in remote repo. Using main branch HEAD."
  else
    echo "  Latest tag: $LATEST_TAG"
    git -C "$TEMP_CLONE" -c advice.detachedHead=false checkout --quiet "$LATEST_TAG"
  fi
  SOURCE="$TEMP_CLONE"
else
  # Resolve source — the directory where this script lives
  SOURCE="$(cd "$(dirname "$0")" && pwd)"
  # Best-effort: refresh tags from origin so version detection is accurate.
  # Silent and non-fatal — we don't want a network hiccup to abort install.
  if command -v git &>/dev/null && [ -d "$SOURCE/.git" ]; then
    git -C "$SOURCE" fetch --tags --quiet origin 2>/dev/null || true
  fi
fi

# ═══════════════════════════════════════════════════════
# Version detection
# ═══════════════════════════════════════════════════════
# Use git describe WITHOUT --exact-match so HEAD commits past the last
# tag still produce a meaningful version string (e.g. v1.2.1-3-g43fc921
# means "3 commits past v1.2.1"). Fall back to --abbrev=0 (just the
# nearest tag), then to a commit-hash dev marker.
if command -v git &>/dev/null && [ -d "$SOURCE/.git" ]; then
  VERSION=$(git -C "$SOURCE" describe --tags 2>/dev/null || echo "")
  if [ -z "$VERSION" ]; then
    VERSION=$(git -C "$SOURCE" describe --tags --abbrev=0 2>/dev/null || echo "")
  fi
  if [ -z "$VERSION" ]; then
    VERSION="dev-$(git -C "$SOURCE" rev-parse --short HEAD 2>/dev/null || echo 'unknown')"
  fi
  COMMIT=$(git -C "$SOURCE" rev-parse --short HEAD 2>/dev/null || echo "unknown")
  # Try to get the remote URL for future update checks
  REMOTE_URL=$(git -C "$SOURCE" remote get-url origin 2>/dev/null || echo "")
  # Override remote URL with the canonical one when installing from --from-remote
  if [ "$FROM_REMOTE" = "1" ]; then
    REMOTE_URL="$REMOTE_REPO_URL"
  fi
else
  VERSION="unknown"
  COMMIT="unknown"
  REMOTE_URL=""
fi

echo "Kloudify $MODE"
echo "  Source:  $SOURCE"
echo "  Target:  $TARGET"
echo "  Version: $VERSION ($COMMIT)"
echo ""

# ═══════════════════════════════════════════════════════
# Pre-flight checks
# ═══════════════════════════════════════════════════════
if [ "$MODE" = "install" ] && [ -f "$TARGET/.claude/kloudify-version.json" ]; then
  echo "Warning: Kloudify is already installed in this project."
  echo "  Installed version: $(cat "$TARGET/.claude/kloudify-version.json" | grep -o '"version": *"[^"]*"' | head -1)"
  echo ""
  echo "Use --upgrade to update: ./install.sh $TARGET --upgrade"
  exit 1
fi

if [ "$MODE" = "upgrade" ] && [ ! -f "$TARGET/.claude/kloudify-version.json" ]; then
  echo "Warning: no kloudify-version.json found. Treating as first install."
  MODE="install"
fi

# ═══════════════════════════════════════════════════════
# Files to copy — explicit list, not glob
# ═══════════════════════════════════════════════════════
# These are the Kloudify infrastructure files. Session state,
# project-specific files, and user content are NEVER copied.

copy_file() {
  local rel="$1"
  local src="$SOURCE/$rel"
  local dst="$TARGET/$rel"

  if [ ! -e "$src" ]; then
    return
  fi

  # Create parent directory
  mkdir -p "$(dirname "$dst")"

  # On upgrade: skip files the user may have customized
  if [ "$MODE" = "upgrade" ] && [ -f "$dst" ]; then
    # Check if target file differs from source
    if ! diff -q "$src" "$dst" &>/dev/null; then
      echo "  CONFLICT: $rel (kept local version, review manually)"
      # Save the new version alongside for manual review
      cp "$src" "${dst}.kloudify-new"
      return
    fi
  fi

  cp "$src" "$dst"
  echo "  $rel"
}

copy_dir() {
  local rel="$1"
  local src="$SOURCE/$rel"
  local dst="$TARGET/$rel"

  if [ ! -d "$src" ]; then
    return
  fi

  mkdir -p "$dst"

  # Copy all files in directory (non-recursive for safety)
  # Use -print0/read -d '' for paths with spaces or special characters
  while IFS= read -r -d '' f; do
    local fname
    fname=$(basename "$f")
    copy_file "$rel/$fname"
  done < <(find "$src" -maxdepth 1 -type f -print0)
}

copy_tree() {
  local rel="$1"
  local src="$SOURCE/$rel"
  local dst="$TARGET/$rel"

  if [ ! -d "$src" ]; then
    return
  fi

  # Use rsync if available, otherwise manual walk
  if command -v rsync &>/dev/null; then
    rsync -a --ignore-existing "$src/" "$dst/" 2>/dev/null
    echo "  $rel/ (synced)"
  else
    # Manual recursive copy, skip existing on upgrade
    while IFS= read -r -d '' f; do
      local frel="${f#$SOURCE/}"
      copy_file "$frel"
    done < <(find "$src" -type f -print0)
  fi
}

echo "Copying Kloudify files..."

# Root files — CLAUDE.md needs special handling to preserve existing content
if [ -f "$TARGET/CLAUDE.md" ]; then
  # Check if the existing CLAUDE.md is already a Kloudify file
  if grep -q "# Claude Context — Kloudify" "$TARGET/CLAUDE.md" 2>/dev/null; then
    # It is ours — overwrite with the new version, no preservation needed
    cp "$SOURCE/CLAUDE.md" "$TARGET/CLAUDE.md"
    echo "  CLAUDE.md (updated — existing Kloudify version replaced)"
  elif [ "$MODE" = "install" ]; then
    # It is NOT ours — preserve the original content at the bottom.
    # We save it to a temp file and append with cat to avoid heredoc
    # injection (if the file contains our delimiter on its own line).
    local tmpfile
    tmpfile=$(mktemp)
    cp "$TARGET/CLAUDE.md" "$tmpfile"
    cp "$SOURCE/CLAUDE.md" "$TARGET/CLAUDE.md"
    cat >> "$TARGET/CLAUDE.md" << 'PRESERVE_EOF'

---

## Project-Specific Instructions (preserved from original CLAUDE.md)

> The content below was in this project's CLAUDE.md before Kloudify was
> installed. Review it and integrate any relevant instructions into
> Kloudify's system (knowledge-base, memory, or inline in this file).
> Remove this section once you have migrated everything you need.

PRESERVE_EOF
    cat "$tmpfile" >> "$TARGET/CLAUDE.md"
    rm "$tmpfile"
    echo "  CLAUDE.md (installed, original content preserved at bottom)"
  else
    # Upgrade mode, non-Kloudify CLAUDE.md — use normal conflict flow
    copy_file "CLAUDE.md"
  fi
else
  copy_file "CLAUDE.md"
fi
copy_file "CLAUDE.local.md"
copy_file ".mcp.json"

# .gitignore: append Kloudify entries if not present
if [ -f "$TARGET/.gitignore" ]; then
  if ! grep -q "# Kloudify" "$TARGET/.gitignore" 2>/dev/null; then
    echo "" >> "$TARGET/.gitignore"
    # Extract Kloudify-specific gitignore entries from source
    sed -n '/# Session context/,$ p' "$SOURCE/.gitignore" >> "$TARGET/.gitignore"
    echo "  .gitignore (appended Kloudify entries)"
  else
    echo "  .gitignore (already has Kloudify entries, skipped)"
  fi
else
  copy_file ".gitignore"
fi

# .claude/ infrastructure (not session state)
copy_file ".claude/settings.json"
copy_file ".claude/command-index.md"
copy_file ".claude/universal-rules.md"
copy_file ".claude/knowledge-base.md.template"

# Hooks
copy_dir ".claude/hooks"

# Commands
copy_dir ".claude/commands"

# Agents
copy_dir ".claude/agents"

# Skills (recursive — may have subdirectories)
copy_tree ".claude/skills"

# Skills generator
copy_tree ".claude/skills/_generator"

echo ""

# ═══════════════════════════════════════════════════════
# Ensure required directories exist
# ═══════════════════════════════════════════════════════
mkdir -p "$TARGET/.claude/logs" \
         "$TARGET/.claude/agent-memory" \
         "$TARGET/.claude/backups" \
         "$TARGET/.claude/reports" \
         "$TARGET/.claude/plans" \
         "$TARGET/Daily Notes" 2>/dev/null

# ═══════════════════════════════════════════════════════
# Make hooks executable
# ═══════════════════════════════════════════════════════
find "$TARGET/.claude/hooks" -name "*.sh" -exec chmod +x {} \; 2>/dev/null

# ═══════════════════════════════════════════════════════
# Write version marker
# ═══════════════════════════════════════════════════════
# Escape values for safe JSON embedding (handle quotes and backslashes)
json_escape() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}
SAFE_VERSION=$(json_escape "$VERSION")
SAFE_COMMIT=$(json_escape "$COMMIT")
SAFE_REMOTE=$(json_escape "$REMOTE_URL")
SAFE_MODE=$(json_escape "$MODE")

cat > "$TARGET/.claude/kloudify-version.json" << VEOF
{
  "version": "$SAFE_VERSION",
  "source_commit": "$SAFE_COMMIT",
  "installed_at": "$(date +%Y-%m-%d)",
  "source_repo": "$SAFE_REMOTE",
  "mode": "$SAFE_MODE"
}
VEOF
echo "Version marker written: .claude/kloudify-version.json"

# ═══════════════════════════════════════════════════════
# First install: create onboarding sentinel
# ═══════════════════════════════════════════════════════
if [ "$MODE" = "install" ]; then
  cat > "$TARGET/__NEEDS_ONBOARD" << 'OEOF'
This file triggers Kloudify's first-run onboarding.
When Claude Code sees this file, it will run /onboard-init
to scan your project, configure the system, and set up
your working environment.

Delete this file manually if you want to skip onboarding.
OEOF
  echo "Onboarding sentinel created: __NEEDS_ONBOARD"
  echo ""
  echo "Installation complete. Next steps:"
  echo "  1. Open the project in Claude Code"
  echo "  2. The agent will detect __NEEDS_ONBOARD and run /onboard-init"
  echo "  3. Answer the onboarding questions"
  echo "  4. Start working with /start"
else
  echo ""
  echo "Upgrade complete."
  echo "  Files marked CONFLICT have a .kloudify-new copy for manual review."
  echo "  Run /upgrade in Claude Code to migrate your knowledge-base."
fi
