# Main-Head Health Runbook

Use this runbook when `origin/main` needs protected-context health evidence but
workflow dispatch is not authorized. The procedure establishes local ground
truth from a pristine exact-head checkout, so settlement and repair decisions do
not depend on noisy shared worktrees or missing GitHub check-runs.

This runbook incorporates the earlier draft on
`origin/codex/main-head-required-checks-runbook-20260707`
(`docs/runbooks/main-head-required-checks.md`) and narrows it to the
no-dispatch verification path.

## No-Dispatch Procedure

Start from the shared root only to fetch and identify the live head:

```bash
git fetch origin --prune
HEAD_SHA=$(git rev-parse origin/main)
git status --short --branch --untracked-files=all
```

Create a pristine detached worktree for the exact head under `/private/tmp`:

```bash
WT=/private/tmp/aragora-main-health-$(date -u +%Y%m%dT%H%M%SZ)
git worktree add --detach "$WT" "$HEAD_SHA"
cd "$WT"
```

Do not diagnose current-main health from the shared root or from an existing
session worktree. Those checkouts can contain user work, branch-specific
dependencies, stale generated files, or partial environment changes that make a
main-health result ambiguous. A detached exact-head worktree keeps the evidence
about `origin/main`, not about the local operator session.

Select and record the interpreter before running the aggregate local proxy. Do
not inherit an unexamined `mypy` from `PATH`:

```bash
PYTHON_BIN="${PYTHON_BIN:-$HOME/.pyenv/versions/3.12.12/bin/python3}"
export PATH="$(dirname "$PYTHON_BIN"):$PATH"

"$PYTHON_BIN" --version
python --version
test "$(python -c 'import os, sys; print(os.path.realpath(sys.executable))')" = \
  "$("$PYTHON_BIN" -c 'import os, sys; print(os.path.realpath(sys.executable))')"
"$PYTHON_BIN" -m mypy --version
MYPY_BIN=$(command -v mypy)
test "$(dirname "$MYPY_BIN")" = "$(dirname "$PYTHON_BIN")"
"$PYTHON_BIN" - <<'PY'
from importlib.metadata import version

for package in ("mypy", "mypy-baseline", "PyJWT"):
    print(f"{package}=={version(package)}")
PY
```

