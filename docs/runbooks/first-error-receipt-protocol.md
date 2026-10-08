# First-Error Diagnostic Receipt Protocol

Use this protocol when diagnosing a long-running failure or timeout on an exact
`origin/main` commit. It makes ownership visible before the run starts and
preserves a useful result even when pytest fails, times out, or is terminated.

This is a diagnostic protocol. It does not authorize changing a main-health
halt, rerunning CI, settling or merging a PR, or deleting another diagnostic
worktree.

## 1. Create A Dedicated Worktree

Never run a first-error diagnostic in the shared checkout or take over an
existing diagnostic worktree. Fetch the exact target and create a new detached
worktree:

```bash
SOURCE_ROOT="$(git rev-parse --show-toplevel)"
COMMON_GIT_DIR="$(
  git -C "$SOURCE_ROOT" rev-parse --path-format=absolute --git-common-dir
)"
SHARED_ROOT="$(dirname "$COMMON_GIT_DIR")"

test -d "$COMMON_GIT_DIR"
test -d "$SHARED_ROOT/.git"

git -C "$SOURCE_ROOT" fetch origin --prune
MAIN_SHA="$(git -C "$SOURCE_ROOT" rev-parse origin/main)"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
TMP_ROOT="${TMPDIR:-/tmp}"
TMP_ROOT="${TMP_ROOT%/}"
WT="$TMP_ROOT/aragora-main-first-error-$TS"

git -C "$SOURCE_ROOT" worktree add --detach "$WT" "$MAIN_SHA"
mkdir -p "$WT/logs" "$SHARED_ROOT/.aragora/main-red"
```

`SOURCE_ROOT` may itself be a linked or disposable worktree. `SHARED_ROOT` is
derived from Git's common directory and therefore names the primary checkout
that owns the worktree registry. Stop as `infra_error` if either directory
check fails; do not fall back to storing the durable receipt in `SOURCE_ROOT`.

Do not silently retarget the worktree if `origin/main` moves. Finish or stop
the run against `MAIN_SHA`, then start a new worktree for the new commit.

## 2. Write Ownership Before Starting

Write `logs/OWNER.json` before launching pytest. The marker is a lease-like
claim for this diagnostic object, not a development branch lease.

```json
{
  "schema": "aragora.main_first_error_owner.v1",
  "owner_session": "<lane-or-session-id>",
  "pid": 12345,
  "started_utc": "2026-07-11T17:00:00Z",
  "purpose": "exact-main first-error diagnostic",
  "main_sha": "<40-character SHA>",
  "command_log": "logs/first-error-<timestamp>.log",
  "ttl_hours": 6
}
```

The owner must update the marker before extending the TTL. A missing heartbeat
does not make an unexpired marker safe to reclaim.

## 3. Stream Output To A Durable Log

Use the interpreter, scope, and exclusions from the incident being reproduced.
Save the example as `<worktree>/logs/run-first-error.sh` and execute that
driver; do not paste its `exit` paths into an interactive shell. The driver
derives its worktree, exact SHA, timestamp, and durable shared root from its
own location, so it does not depend on variables left in the setup shell.
Bound the process group with `gtimeout` on macOS or `timeout` elsewhere, and
preserve the pytest side of the pipeline:

