#!/usr/bin/env bash
# preflight_mypy.sh — run mypy on the Python files changed versus a diff base.
#
# Purpose: catch type-check regressions before a push hits CI. Uses the repo's
# existing mypy configuration in pyproject.toml — no new config is introduced.
#
# Usage:
#   scripts/preflight_mypy.sh                       # diff against origin/main
#   scripts/preflight_mypy.sh --diff-base <ref>     # diff against <ref>
#
# Exit codes:
#   0    no changed *.py files, or mypy passed
#   N    mypy's exit code if it reported issues
#
# Notes:
#   - macOS bash 3.2 compatible (no GNU-only flags).
#   - Honors any pre-existing mypy config (pyproject.toml / mypy.ini).

set -eu

DIFF_BASE="origin/main"

usage() {
    cat <<'EOF'
Usage: scripts/preflight_mypy.sh [--diff-base <ref>]

Runs `mypy --pretty` against the set of *.py files changed versus <ref>
(default: origin/main). Exits 0 with a skip message when no Python files
changed. Otherwise exits with mypy's exit code.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --diff-base)
            if [ "$#" -lt 2 ]; then
                echo "error: --diff-base requires a value" >&2
                exit 2
            fi
            DIFF_BASE="$2"
            shift 2
            ;;
        --diff-base=*)
            DIFF_BASE="${1#--diff-base=}"
            shift 1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

# Resolve repo root so this script works regardless of CWD.
REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "${REPO_ROOT}" ]; then
    echo "error: not inside a git repository" >&2
    exit 2
fi
cd "${REPO_ROOT}"

# Compute changed Python files versus the diff base (three-dot form so we
# compare against the merge-base, mirroring CI's changed-file gate).
if ! git rev-parse --verify --quiet "${DIFF_BASE}" >/dev/null; then
    echo "error: diff base '${DIFF_BASE}' is not a valid git ref" >&2
    exit 2
fi

CHANGED_FILES_RAW="$(git diff --name-only "${DIFF_BASE}...HEAD" -- '*.py' || true)"

# Filter out deleted files (mypy cannot type-check a missing path).
CHANGED_FILES=""
if [ -n "${CHANGED_FILES_RAW}" ]; then
    # Iterate line-by-line; portable on macOS bash 3.2.
    while IFS= read -r f; do
        [ -z "$f" ] && continue
        if [ -f "$f" ]; then
            if [ -z "${CHANGED_FILES}" ]; then
                CHANGED_FILES="$f"
            else
                CHANGED_FILES="${CHANGED_FILES}
$f"
            fi
        fi
    done <<EOF
${CHANGED_FILES_RAW}
EOF
fi

# The three-dot diff above selects files from committed state only, so a
# pre-commit run with python edits outside that diff silently skips them.
# Files inside the committed diff ARE handed to mypy (which reads their
# working-tree content), so only dirty paths outside the diff are unchecked —
# surface those as a stderr advisory without touching stdout, mypy argv, or
# exit codes.
UNCOMMITTED_PY="$(
    {
        git diff --name-only --cached -- '*.py' || true
        git diff --name-only -- '*.py' || true
        git ls-files --others --exclude-standard -- '*.py' || true
    } | sort -u | comm -23 - <(printf '%s\n' "${CHANGED_FILES}" | sort)
)"
if [ -n "${UNCOMMITTED_PY}" ]; then
    {
        echo "preflight_mypy: WARNING: uncommitted python changes are NOT checked by this committed-state gate (${DIFF_BASE}...HEAD):"
        echo "${UNCOMMITTED_PY}" | sed 's/^/  /'
        echo "preflight_mypy: commit them and re-run scripts/preflight_mypy.sh to type-check them."
    } >&2
fi

if [ -z "${CHANGED_FILES}" ]; then
    echo "no python changes; mypy preflight skipped"
    exit 0
fi

echo "preflight_mypy: ${DIFF_BASE}...HEAD changed python files:"
echo "${CHANGED_FILES}" | sed 's/^/  /'
echo

# Build an argv from the newline-separated list.
# shellcheck disable=SC2086
set --
while IFS= read -r f; do
    [ -z "$f" ] && continue
    set -- "$@" "$f"
done <<EOF
${CHANGED_FILES}
EOF

if ! command -v mypy >/dev/null 2>&1; then
    echo "error: mypy is not installed in PATH" >&2
    echo "hint: pip install -e '.[dev]' or pip install mypy" >&2
    exit 2
fi

set +e
mypy --pretty "$@"
status=$?
set -e

if [ "${status}" -ne 0 ]; then
    cat >&2 <<EOF

preflight_mypy: mypy reported issues (exit ${status}).
hint:
  - run \`mypy --pretty <file>\` locally on the file(s) above to iterate,
  - or narrow with \`mypy --pretty --show-error-codes <file>\` for triage,
  - then re-run \`scripts/preflight_mypy.sh\` before pushing.
EOF
fi

exit "${status}"
