#!/usr/bin/env bash
# Launch Codex in an auto-managed worktree.
#
# Usage:
#   ./scripts/codex_session.sh
#   ./scripts/codex_session.sh --agent codex-qa
#   ./scripts/codex_session.sh --orchestrator crewai
#   ./scripts/codex_session.sh --agent codex-qa --base main -- python -m pytest tests/debate -q
#   ./scripts/codex_session.sh --managed-dir .worktrees/codex-auto-qa --no-maintain --no-reconcile

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT_REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMMON_GIT_DIR="$(
    git -C "${SCRIPT_REPO_ROOT}" rev-parse --path-format=absolute --git-common-dir 2>/dev/null || true
)"
if [[ -n "${COMMON_GIT_DIR}" && "${COMMON_GIT_DIR}" == */.git ]]; then
    REPO_ROOT="$(cd "${COMMON_GIT_DIR%/.git}" && pwd)"
else
    REPO_ROOT="${SCRIPT_REPO_ROOT}"
fi

AGENT="codex"
BASE_BRANCH="main"
RECONCILE=true
MAINTAIN=true
TTL_HOURS="${CODEX_WORKTREE_TTL_HOURS:-24}"
MANAGED_DIR="${CODEX_WORKTREE_MANAGED_DIR:-.worktrees/codex-auto}"
SESSION_ID_OVERRIDE="${CODEX_WORKTREE_SESSION_ID:-}"
ORCHESTRATOR="${CODEX_ORCHESTRATOR:-}"
TASK_ID="${CODEX_WORK_LEASE_TASK_ID:-}"
LEASE_TITLE="${CODEX_WORK_LEASE_TITLE:-}"
LEASE_TTL_HOURS="${CODEX_WORK_LEASE_TTL_HOURS:-8}"
ALLOW_LEASE_OVERLAP=false
WRITE_SCOPES=()
CLAIMED_PATHS=()
TEST_COMMANDS=()

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent)
            AGENT="${2:-}"
            shift 2
            ;;
        --base)
            BASE_BRANCH="${2:-}"
            shift 2
            ;;
        --no-reconcile)
            RECONCILE=false
            shift
            ;;
        --no-maintain)
            MAINTAIN=false
            shift
            ;;
        --ttl-hours)
            TTL_HOURS="${2:-24}"
            shift 2
            ;;
        --managed-dir)
            MANAGED_DIR="${2:-.worktrees/codex-auto}"
            shift 2
            ;;
        --session-id)
            SESSION_ID_OVERRIDE="${2:-}"
            shift 2
            ;;
        --orchestrator)
            ORCHESTRATOR="${2:-}"
            shift 2
            ;;
        --task-id)
            TASK_ID="${2:-}"
            shift 2
            ;;
        --title|--goal)
            LEASE_TITLE="${2:-}"
            shift 2
            ;;
        --lease-ttl-hours)
            LEASE_TTL_HOURS="${2:-8}"
            shift 2
            ;;
        --write-scope)
            WRITE_SCOPES+=("${2:-}")
            shift 2
            ;;
        --claimed-path)
            CLAIMED_PATHS+=("${2:-}")
            shift 2
            ;;
        --test)
            TEST_COMMANDS+=("${2:-}")
            shift 2
            ;;
        --allow-overlap)
            ALLOW_LEASE_OVERLAP=true
            shift
            ;;
        --help|-h)
            sed -n '1,20p' "$0"
            exit 0
            ;;
        --)
            shift
            break
            ;;
        *)
            break
            ;;
    esac
done

ENSURE_ARGS=(ensure --agent "${AGENT}" --base "${BASE_BRANCH}" --print-path)
if [[ -n "${SESSION_ID_OVERRIDE}" ]]; then
    ENSURE_ARGS+=(--session-id "${SESSION_ID_OVERRIDE}")
fi
if ${RECONCILE}; then
    ENSURE_ARGS+=(--reconcile --strategy ff-only)
fi

