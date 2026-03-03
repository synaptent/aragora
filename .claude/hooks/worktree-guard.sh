#!/usr/bin/env bash
# worktree-guard.sh — SessionStart hook for worktree isolation (Layer 2).
#
# Detection order:
# 1. ARAGORA_WORKTREE_ACTIVE=1 → Layer 1 (claude-wt) already handled it → silent
# 2. CWD is inside .worktrees/ or .claude/worktrees/ → already isolated → silent
# 3. Otherwise → output instruction for Claude to call EnterWorktree (Layer 3)

# Layer 1 check: wrapper already created a worktree
if [[ "${ARAGORA_WORKTREE_ACTIVE:-}" == "1" ]]; then
  exit 0
fi

# Already-in-worktree check: CWD is inside a worktree path
CWD="$(pwd)"
if [[ "$CWD" == *"/.worktrees/"* ]] || [[ "$CWD" == *"/.claude/worktrees/"* ]]; then
  exit 0
fi

# Check if we're in the main repo (not a worktree) by looking at git
MAIN_WORKTREE="$(git worktree list --porcelain 2>/dev/null | head -1 | sed 's/^worktree //')"
if [[ -n "$MAIN_WORKTREE" && "$CWD" != "$MAIN_WORKTREE" ]]; then
  # We're in a worktree (just not one of our managed ones) — that's fine
  exit 0
fi

# We're in the main repo directory without isolation.
# Output a warning that Claude will see as a system reminder.
cat << 'WARN'
WORKTREE ISOLATION WARNING: You are running in the main repository directory, not an isolated worktree. Other Claude sessions may be editing files concurrently, which can cause your changes to be overwritten.

ACTION REQUIRED: Before making any file edits, call the EnterWorktree tool to create an isolated worktree. This prevents concurrent session conflicts.

If EnterWorktree is not available or fails, you can still work but should commit changes immediately after each edit to prevent loss.
WARN
