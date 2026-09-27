#!/usr/bin/env bash
# Shared mergeability preflight for local Codex automations and swarm/boss-loop PRs.

set -euo pipefail

JSON_MODE=false
if [[ "${1:-}" == "--json" ]]; then
    JSON_MODE=true
    shift
fi

BASE_REF="${1:-origin/main}"
HEAD_REF="${2:-HEAD}"
changed_files=""
source_changes=""
test_changes=""
docs_only_changes=""
forbidden_files=""
rescue_publish_files=""
publisher_startup_changes=""
docs_only=false

usage() {
    cat <<'EOF'
Usage: scripts/automation_pr_preflight.sh [--json] [BASE_REF] [HEAD_REF]

Checks an automation branch before it is pushed or turned into a PR.

Checks:
  - base and head refs exist
  - branch has a non-empty diff versus the base
  - diff has no whitespace errors
  - session/log/coordination artifacts are not committed
  - non-canonical rescue productization publish artifacts are not committed
  - synthetic preflight validation commits/scratch diffs are not published
  - source changes without test changes are called out for operator review
EOF
}

emit_json() {
    local status="$1"
    local error="${2:-}"
    export PREFLIGHT_BASE_REF="${BASE_REF}"
    export PREFLIGHT_HEAD_REF="${HEAD_REF}"
    export PREFLIGHT_STATUS="${status}"
    export PREFLIGHT_ERROR="${error}"
    export PREFLIGHT_CHANGED_FILES="${changed_files}"
    export PREFLIGHT_SOURCE_CHANGES="${source_changes}"
    export PREFLIGHT_TEST_CHANGES="${test_changes}"
    export PREFLIGHT_DOCS_ONLY="${docs_only}"
    export PREFLIGHT_FORBIDDEN_FILES="${forbidden_files}"
    export PREFLIGHT_RESCUE_PUBLISH_FILES="${rescue_publish_files}"
    export PREFLIGHT_PUBLISHER_STARTUP_CHANGES="${publisher_startup_changes}"
    python3 -c '
import json
import os
import shlex


def lines(name: str) -> list[str]:
    return [line for line in os.environ.get(name, "").splitlines() if line]


changed_paths = set(lines("PREFLIGHT_CHANGED_FILES"))
source_changes = lines("PREFLIGHT_SOURCE_CHANGES")
test_changes = lines("PREFLIGHT_TEST_CHANGES")
publisher_startup_changes = lines("PREFLIGHT_PUBLISHER_STARTUP_CHANGES")
changed_paths = set(lines("PREFLIGHT_CHANGED_FILES"))
python_sources = [path for path in source_changes if path.endswith(".py")]
suggested_commands: list[str] = []
if python_sources:
    quoted = " ".join(shlex.quote(path) for path in python_sources)
    suggested_commands.append(
        f"python3 scripts/nomic_ci_test_selector.py --changed-files {quoted} --dry-run"
    )
    suggested_commands.append(f"python3 -m ruff check {quoted}")
if "scripts/agent_bridge.py" in source_changes:
    suggested_commands.append("python3 scripts/agent_bridge.py operator-snapshot --json --summary-only")
if test_changes:
    quoted_tests = " ".join(shlex.quote(path) for path in test_changes)
    suggested_commands.append(f"python3 -m pytest {quoted_tests} -q")
if changed_paths & {
    "scripts/render_benchmark_truth_status.py",
    "tests/scripts/test_render_benchmark_truth_status.py",
}:
    suggested_commands.append("python3 -m py_compile scripts/render_benchmark_truth_status.py")
    pytest_command = "python3 -m pytest tests/scripts/test_render_benchmark_truth_status.py -q"
    if pytest_command not in suggested_commands:
        suggested_commands.append(pytest_command)
if publisher_startup_changes:
    startup_modules = (
        "scripts.cache_codex_automation_github_status",
        "scripts.publish_automation_handoffs",
        "scripts.publish_codex_automation_branches",
        "scripts.github_cli_health",
    )
    suggested_commands.append(
        "python3 -c \"import importlib; [importlib.import_module(module) "
        f"for module in {startup_modules!r}]\""
    )

payload = {
    "base_ref": os.environ["PREFLIGHT_BASE_REF"],
    "head_ref": os.environ["PREFLIGHT_HEAD_REF"],
    "status": os.environ["PREFLIGHT_STATUS"],
    "changed_files": lines("PREFLIGHT_CHANGED_FILES"),
    "docs_only": os.environ.get("PREFLIGHT_DOCS_ONLY") == "true",
    "source_without_tests": bool(source_changes) and not bool(test_changes),
    "forbidden_files": lines("PREFLIGHT_FORBIDDEN_FILES"),
    "rescue_publish_files": lines("PREFLIGHT_RESCUE_PUBLISH_FILES"),
    "suggested_validation_commands": suggested_commands,
}
error = os.environ.get("PREFLIGHT_ERROR", "")
if error:
    payload["error"] = error
print(json.dumps(payload, sort_keys=True))
'
}