if ${MAINTAIN}; then
    # Keep startup fast and non-destructive: prune stale trees but keep local branches.
    python3 "${REPO_ROOT}/scripts/codex_worktree_autopilot.py" \
        --repo "${REPO_ROOT}" \
        --managed-dir "${MANAGED_DIR}" \
        maintain \
        --base "${BASE_BRANCH}" \
        --ttl-hours "${TTL_HOURS}" \
        --no-delete-branches \
        >/dev/null 2>&1 || true
fi

WORKTREE_PATH="$(
    python3 "${REPO_ROOT}/scripts/codex_worktree_autopilot.py" \
        --repo "${REPO_ROOT}" \
        --managed-dir "${MANAGED_DIR}" \
        "${ENSURE_ARGS[@]}"
)"

cd "${WORKTREE_PATH}"
echo "Codex worktree: ${WORKTREE_PATH}"

LOCK_FILE="${WORKTREE_PATH}/.codex_session_active"
META_FILE="${WORKTREE_PATH}/.codex_session_meta.json"
LOG_FILE="${WORKTREE_PATH}/.codex_session.log"
STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
BRANCH_NAME="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo detached)"
SESSION_ID="$(basename "${WORKTREE_PATH}")"

if [[ $# -eq 0 ]]; then
    SESSION_MODE="codex"
    SESSION_COMMAND="codex"
    SESSION_ARGS_JSON='["codex"]'
else
    SESSION_MODE="command"
    SESSION_COMMAND="$*"
    SESSION_ARGS_JSON="$(python3 - "$@" <<'PY'
import json
import sys
print(json.dumps(sys.argv[1:]))
PY
)"
fi

if [[ -z "${ORCHESTRATOR}" ]]; then
    cmd_lc="${SESSION_COMMAND,,}"
    case "${cmd_lc}" in
        *gastown*|*bead*|*molecule*)
            ORCHESTRATOR="gastown"
            ;;
        *langchain*)
            ORCHESTRATOR="langchain"
            ;;
        *crewai*|*"crew ai"*)
            ORCHESTRATOR="crewai"
            ;;
        *langgraph*)
            ORCHESTRATOR="langgraph"
            ;;
        *autogen*)
            ORCHESTRATOR="autogen"
            ;;
        *openclaw*)
            ORCHESTRATOR="openclaw"
            ;;
        *nomic*)
            ORCHESTRATOR="nomic"
            ;;
        *)
            ORCHESTRATOR="generic"
            ;;
    esac
fi

printf \
    'pid=%s\nsession_id=%s\nagent=%s\nbranch=%s\nworktree_path=%s\nlog_path=%s\nmeta_path=%s\nmode=%s\norchestrator=%s\nstarted_at=%s\n' \
    "$$" \
    "${SESSION_ID}" \
    "${AGENT}" \
    "${BRANCH_NAME}" \
    "${WORKTREE_PATH}" \
    "${LOG_FILE}" \
    "${META_FILE}" \
    "${SESSION_MODE}" \
    "${ORCHESTRATOR}" \
    "${STARTED_AT}" \
    > "${LOCK_FILE}"

META_FILE="${META_FILE}" \
WORKTREE_PATH="${WORKTREE_PATH}" \
BRANCH_NAME="${BRANCH_NAME}" \
AGENT="${AGENT}" \
SHELL_PID="$$" \
SESSION_ID="${SESSION_ID}" \
LOG_FILE="${LOG_FILE}" \
SESSION_MODE="${SESSION_MODE}" \
ORCHESTRATOR="${ORCHESTRATOR}" \
SESSION_COMMAND="${SESSION_COMMAND}" \
SESSION_ARGS_JSON="${SESSION_ARGS_JSON}" \
STARTED_AT="${STARTED_AT}" \
python3 - <<'PY'
import json
import os
from pathlib import Path

meta = {
    "pid": int(os.environ["SHELL_PID"]),
    "session_id": os.environ["SESSION_ID"],
    "agent": os.environ["AGENT"],
    "branch": os.environ["BRANCH_NAME"],
    "worktree_path": os.environ["WORKTREE_PATH"],
    "log_path": os.environ["LOG_FILE"],
    "mode": os.environ["SESSION_MODE"],
    "orchestrator": os.environ["ORCHESTRATOR"],
    "command": os.environ["SESSION_COMMAND"],
    "args": json.loads(os.environ["SESSION_ARGS_JSON"]),
    "started_at": os.environ["STARTED_AT"],
}
Path(os.environ["META_FILE"]).write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
PY