The declared mypy range is `>=2.1.0,<3.0`. A missing mypy, a mypy below that
floor, a `mypy` executable that does not belong to `PYTHON_BIN`, or a bare
`python` that resolves to a different interpreter is an environment failure,
not evidence that `main` is red (the mismatch observed in #9175). The bare
`python` check is load-bearing because `make ci-required` uses it for parity and
OpenAPI commands. For the current #9099 campaign, comparable identity counts
additionally require the campaign's exact environment: Python 3.12.12, mypy
2.2.0, mypy-baseline 0.7.4, and PyJWT 2.13.0. Record all four versions with the
result.

Capture the full log outside the worktree, for example:

```bash
LOG=/tmp/aragora-main-health-ci-required-$(date -u +%Y%m%dT%H%M%SZ).log
if make ci-required >"$LOG" 2>&1; then
  CI_REQUIRED_RC=0
else
  CI_REQUIRED_RC=$?
fi
printf 'ci_required_rc=%s log=%s\n' "$CI_REQUIRED_RC" "$LOG"
```

`/tmp` is only a staging location. Before using the log as settlement or re-arm
evidence, record its SHA-256 digest, copy it to an append-only retained artifact
store, and record that store's immutable artifact identifier. A mutable local
path by itself is not durable evidence.

## Local Context Map

Read live branch protection before using this mapping:

```bash
gh api repos/synaptent/aragora/branches/main/protection/required_status_checks \
  --jq '{strict, contexts, checks}'
```

`make ci-required` is a local proxy for most, but not all, protected contexts.
It is fail-fast, so later rows are `not reached` when an earlier command fails.
Match contexts by the exact branch-protection name. In particular, the protected
`typecheck` context is the fail-closed job in the Lint workflow; it is not the
separate `Tests / Type Check` job, whose mypy command is currently advisory.

| Required context | Local command | Notes |
| --- | --- | --- |
| `lint` | `ruff check aragora/ tests/ scripts/` | Runs first in `make ci-required`. |
| `typecheck` | `mypy aragora/ --ignore-missing-imports` | Proxies the protected Lint workflow context, which runs the full `scripts/test_tiers.sh typecheck` tier on `main` and fails on mypy errors. Do not substitute the non-required `Tests / Type Check` job, which currently truncates diagnostics and exits successfully. |
| `sdk-parity` | `python scripts/check_version_alignment.py`; `python scripts/check_sdk_parity.py --strict --baseline scripts/baselines/check_sdk_parity.json --budget scripts/baselines/check_sdk_parity_budget.json`; `python scripts/check_sdk_namespace_parity.py --strict --baseline scripts/baselines/check_sdk_namespace_parity.json`; `python scripts/check_cross_sdk_parity.py --strict --baseline scripts/baselines/cross_sdk_parity.json` | Not reached if lint or typecheck fails. |
| `Generate & Validate` | `SPEC_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aragora-openapi-ci-required.XXXXXX")"`; `SPEC="$SPEC_DIR/openapi.json"`; `python scripts/generate_openapi.py --output "$SPEC" --format json --quiet`; `python scripts/add_openapi_operation_ids.py --spec "$SPEC"`; `python scripts/add_openapi_param_descriptions.py --spec "$SPEC"`; `python scripts/add_openapi_descriptions.py --spec "$SPEC"`; `python scripts/verify_sdk_contracts.py --strict --baseline scripts/baselines/verify_sdk_contracts.json --extra-spec "$SPEC"`; `python scripts/validate_openapi_routes.py --spec "$SPEC" --fail-on-missing --baseline scripts/baselines/validate_openapi_routes.json` | Not reached if any earlier command fails. Record `SPEC_DIR` with the run so the generated spec can be retained or removed deliberately. |
| `TypeScript SDK Type Check` | Not covered by `make ci-required` at this head. Use the dedicated SDK workflow or an explicitly authorized local command such as `cd sdk/typescript && npm ci && npx tsc --noEmit` when that context is the target. | This gap should not be interpreted as a pass. |
| `aragora-merge-quorum` | No main-head local proxy. | Treat as PR-only/skipped for `main` unless live tooling proves otherwise. |

## Disposition Rules

- If every local proxy passes and no required GitHub context is red, record the
  exact head, log path, elapsed time, and use the result as main-head legitimacy
  evidence for settlement decisions.
- If any local proxy fails, stop at the first failing command. Do not dispatch
  unrelated workflows to mask the failure. The next cycle should repair the
  named failing surface or prove the failure is an environment/tooling mismatch.
- If a required GitHub context is missing but the local proxy is green, prepare
  an exact-head workflow-dispatch authorization prompt for only that missing
  context. Do not dispatch without authorization.
- If `TypeScript SDK Type Check` is missing, do not infer its state from
  `make ci-required`; run or request the dedicated SDK check path.
- If `aragora-merge-quorum` is skipped on `main`, classify it as main-unsafe or
  PR-only rather than dispatching it.

## Human Re-arm Evidence Standard

The presence of `.aragora/merge_executor.halt` is binding. Automated workers
may gather evidence but must not delete, rewrite, or work around the marker.
Re-arm is a separate human action after the following packet is complete.

### 1. Pin the tested state

Record the halt marker before testing, then fetch `main` with an explicit
refspec and create a new detached worktree at the fetched SHA:

```bash
cat .aragora/merge_executor.halt
git fetch origin +refs/heads/main:refs/remotes/origin/main
TESTED_SHA=$(git rev-parse origin/main)
WT=/private/tmp/aragora-main-rearm-${TESTED_SHA:0:12}
git worktree add --detach "$WT" "$TESTED_SHA"
cd "$WT"
test "$(git rev-parse HEAD)" = "$TESTED_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
```

Never reuse a session worktree for re-arm evidence. If `WT` already exists,
choose a new path; do not clean or reset an unverified directory.

### 2. Prove the toolchain before interpreting results

Run the interpreter and package-version preflight from the no-dispatch
procedure above. Classify the run before inspecting code failures:

| Classification | Meaning | Required action |
| --- | --- | --- |
| `infra_error` | Python or required packages are missing; mypy is outside `>=2.1.0,<3.0`; `mypy` resolves outside `PYTHON_BIN`; dependency setup, disk, or runner startup fails. | Repair the environment and rerun. Do not use the result as red-main evidence. |
| `product_red` | A valid pinned environment reaches collection/check execution and reports a mypy diagnostic, collection error, assertion failure, or other reproducible repository failure. | Keep the halt marker. Open or advance a bounded repair against the exact SHA. |
| `inconclusive` | `origin/main` moves during the run, the process times out, or the evidence log is incomplete. | Discard the result and rerun from the new exact head. |
| `green_candidate` | Required and full suites both exit 0 under the recorded environment, with complete logs. | Continue to head-stability and packet review; do not re-arm yet. |

For the #9099 campaign, a run under a different version than Python 3.12.12,
mypy 2.2.0, mypy-baseline 0.7.4, or PyJWT 2.13.0 may diagnose a local problem,
but it cannot prove the campaign identity set has drained.

### 3. Run both required and hidden-red coverage

Capture separate logs and exit codes. The full suite is load-bearing because
path-gated PR checks are the reason the halt exists:

```bash
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
REQUIRED_LOG=/tmp/aragora-main-rearm-required-$STAMP.log
FULL_LOG=/tmp/aragora-main-rearm-full-$STAMP.log

if make ci-required >"$REQUIRED_LOG" 2>&1; then
  REQUIRED_RC=0
else
  REQUIRED_RC=$?
fi

if "$PYTHON_BIN" -m pytest tests/ -q -p no:cacheprovider \
  --ignore=tests/connectors >"$FULL_LOG" 2>&1; then
  FULL_RC=0
else
  FULL_RC=$?
fi

printf 'required_rc=%s full_rc=%s\n' "$REQUIRED_RC" "$FULL_RC"
```

Do not use `&&` between the suites: the packet needs an explicit result for
each. Both exit codes must be zero. Any skip or ignore beyond the command above
must be called out and justified in the packet; it is not silently equivalent
to green.

### 4. Recheck head stability

After both suites finish, prove that the tested commit is still current:

```bash
test "$(git rev-parse HEAD)" = "$TESTED_SHA"
test -z "$(git status --porcelain=v1 --untracked-files=all)"
git fetch origin +refs/heads/main:refs/remotes/origin/main
LIVE_SHA=$(git rev-parse origin/main)
test "$LIVE_SHA" = "$TESTED_SHA"
```

If `LIVE_SHA` differs, classify the packet as `inconclusive`. Green evidence
for an older main commit does not authorize re-arm at the new head.

### 5. Packet fields and human action

The re-arm packet must include:

- the halt marker contents and its original failing SHA
- `TESTED_SHA` and commit summary
- UTC start/end timestamps and elapsed time for each suite
- Python, mypy, mypy-baseline, and PyJWT versions
- exact commands, exit codes, SHA-256 log digests, and immutable retained
  artifact identifiers (`/tmp` staging paths alone do not qualify)
- any skipped/ignored surfaces and why they do not weaken the claim
- final clean-worktree and `LIVE_SHA == TESTED_SHA` proof
- classification: `infra_error`, `product_red`, `inconclusive`, or
  `green_candidate`

Only a `green_candidate` packet may be presented to the human operator for
re-arm. The operator reviews the evidence, confirms the marker still describes
the same incident, and explicitly authorizes removing the exact halt file.
Removal is not implied by a green command result and is never delegated to the
worker that produced the packet. After re-arm, the next merge cycle must still
re-run its normal exact-head ownership, quorum, settlement, and branch-
protection gates.

## Historical Snapshot: 2026-07-08 (Non-Comparable)

This retained observation predates the pinned #9099 campaign profile. It ran
under Python 3.11.11 rather than Python 3.12.12, so it is classified as
`non_comparable_environment`. It may illustrate what that older environment
reported, but it cannot establish `product_red`, red `main`, or a #9099
identity set. Do not use it to trigger preservation, repair, settlement, or
re-arm decisions; rerun the procedure under the exact declared profile first.

| Field | Value |
| --- | --- |
| Exact `origin/main` head | `2543ae8b42f6305e3241cfc64e8658a91f1115ea` |
| Commit summary | `docs(m6): canonical consistency sweep across quickstart/verifier/action docs (#9003)` |
| Detached worktree | `/private/tmp/aragora-main-health-20260708T143015Z` |
| Local command | `PATH="$HOME/.pyenv/versions/3.11.11/bin:$PATH" make ci-required` |
| Evidence classification | `non_comparable_environment` |
| Campaign comparability | Invalid: Python 3.11.11 does not match the required Python 3.12.12 profile. |
| Start / end | `2026-07-08T14:30:36Z` / `2026-07-08T14:31:37Z` |
| Elapsed | 61 seconds |
| Full log | `/tmp/aragora-main-health-ci-required-20260708T143015Z.log` |
| Result | Historical observation only: failed at `typecheck` under a non-comparable environment. |

Per-check result:

| Local check | Status | Evidence |
| --- | --- | --- |
| Ruff lint | pass | Log lines show `ruff check aragora/ tests/ scripts/` followed by `All checks passed!`. |
| Mypy typecheck | fail | `mypy aragora/ --ignore-missing-imports` reported 2,646 errors in 648 files. |
| Version alignment | not reached | `make ci-required` stopped at mypy. |
| SDK parity trio | not reached | `make ci-required` stopped at mypy. |
| OpenAPI generation and route validation | not reached | `make ci-required` stopped at mypy. |
| TypeScript SDK Type Check | not covered | Not part of `make ci-required` at this head. |
| `aragora-merge-quorum` | main-unsafe / skipped | Live exact-head GitHub checks showed skipped quorum jobs for `main`. |

Minimal failing excerpt:

```text
aragora/server/commands/models.py:75: error: Incompatible types in assignment (expression has type "None", variable has type "list[dict[str, Any] | None]")  [assignment]
aragora/server/commands/models.py:78: error: Incompatible types in assignment (expression has type "None", variable has type "list[dict[str, Any] | None]")  [assignment]
aragora/server/commands/models.py:85: error: Incompatible default for argument "blocks" (default has type "None", argument has type "list[dict[str, Any] | None]")  [assignment]
aragora/pipeline/idea_clusterer.py:226: error: Incompatible types in assignment (expression has type "int | None", target has type "int")  [assignment]
...
Found 2646 errors in 648 files (checked 4248 source files)
make: *** [ci-required] Error 1
```

Disposition: non-actionable historical observation. Because the interpreter
does not match the declared campaign profile, this result is not evidence that
`origin/main` was red and must not nominate source or tooling repair. Produce a
fresh exact-profile run before drawing a main-health conclusion.