fail_preflight() {
    local exit_code="$1"
    local error="$2"
    if [[ "${JSON_MODE}" == "true" ]]; then
        emit_json "failed" "${error}"
    else
        echo "preflight: ${error}" >&2
    fi
    exit "${exit_code}"
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
    usage
    exit 0
fi

if ! git rev-parse --verify "${BASE_REF}^{commit}" >/dev/null 2>&1; then
    fail_preflight 2 "base ref not found: ${BASE_REF}"
fi

if ! git rev-parse --verify "${HEAD_REF}^{commit}" >/dev/null 2>&1; then
    fail_preflight 2 "head ref not found: ${HEAD_REF}"
fi

changed_files="$(git diff --name-only "${BASE_REF}...${HEAD_REF}")"
if [[ -z "${changed_files}" ]]; then
    fail_preflight 1 "no branch diff versus ${BASE_REF}"
fi

head_subject="$(git log -1 --pretty=%s "${HEAD_REF}")"
normalized_subject="$(printf '%s' "${head_subject}" | tr '[:upper:]' '[:lower:]')"
changed_file_count="$(printf '%s\n' "${changed_files}" | sed '/^$/d' | wc -l | tr -d ' ')"

if [[ "${normalized_subject}" == "chore: preflight worker check" || "${normalized_subject}" == "[preflight] worker check" ]]; then
    if [[ "${JSON_MODE}" == "true" ]]; then
        fail_preflight 1 "synthetic preflight validation commits must not be published"
    fi
    echo "preflight: synthetic preflight validation commits must not be published:" >&2
    echo "  subject: ${head_subject}" >&2
    exit 1
fi

if [[ "${changed_file_count}" == "1" && "${changed_files}" == "scratch/preflight_worker_check.txt" ]]; then
    fail_preflight 1 "synthetic preflight validation scratch diffs must not be published."
fi

if [[ "${JSON_MODE}" != "true" ]]; then
    echo "preflight: checking whitespace"
fi
if ! whitespace_output="$(git diff --check "${BASE_REF}...${HEAD_REF}" 2>&1)"; then
    if [[ "${JSON_MODE}" == "true" ]]; then
        fail_preflight 1 "${whitespace_output}"
    fi
    printf '%s\n' "${whitespace_output}" >&2
    exit 1
fi

forbidden_regex='^\.aragora/|(^|/)(\.codex_session_active|\.claude-session-active|\.nomic-session-active|\.codex_session_meta\.json|\.swarm_worker_stdout\.log|\.swarm_worker_stderr\.log|\.swarm_worker_status\.json|\.swarm_repair_journal\.json|\.operator_state\.json|\.operator_snapshot\.json)$|(^|/)(\.aragora_events|\.pytest_cache|__pycache__)/'
forbidden_files="$(printf '%s\n' "${changed_files}" | grep -E "${forbidden_regex}" || true)"
if [[ -n "${forbidden_files}" ]]; then
    if [[ "${JSON_MODE}" == "true" ]]; then
        fail_preflight 1 "automation/session artifacts must not be committed"
    fi
    echo "preflight: automation/session artifacts must not be committed:" >&2
    printf '%s\n' "${forbidden_files}" >&2
    exit 1
fi

rescue_publish_regex='(^|/)rescue-productization-[^/]*\.json$|(^|/)(rescue_productization|rescue-productization)(/.*)?/(latest\.json|rescue-productization-[^/]*\.json)$|^docs/status/generated/rescue_productization/.*$'
canonical_rescue_status_regex='^docs/status/generated/rescue_productization/(latest\.json|rescue-productization-[0-9]{8}T[0-9]{6}Z\.json)$'
rescue_publish_files="$(printf '%s\n' "${changed_files}" | grep -E "${rescue_publish_regex}" | grep -Ev "${canonical_rescue_status_regex}" || true)"
if [[ -n "${rescue_publish_files}" ]]; then
    if [[ "${JSON_MODE}" == "true" ]]; then
        fail_preflight 1 "rescue productization publish artifacts must not be committed"
    fi
    echo "preflight: rescue productization publish artifacts must not be committed:" >&2
    printf '%s\n' "${rescue_publish_files}" >&2
    exit 1
fi

source_changes="$(printf '%s\n' "${changed_files}" | grep -E '(^aragora/|^scripts/|^\.github/|^tests/).*\.(py|sh|ya?ml|toml|json|ts|tsx|js|jsx)$' || true)"
test_changes="$(printf '%s\n' "${changed_files}" | grep -E '(^tests/|__tests__/|\.test\.|\.spec\.)' || true)"
publisher_startup_changes="$(printf '%s\n' "${changed_files}" | grep -E '^scripts/(cache_codex_automation_github_status|github_cli_health|publish_automation_handoffs|publish_codex_automation_branches)\.py$' || true)"
docs_only_changes="$(printf '%s\n' "${changed_files}" | grep -Ev '(^docs/|^docs-site/|\.md$)' || true)"
if [[ -z "${docs_only_changes}" ]]; then
    docs_only=true
fi

if printf '%s\n' "${changed_files}" | grep -qx 'docs/status/NEXT_STEPS_CANONICAL.md'; then
    next_steps_blob="${HEAD_REF}:docs/status/NEXT_STEPS_CANONICAL.md"
    if ! git cat-file -e "${next_steps_blob}" 2>/dev/null; then
        fail_preflight 1 "docs/status/NEXT_STEPS_CANONICAL.md must exist at ${HEAD_REF}"
    fi
    next_steps_content="$(git show "${next_steps_blob}")"
    stale_proof_regex='Current May 28 proof-loop state|truth_success_rate_verified over five verified entries|full-corpus truth remains 38\.5%'
    if printf '%s\n' "${next_steps_content}" | grep -Eq "${stale_proof_regex}"; then
        fail_preflight 1 "docs/status/NEXT_STEPS_CANONICAL.md still contains stale proof-loop percentages"
    fi
    for required_ref in B0_BENCHMARK_TRUTH_STATUS TW03_RESCUE_PRODUCTIZATION_STATUS 'Current proof-loop state'; do
        if ! printf '%s\n' "${next_steps_content}" | grep -Fq "${required_ref}"; then
            fail_preflight 1 "docs/status/NEXT_STEPS_CANONICAL.md is missing live proof-surface reference: ${required_ref}"
        fi
    done
fi

if [[ "${JSON_MODE}" == "true" ]]; then
    emit_json "ok"
    exit 0
fi

if [[ -n "${source_changes}" && -z "${test_changes}" ]]; then
    echo "preflight: source/config changes found without test changes." >&2
    echo "preflight: run the relevant validation command and include it in the PR body." >&2
    echo "preflight: changed source/config paths:" >&2
    printf '%s\n' "${source_changes}" >&2
fi

if [[ "${docs_only}" == "true" ]]; then
    echo "preflight: docs-only diff detected"
fi

echo "preflight: changed files"
printf '%s\n' "${changed_files}" | sed 's/^/  - /'

# Opt-in Tier-4 merge-train guard (default off; flip ARAGORA_TIER4_MERGE_TRAIN=1).
# Refuses to add an (N+1)th concurrent open PR to a serialized Tier-4 surface
# (e.g. scripts/settle_tier4_pr.py), which is what creates the settlement
# pile-up + re-conflict churn. Best-effort: a transport/tooling failure warns
# and does NOT block (only a clean queue decision, exit 2, fails the preflight).
# Reads open-PR state via the App token, so it never burns the operator PAT.
if [[ "${ARAGORA_TIER4_MERGE_TRAIN:-0}" == "1" ]]; then
    changed_csv="$(printf '%s\n' "${changed_files}" | sed '/^$/d' | paste -sd, -)"
    train_args=(--check --changed-files "${changed_csv}" --repo "${ARAGORA_TIER4_MERGE_TRAIN_REPO:-synaptent/aragora}")
    if [[ -n "${ARAGORA_TIER4_MERGE_TRAIN_PR:-}" ]]; then
        train_args+=(--candidate-pr "${ARAGORA_TIER4_MERGE_TRAIN_PR}")
    fi
    if [[ -n "${ARAGORA_TIER4_MERGE_TRAIN_CAP:-}" ]]; then
        train_args+=(--cap "${ARAGORA_TIER4_MERGE_TRAIN_CAP}")
    fi
    set +e
    train_out="$(python3 scripts/tier4_merge_train.py "${train_args[@]}" 2>&1)"
    train_rc=$?
    set -e
    if [[ "${train_rc}" -eq 2 ]]; then
        fail_preflight 2 "tier-4 merge-train lane full: ${train_out}"
    elif [[ "${train_rc}" -ne 0 ]]; then
        echo "preflight: tier-4 merge-train check skipped (non-fatal): ${train_out}" >&2
    else
        echo "preflight: tier-4 merge-train lane has room"
    fi
fi

echo "preflight: ok"
