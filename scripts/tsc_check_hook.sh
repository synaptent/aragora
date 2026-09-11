#!/usr/bin/env bash
# Local pre-push hook: TypeScript type check for the frontend (aragora/live).
#
# A fresh worktree has no aragora/live/node_modules, and `tsc` then fails with
# TS2688 "Cannot find type definition file for 'node'/'jest'". That is an
# environment artifact, not a code error, and it tempts `git push --no-verify`,
# which also skips every other pre-push hook. So when dependencies are absent
# this hook skips itself with a clear message; CI's TypeScript checks remain the
# authoritative gate. Set ARAGORA_TSC_CHECK_STRICT=1 to fail instead of skip.
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
live="$root/aragora/live"

if [ ! -d "$live/node_modules" ]; then
  if [ "${ARAGORA_TSC_CHECK_STRICT:-0}" = "1" ]; then
    echo "tsc-check: aragora/live/node_modules is absent and ARAGORA_TSC_CHECK_STRICT=1, failing." >&2
    exit 1
  fi
  echo "tsc-check: SKIPPED. aragora/live/node_modules is absent in this checkout (fresh worktree)."
  echo "           CI's TypeScript checks remain authoritative. To run the check locally first:"
  echo "             (cd aragora/live && npm ci)"
  exit 0
fi

cd "$live"
exec npx tsc --noEmit