```bash
#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
WT="$(cd "$SCRIPT_DIR/.." && pwd -P)"
MAIN_SHA="$(git -C "$WT" rev-parse HEAD)"
COMMON_GIT_DIR="$(
  git -C "$WT" rev-parse --path-format=absolute --git-common-dir
)"
SHARED_ROOT="$(dirname "$COMMON_GIT_DIR")"
TS="${FIRST_ERROR_TS:-$(date -u +%Y%m%dT%H%M%SZ)}"

test -d "$COMMON_GIT_DIR"
test -d "$SHARED_ROOT/.git"
mkdir -p "$WT/logs" "$SHARED_ROOT/.aragora/main-red"

cd "$WT"
LOG="logs/first-error-$TS.log"
TEST_TIMEOUT="${TEST_TIMEOUT:-1800s}"
PYTHON_BIN="${PYTHON_BIN:-python}"
PYTEST_ARGS=(
  -m pytest tests/ -x -v -p no:cacheprovider
  --ignore=tests/connectors
)
STARTED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START_EPOCH="$(date +%s)"
PRECHECK_ERROR=""

if command -v gtimeout >/dev/null 2>&1; then
  TIMEOUT_BIN=gtimeout
elif command -v timeout >/dev/null 2>&1; then
  TIMEOUT_BIN=timeout
else
  TIMEOUT_BIN=""
  PRECHECK_ERROR="no supported timeout binary"
fi

if [[ -n "$PRECHECK_ERROR" ]]; then
  TEST_RC=2
  printf '%s\n' "$PRECHECK_ERROR" | tee "$LOG"
  COMMAND="unavailable: $PRECHECK_ERROR"
else
  COMMAND="PYTHONUNBUFFERED=1 $TIMEOUT_BIN --signal=TERM --kill-after=30s"
  COMMAND+=" $TEST_TIMEOUT $PYTHON_BIN ${PYTEST_ARGS[*]}"
  set +e
  PYTHONUNBUFFERED=1 "$TIMEOUT_BIN" --signal=TERM --kill-after=30s \
    "$TEST_TIMEOUT" "$PYTHON_BIN" "${PYTEST_ARGS[@]}" 2>&1 | tee "$LOG"
  TEST_RC="${PIPESTATUS[0]}"
  set -e
fi

ENDED_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
END_EPOCH="$(date +%s)"
WALL_SECONDS="$((END_EPOCH - START_EPOCH))"

if [[ -n "$PRECHECK_ERROR" ]]; then
  OUTCOME=infra_error
  NEXT_ACTION="install a supported timeout command, then start a new diagnostic"
else
  case "$TEST_RC" in
    0)
      OUTCOME=green
      NEXT_ACTION="record the bounded green scope; do not generalize beyond it"
      ;;
    1)
      OUTCOME=test_failure
      NEXT_ACTION="repair or isolate the first failing node before rerunning"
      ;;
    124|137)
      OUTCOME=timeout_only_no_failure
      NEXT_ACTION="narrow the scope or extend the timeout without declaring main red"
      ;;
    2|3|4|5)
      OUTCOME=collection_error
      NEXT_ACTION="repair the pytest collection or invocation error"
      ;;
    *)
      OUTCOME=infra_error
      NEXT_ACTION="diagnose the unexpected runner exit before retrying"
      ;;
  esac
fi

if [[ ! -s "$LOG" ]]; then
  OUTCOME=infra_error
  NEXT_ACTION="repair logging before retrying the diagnostic"
fi

FIRST_NODEID="$({
  awk '/::/ && ($0 ~ / FAILED / || $0 ~ / ERROR /) {print $1; exit}' "$LOG"
} || true)"
TRACEBACK_HEAD="$({
  awk '
    /^=+ (FAILURES|ERRORS) =+$/ {capture=1; next}
    capture && count < 40 {print; count++}
  ' "$LOG"
} || true)"
PROGRESS="$({
  grep -E '^[^[:space:]]+::[^[:space:]]+[[:space:]]+(PASSED|FAILED|ERROR|SKIPPED|XFAIL|XPASS)' \
    "$LOG" | tail -n 5
} || true)"

inline_receipt_field() {
  if [[ -z "$1" ]]; then
    printf 'null'
  else
    printf '%s' "$1" | tr '\n' ' '
  fi
}

TRACEBACK_FIELD="$(inline_receipt_field "$TRACEBACK_HEAD")"
PROGRESS_FIELD="$(inline_receipt_field "$PROGRESS")"

if command -v shasum >/dev/null 2>&1; then
  LOG_SHA256="$(shasum -a 256 "$LOG" | awk '{print $1}')"
elif command -v sha256sum >/dev/null 2>&1; then
  LOG_SHA256="$(sha256sum "$LOG" | awk '{print $1}')"
else
  LOG_SHA256=unavailable
  OUTCOME=infra_error
  NEXT_ACTION="install a SHA-256 utility before retrying the diagnostic"
fi

REPORT_WORKTREE="logs/first-error-report-$TS.md"
REPORT_SHARED="$SHARED_ROOT/.aragora/main-red/first-error-report-$TS.md"
REPORT_TMP="logs/.first-error-report-$TS.tmp"
{
  printf '# First-Error Diagnostic Receipt\n\n'
  printf -- '- schema: `aragora.main_first_error_receipt.v1`\n'
  printf -- '- main_sha: `%s`\n' "$MAIN_SHA"
  printf -- '- started_utc: `%s`\n' "$STARTED_UTC"
  printf -- '- ended_utc: `%s`\n' "$ENDED_UTC"
  printf -- '- wall_seconds: `%s`\n' "$WALL_SECONDS"
  printf -- '- command: `%s`\n' "$COMMAND"
  printf -- '- exit_code: `%s`\n' "$TEST_RC"
  printf -- '- outcome: `%s`\n' "$OUTCOME"
  printf -- '- first_nodeid: `%s`\n' "${FIRST_NODEID:-null}"
  printf -- '- log_path: `%s`\n' "$LOG"
  printf -- '- log_sha256: `%s`\n' "$LOG_SHA256"
  printf -- '- next_action: %s\n' "$NEXT_ACTION"
  printf -- '- traceback_head: %s\n' "$TRACEBACK_FIELD"
  printf -- '- progress: %s\n' "$PROGRESS_FIELD"
  printf '\n## Traceback head\n\n'
  if [[ -n "$TRACEBACK_HEAD" ]]; then
    printf '```text\n%s\n```\n' "$TRACEBACK_HEAD"
  else
    printf 'null\n'
  fi
  printf '\n## Progress\n\n'
  if [[ -n "$PROGRESS" ]]; then
    printf '```text\n%s\n```\n' "$PROGRESS"
  else
    printf 'null\n'
  fi
} > "$REPORT_TMP"

cp "$REPORT_TMP" "$REPORT_WORKTREE"
cp "$REPORT_TMP" "$REPORT_SHARED"
rm -f "$REPORT_TMP"

DRIVER_RC="$TEST_RC"
if [[ "$OUTCOME" == infra_error ]]; then
  DRIVER_RC=2
fi
exit "$DRIVER_RC"
```