LEASE_ID=""
if [[ -n "${TASK_ID}" || -n "${LEASE_TITLE}" || ${#WRITE_SCOPES[@]} -gt 0 || ${#CLAIMED_PATHS[@]} -gt 0 || ${#TEST_COMMANDS[@]} -gt 0 ]]; then
    if [[ -z "${TASK_ID}" ]]; then
        TASK_ID="${SESSION_ID}"
    fi
    if [[ -z "${LEASE_TITLE}" ]]; then
        LEASE_TITLE="${SESSION_COMMAND}"
    fi

    LEASE_CMD=(
        python3 -m aragora.nomic.dev_coordination
        --repo "${REPO_ROOT}"
        claim
        --task-id "${TASK_ID}"
        --title "${LEASE_TITLE}"
        --agent "${AGENT}"
        --session-id "${SESSION_ID}"
        --branch "${BRANCH_NAME}"
        --worktree "${WORKTREE_PATH}"
        --ttl-hours "${LEASE_TTL_HOURS}"
    )
    for scope in "${WRITE_SCOPES[@]}"; do
        LEASE_CMD+=(--write-scope "${scope}")
    done
    for path in "${CLAIMED_PATHS[@]}"; do
        LEASE_CMD+=(--claimed-path "${path}")
    done
    for test_cmd in "${TEST_COMMANDS[@]}"; do
        LEASE_CMD+=(--test "${test_cmd}")
    done
    if ${ALLOW_LEASE_OVERLAP}; then
        LEASE_CMD+=(--allow-overlap)
    fi

    LEASE_ID="$("${LEASE_CMD[@]}")"

    printf 'lease_id=%s\n' "${LEASE_ID}" >> "${LOCK_FILE}"
    META_FILE="${META_FILE}" LEASE_ID="${LEASE_ID}" python3 - <<'PY'
import json
import os
from pathlib import Path

meta_path = Path(os.environ["META_FILE"])
meta = json.loads(meta_path.read_text(encoding="utf-8"))
meta["lease_id"] = os.environ["LEASE_ID"]
meta_path.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
PY
fi

{
    echo "=== session_start ==="
    echo "started_at=${STARTED_AT}"
    echo "pid=$$"
    echo "agent=${AGENT}"
    echo "branch=${BRANCH_NAME}"
    echo "mode=${SESSION_MODE}"
    echo "orchestrator=${ORCHESTRATOR}"
    echo "command=${SESSION_COMMAND}"
} >> "${LOG_FILE}"

cleanup_lock() {
    local exit_code=$?
    local ended_at
    ended_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

    {
        echo "=== session_end ==="
        echo "ended_at=${ended_at}"
        echo "exit_code=${exit_code}"
    } >> "${LOG_FILE}" 2>/dev/null || true

    META_FILE="${META_FILE}" \
    ENDED_AT="${ended_at}" \
    EXIT_CODE="${exit_code}" \
    python3 - <<'PY' >/dev/null 2>&1
import json
import os
from pathlib import Path

meta_path = Path(os.environ["META_FILE"])
if not meta_path.exists():
    raise SystemExit(0)
data = json.loads(meta_path.read_text(encoding="utf-8"))
data["ended_at"] = os.environ["ENDED_AT"]
data["exit_code"] = int(os.environ["EXIT_CODE"])
meta_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
PY

    rm -f "${LOCK_FILE}" 2>/dev/null || true
}
trap cleanup_lock EXIT INT TERM

if command -v script >/dev/null 2>&1; then
    if [[ $# -eq 0 ]]; then
        script -q "${LOG_FILE}" codex
    else
        script -q "${LOG_FILE}" "$@"
    fi
    exit $?
fi

# Fallback when script(1) is unavailable.
if [[ $# -eq 0 ]]; then
    codex 2>&1 | tee -a "${LOG_FILE}"
    exit ${PIPESTATUS[0]}
fi

"$@" 2>&1 | tee -a "${LOG_FILE}"
exit ${PIPESTATUS[0]}
