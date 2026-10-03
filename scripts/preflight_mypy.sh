#!/usr/bin/env bash
# preflight_mypy.sh — run mypy on the Python files changed versus a diff base,
# then run the repo's pre-push typecheck hook.
#
# Purpose: catch type-check regressions before a push hits CI. Two passes:
#   1. repo-config pass: `mypy --pretty` on the changed *.py files using the
#      repo's existing mypy configuration in pyproject.toml.
#   2. pre-push hook parity: the `typecheck-changed` hook from
#      .pre-commit-config.yaml, run through pre-commit, so a branch that
#      passes this preflight is not then blocked at `git push`.
#
# Usage:
#   scripts/preflight_mypy.sh                       # diff against origin/main
#   scripts/preflight_mypy.sh --diff-base <ref>     # diff against <ref>
#
# Exit codes:
#   0    both passes clean (the repo-config pass is skipped when no *.py changed)
#   N    the repo-config pass's mypy exit code if it reported issues, otherwise
#        the hook's exit code if the hook reported issues
#   2    usage error, or mypy / pre-commit not installed
#
# Notes:
#   - macOS bash 3.2 compatible (no GNU-only flags).
#   - Honors any pre-existing mypy config (pyproject.toml / mypy.ini).
#   - The hook plans origin/main...HEAD whatever --diff-base says, exactly as
#     it does on `git push`.

set -eu

DIFF_BASE="origin/main"
HOOK_ID="typecheck-changed"

usage() {
    cat <<'EOF'
Usage: scripts/preflight_mypy.sh [--diff-base <ref>]

Runs `mypy --pretty` against the set of *.py files changed versus <ref>
(default: origin/main), then runs the repo's pre-push `typecheck-changed`
hook through pre-commit. The repo-config pass is skipped when no Python files
changed; the hook always runs. Exits non-zero if either pass reports issues.
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

status=0

if [ -z "${CHANGED_FILES}" ]; then
    echo "no python changes; repo-config mypy pass skipped"
else
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
fi

# Neither pass subsumes the other. The hook runs CI's changed-file form
# (--follow-imports=skip) with its own pinned mypy and stub packages, so it can
# report errors such as [has-type] on attributes initialized only in an
# unchanged base class, which the repo config (follow_imports=silent) resolves.
# The repo-config pass in turn follows imports and reports errors such as
# [arg-type] against unchanged modules that the hook treats as Any. Running
# the hook itself, rather than re-creating its flags here, keeps its mypy
# version, stub set and planner in step with .pre-commit-config.yaml.
echo
echo "preflight_mypy: pre-push hook parity: ${HOOK_ID} (plans origin/main...HEAD, as on git push):"

if ! command -v pre-commit >/dev/null 2>&1; then
    echo "error: pre-commit is not installed in PATH; it is required to reproduce the pre-push ${HOOK_ID} hook" >&2
    echo "hint: pip install -e '.[dev]' or pip install pre-commit" >&2
    exit 2
fi

# --all-files stops pre-commit from stashing unstaged edits. The hook sets
# pass_filenames: false and always_run: true, so it ignores the file list and
# plans its own targets.
set +e
pre-commit run "${HOOK_ID}" --hook-stage pre-push --all-files --verbose
hook_status=$?
set -e

if [ "${hook_status}" -ne 0 ]; then
    cat >&2 <<EOF

preflight_mypy: the pre-push ${HOOK_ID} hook reported issues (exit ${hook_status}); git push would be blocked.
hint:
  - the hook mirrors CI: \`mypy --ignore-missing-imports --follow-imports=skip --show-error-codes\`
    on the changed aragora/**.py files, or \`scripts/test_tiers.sh typecheck\` in full mode,
  - re-run only the hook with \`pre-commit run ${HOOK_ID} --hook-stage pre-push --all-files --verbose\`.
EOF
    if [ "${status}" -eq 0 ]; then
        status="${hook_status}"
    fi
fi

exit "${status}"