Run the saved driver with `bash "$WT/logs/run-first-error.sh"`. A caller may
set `FIRST_ERROR_TS` to coordinate related receipt filenames, but no setup
variable is required for a correct run.

`PIPESTATUS` is intentionally Bash-specific, which is why the example is a
driver script rather than an interactive-shell fragment. Set `TEST_TIMEOUT`
for the incident scope: 30 minutes can be appropriate for a focused shard but
is not expected to prove that the full `tests/` suite is green. Record the
selected timeout and test scope in the receipt.

Do not rely on terminal scrollback. A run without a non-empty log is
`infra_error`, even if the operator observed output on screen.

## 4. Write The Report Before Exit

Every run must write a report, including timeout and infrastructure outcomes.
Write it before cleanup, comments, branch publication, or returning from the
driver script.

Required fields:

| Field | Requirement |
| --- | --- |
| `schema` | `aragora.main_first_error_receipt.v1` |
| `main_sha` | Exact 40-character commit tested |
| `started_utc`, `ended_utc`, `wall_seconds` | UTC timestamps and measured duration |
| `command` | Exact command, interpreter, timeout, plugins, and exclusions |
| `exit_code` | Pipeline command exit code, not `tee`'s exit code |
| `outcome` | One of `test_failure`, `timeout_only_no_failure`, `collection_error`, `infra_error`, or `green` |
| `first_nodeid` | First failing or timed-out node ID, or `null` |
| `traceback_head` | Bounded traceback head, or `null` |
| `progress` | Last completed node IDs, percentage, counts, or other bounded progress evidence |
| `log_path`, `log_sha256` | Worktree-relative path and digest |
| `next_action` | One concrete follow-up that does not overstate the result |

A timeout without a failing node ID is `timeout_only_no_failure`, not proof
that main is test-red. A missing dependency, unavailable timeout command, or
empty log is `infra_error`.

Store the report in both locations before the driver exits:

```text
<worktree>/logs/first-error-report-<timestamp>.md
<shared-checkout-root>/.aragora/main-red/first-error-report-<timestamp>.md
```

The worktree copy travels with the diagnostic context. The shared checkout is
the `SHARED_ROOT` resolved from Git's common directory, not whichever linked
worktree launched the diagnostic. Its `.aragora` copy therefore survives later
helper-mediated cleanup of the diagnostic or source worktree.

## 5. Reclaim Conservatively

Treat an existing diagnostic worktree as owned unless every check below is
clear:

1. No process has the worktree as its current directory or an open file.
2. No matching pytest, timeout wrapper, or diagnostic driver process remains.
3. No unexpired `logs/OWNER.json` exists.
4. Worktree and `logs/` mtimes remain unchanged across a 90-second window.
5. The owner marker TTL has expired, if a marker exists.
6. `safe_worktree_cleanup.py inspect` reports the worktree state without
   unknown or dirty-work blockers.

Use read-only probes:

```bash
ps -eo pid=,etime=,command= |
  awk -v wt="$OLD_WT" \
    'index($0, wt) && /pytest|first-error|timeout|gtimeout/ && $0 !~ /awk -v wt=/'
lsof +D "$OLD_WT" 2>/dev/null

mtime_line() {
  if stat -f '%m %N' "$@" >/dev/null 2>&1; then
    stat -f '%m %N' "$@"
  else
    stat -c '%Y %n' "$@"
  fi
}

mtime_line "$OLD_WT" "$OLD_WT/logs"
sleep 90
mtime_line "$OLD_WT" "$OLD_WT/logs"
python3 scripts/safe_worktree_cleanup.py inspect "$OLD_WT" --json
```

If any signal is ambiguous, preserve the old worktree. Reclaim means create a
new worktree with a new owner marker; it never means reset, clean, edit, or
delete the old one. Cleanup remains a separate helper-mediated action.

## 6. Completion Checklist

- Owner marker written before pytest starts.
- Exact main SHA and exact command captured.
- Timeout wrapper verified before the run.
- Output streamed to a non-empty log.
- Pipeline exit code preserved.
- Outcome classified without turning timeout-only evidence into test-red.
- Report written to worktree and shared `.aragora` locations before exit.
- Old or ambiguous worktrees left untouched.
- Any issue comment links to the durable report and is labeled diagnostic,
  not settlement evidence.

## Incident Note

During conductor cycles 150 and 151 on 2026-07-11, an exact-main first-error
process ended after creating a clean detached worktree but left no owner marker,
log, report, commit, or durable receipt. The next conductor could prove that
the process had stopped, but could not safely distinguish completed work from
abandoned work until a 90-second stability probe. This protocol closes that
coordination gap; it does not adjudicate the underlying main-health incident.
