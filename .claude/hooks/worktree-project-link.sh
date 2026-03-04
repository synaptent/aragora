#!/usr/bin/env bash
# worktree-project-link.sh — Directory-level symlink for worktree project dirs.
#
# Problem: Claude Code derives ~/.claude/projects/<encoded-path>/ from CWD.
# When CWD is a worktree, plugins look for transcripts/state in a worktree-
# specific project dir, but the actual data lives in the main repo's project dir.
#
# Fix: Make the worktree project dir a SYMLINK to the main repo project dir.
# All file lookups transparently resolve — no per-file symlinks needed.
#
# Why this scales:
# - Directory-level symlink covers ALL file types (transcripts, settings, state)
# - Transcript files are UUID-named — no conflicts between concurrent sessions
# - Idempotent — safe to call from SessionStart, PostToolUse, and Stop
# - Works regardless of plugin hook ordering (symlink exists before plugins run)
#
# Registered on:
#   SessionStart  — covers sessions launched directly in worktrees
#   PostToolUse   — covers mid-session EnterWorktree (matcher: "EnterWorktree")
#   Stop          — safety net + session lock cleanup

# Defensive: if CWD was deleted (worktree removed), exit gracefully.
if ! cd "${PWD}" 2>/dev/null; then
  exit 0
fi

set -euo pipefail

CWD="$(pwd)"

# --- Session lock cleanup (runs for ALL sessions, not just worktrees) ---
# Remove lock file so worktree autopilot can clean up after session ends.
rm -f "${CWD}/.claude-session-active" 2>/dev/null || true

# --- Worktree project dir symlink ---
# Only act if CWD is inside a worktree directory.
if [[ "$CWD" != *"/.worktrees/"* ]] && [[ "$CWD" != *"/.claude/worktrees/"* ]]; then
  exit 0
fi

CLAUDE_DIR="${HOME}/.claude/projects"

# Derive the worktree project dir (same path mangling Claude Code uses: / and . → -)
worktree_project_dir="${CLAUDE_DIR}/$(echo "$CWD" | sed 's|[/.]|-|g')"

# Find the main repo root by stripping the worktree path suffix.
main_repo="$CWD"
if [[ "$main_repo" == *"/.claude/worktrees/"* ]]; then
  main_repo="${main_repo%%/.claude/worktrees/*}"
elif [[ "$main_repo" == *"/.worktrees/"* ]]; then
  main_repo="${main_repo%%/.worktrees/*}"
fi

main_project_dir="${CLAUDE_DIR}/$(echo "$main_repo" | sed 's|[/.]|-|g')"

# Nothing to do if paths resolve to the same directory.
if [[ "$worktree_project_dir" == "$main_project_dir" ]]; then
  exit 0
fi

# Ensure main project dir exists as a real directory.
mkdir -p "$main_project_dir"

if [[ -L "$worktree_project_dir" ]]; then
  # Already a symlink — verify it points to the right place.
  current_target="$(readlink "$worktree_project_dir" 2>/dev/null || true)"
  if [[ "$current_target" != "$main_project_dir" ]]; then
    rm -f "$worktree_project_dir"
    ln -sf "$main_project_dir" "$worktree_project_dir"
  fi
elif [[ -d "$worktree_project_dir" ]]; then
  # Real directory exists — move contents to main, then replace with symlink.
  # This handles the case where Claude Code created the dir before our hook ran.
  for f in "$worktree_project_dir"/*; do
    [[ -e "$f" ]] || continue
    basename="$(basename "$f")"
    if [[ ! -e "$main_project_dir/$basename" ]]; then
      mv "$f" "$main_project_dir/" 2>/dev/null || true
    fi
  done
  rm -rf "$worktree_project_dir"
  ln -sf "$main_project_dir" "$worktree_project_dir"
else
  # Doesn't exist yet — create parent and symlink.
  # If our hook runs before Claude Code creates the dir, Claude Code will
  # see the symlink as an existing directory (mkdir -p is a no-op on symlinks
  # to dirs) and write all files through it.
  mkdir -p "$(dirname "$worktree_project_dir")"
  ln -sf "$main_project_dir" "$worktree_project_dir"
fi
