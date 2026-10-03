# Main-Green Re-Arm Evidence

Use this runbook after `.aragora/merge_executor.halt` has stopped merges because
`origin/main` was classified red. The halt marker is a durable stop signal, not
a live health probe: its recorded SHA may be older than current main, and a fix
landing on main is not by itself proof that every required and full-suite path
is green.

This procedure produces an exact-head evidence packet for a human re-arm
decision. Automated agents may collect the evidence, but they must not delete,
replace, or work around the halt marker.

## Preconditions

1. Work from the canonical checkout whose `.aragora` directory is used by the
   merge executor. Do not use a session worktree's local halt path as a proxy.
2. Keep the halt marker in place while collecting evidence.
3. Use `--no-halt-file` for every diagnostic run. A diagnostic must not rewrite
   an existing incident record.
4. Treat a missing, broken, or below-floor test tool as an infrastructure
   failure, not as evidence that the repository is red.
5. Require the required suite and full suite to test the same `origin/main`
   SHA. If main moves between them, discard the pair and rerun both.

Set the paths once from the canonical checkout:

```bash
REPO_ROOT="$(git rev-parse --show-toplevel)"
cd -- "$REPO_ROOT"
HALT_FILE="$REPO_ROOT/.aragora/merge_executor.halt"
PRISTINE_DIR="$HOME/.aragora/pristine-main"
```

Record the incident marker before doing anything else:

```bash
test -f "$HALT_FILE"
HALT_SHA256="$(shasum -a 256 "$HALT_FILE" | awk '{print $1}')"
cat "$HALT_FILE"
printf 'halt_sha256=%s\n' "$HALT_SHA256"
```

The marker's `details` explain why the halt was armed. They do not establish
the health of a newer main head.

## 1. Pin The Candidate Head

Fetch with an explicit refspec, then record the full SHA:

```bash
git fetch origin +refs/heads/main:refs/remotes/origin/main
CANDIDATE_SHA="$(git rev-parse origin/main)"
git show --no-patch --format='%H%n%aI%n%s' "$CANDIDATE_SHA"
```

All later evidence must name `CANDIDATE_SHA`. Do not report only a branch name
or a short SHA.

## 2. Prove The Toolchain

`make ci-required` resolves `mypy` from `PATH`. The declared development
dependency currently requires `mypy>=2.1.0,<3.0`; a PATH installation such as
1.19.1 is not a valid required-suite runner even if it can execute.

Capture the interpreter and executable identities:

```bash
python3 --version
python3 -c 'import sys, pytest; print(sys.executable); print(pytest.__version__)'
command -v mypy
mypy --version
jq --version
gh --version | head -n 1
git show "${CANDIDATE_SHA}:pyproject.toml" | grep -nE '"mypy[<>=]'
```

Classify any of these outcomes as `infra_error` and stop before running the
suites:

- `pytest` cannot be imported by the interpreter that will launch the full
  suite;
- `mypy` is absent from `PATH`, cannot launch, or its version cannot be parsed;
- PATH `mypy` is below the declared lower bound or outside the declared range;
- `jq` is older than 1.7 or `gh` is older than 2.40 for the hosted-policy
  collection commands below;
- the pristine worktree cannot be fetched, created, or safely refreshed;
- a command times out or cannot be launched.

PR #9175 adds this classification to `scripts/pristine_main_health.py`. Until
that exact behavior is present on `CANDIDATE_SHA`, enforce the preflight above
manually. Never interpret a known-invalid toolchain's nonzero result as a new
repository failure.

## 3. Run Required And Full Proofs

Run both suites in report-only mode. Preserve complete stdout, stderr, exit
code, start time, and end time in an operator-owned evidence directory outside
the repository.

```bash
EVIDENCE_PARENT="${TMPDIR:-/tmp}"
EVIDENCE_DIR="$(
  umask 077
  mktemp -d "${EVIDENCE_PARENT%/}/aragora-main-green-${CANDIDATE_SHA}.XXXXXX"
)"

python3 scripts/pristine_main_health.py \
  --repo-root "$REPO_ROOT" \
  --pristine-dir "$PRISTINE_DIR" \
  --halt-file "$HALT_FILE" \
  --suite required \
  --no-halt-file \
  --timeout-minutes 30 \
  >"$EVIDENCE_DIR/required.stdout" \
  2>"$EVIDENCE_DIR/required.stderr"
REQUIRED_EXIT=$?

if [ "$REQUIRED_EXIT" -eq 0 ]; then
  python3 scripts/pristine_main_health.py \
    --repo-root "$REPO_ROOT" \
    --pristine-dir "$PRISTINE_DIR" \
    --halt-file "$HALT_FILE" \
    --suite full \
    --no-halt-file \
    --timeout-minutes 180 \
    >"$EVIDENCE_DIR/full.stdout" \
    2>"$EVIDENCE_DIR/full.stderr"
  FULL_EXIT=$?
else
  FULL_EXIT=not_run
  printf 'full suite not run: required suite exited %s\n' "$REQUIRED_EXIT" \
    >"$EVIDENCE_DIR/full.stdout"
  : >"$EVIDENCE_DIR/full.stderr"
fi

printf 'required_exit=%s\nfull_exit=%s\n' "$REQUIRED_EXIT" "$FULL_EXIT"
```

The proof is green only when both exit codes are zero and both stdout files
report the same 12-character prefix of `CANDIDATE_SHA`; the later full-SHA
guard binds that prefix to the unchanged remote head. A failing
`make ci-required` is a real repository failure only after the toolchain
preflight succeeds. For example, known mypy campaign debt tracked by issue
#9099 remains a real required-suite failure; it is not made green by a passing
focused test or by a draft repair.

Hash the captured evidence:

```bash
shasum -a 256 \
  "$EVIDENCE_DIR/required.stdout" \
  "$EVIDENCE_DIR/required.stderr" \
  "$EVIDENCE_DIR/full.stdout" \
  "$EVIDENCE_DIR/full.stderr"
```

## 4. Recheck Head And Hosted Gates

The local pair is invalid if main moved during collection:

```bash
CANDIDATE_SHA="$CANDIDATE_SHA" sh -eu <<'HEAD_RECHECK'
git fetch origin +refs/heads/main:refs/remotes/origin/main
actual_sha="$(git rev-parse origin/main)"
if [ "$actual_sha" != "$CANDIDATE_SHA" ]; then
  printf 'HEAD DRIFT: expected %s, observed %s; discard the evidence pair\n' \
    "$CANDIDATE_SHA" "$actual_sha" >&2
  exit 1
fi
HEAD_RECHECK
```

Also capture both applicable ruleset and branch-protection policy, every page
of check runs, and every page of legacy commit statuses for the same SHA. The
required set is the union of both policy sources; failure to read either source
is `evidence_incomplete`, never an empty-policy success. Preserve each
app-bound requirement's integration or app ID; a same-named run from another
GitHub App is not proof for that requirement. Treat a branch-protection name in
`.contexts` as legacy only when neither source binds that name to an app. An
unbound ruleset context may be satisfied by either a Check Run or a legacy
commit status; if both surfaces report the context and disagree, fail closed.
Select matching check runs by their numeric creation-ordered ID so a newer
queued run with no `started_at` cannot be hidden by an older success; a missing
or nonnumeric ID fails closed:

Run the collection in a disposable shell so a failed API read terminates this
evidence pass without exiting the operator's interactive shell:

```bash
CANDIDATE_SHA="$CANDIDATE_SHA" EVIDENCE_DIR="$EVIDENCE_DIR" \
  sh -eu <<'REQUIRED_CONTEXT_EVIDENCE'
RULESET_REQUIRED_RAW="$(
  gh api --paginate --slurp \
    "repos/synaptent/aragora/rules/branches/main?per_page=100"
)" || exit 1
RULESET_REQUIRED_JSON="$(
  printf '%s\n' "$RULESET_REQUIRED_RAW" \
    | jq -e '
      if type != "array" or any(.[]; type != "array") then
        error("ruleset pagination response is not an array of pages")
      elif any(.[][]; type != "object") then
        error("ruleset response contains a non-object rule")
      elif any(
        .[][] | select(.type == "required_status_checks");
        ((.parameters | type) != "object")
        or ((.parameters.required_status_checks | type) != "array")
      ) then
        error("required_status_checks rule has an invalid parameters schema")
      elif any(
        .[][]
        | select(.type == "required_status_checks")
        | .parameters.required_status_checks[];
        (type != "object")
        or (((.context // .name) | type) != "string")
        or (((.context // .name) | length) == 0)
      ) then
        error("required_status_checks contains an invalid requirement")
      else
        [
          .[][]
          | select(.type == "required_status_checks")
          | .parameters.required_status_checks[]
          | {
              context: (.context // .name),
              app_id: (.integration_id // .app_id // null)
            }
        ]
      end
    '
)" || exit 1
BRANCH_PROTECTION_REQUIRED_RAW="$(
  gh api repos/synaptent/aragora/branches/main/protection/required_status_checks
)" || exit 1
BRANCH_PROTECTION_REQUIRED_JSON="$(
  printf '%s\n' "$BRANCH_PROTECTION_REQUIRED_RAW" \
    | jq -e '
      if type != "object"
        or (.checks | type) != "array"
        or (.contexts | type) != "array"
      then
        error("branch-protection response is missing checks or contexts")
      elif any(.checks[];
        type != "object"
        or (.context | type) != "string"
        or (.context | length) == 0
        or (
          .app_id != null
          and .app_id != -1
          and (.app_id | type) != "number"
        )
      ) then
        error("branch-protection checks contain an invalid requirement")
      elif any(.contexts[]; type != "string" or length == 0) then
        error("branch-protection contexts contain an invalid name")
      else
        {
          checks: [.checks[] | {context, app_id}],
          legacy_contexts: (
            [.contexts[]] - [.checks[].context] | unique
          )
        }
      end
    '
)" || exit 1
REQUIRED_POLICY_JSON="$(
  jq -n \
    --argjson ruleset "$RULESET_REQUIRED_JSON" \
    --argjson protection "$BRANCH_PROTECTION_REQUIRED_JSON" \
    '{
      checks: (
        (
          [$ruleset[]
            | select(.app_id != null and .app_id != -1)
            | {context, app_id, source: "ruleset"}
          ]
          + [$protection.checks[]
            | select(.app_id != null and .app_id != -1)
            | {context, app_id, source: "branch_protection"}
          ]
        )
        | map(select(
            (.context | type) == "string"
            and (.context | length > 0)
          ))
        | sort_by(.context, .app_id, .source)
        | group_by([.context, .app_id])
        | map({
            context: .[0].context,
            app_id: .[0].app_id,
            sources: (map(.source) | unique)
          })
      ),
      status_or_checks: (
        (
          [$ruleset[]
            | select(.app_id == null or .app_id == -1)
            | select(
                (.context | type) == "string"
                and (.context | length > 0)
              )
            | {context, source: "ruleset"}
          ]
          + [$protection.checks[]
            | select(.app_id == null or .app_id == -1)
            | select(
                (.context | type) == "string"
                and (.context | length > 0)
              )
            | {context, source: "branch_protection"}
          ]
        )
        | sort_by(.context, .source)
        | group_by(.context)
        | map({
            context: .[0].context,
            sources: (map(.source) | unique)
          })
      ),
      legacy_contexts: (
        $protection.legacy_contexts
        - [$ruleset[].context]
        - [$protection.checks[].context]
        | unique
      )
    }'
)" || exit 1
CHECK_RUNS_RAW="$(
  gh api --paginate --slurp \
    "repos/synaptent/aragora/commits/$CANDIDATE_SHA/check-runs?filter=latest&per_page=100"
)" || exit 1
CHECK_RUNS_JSON="$(
  printf '%s\n' "$CHECK_RUNS_RAW" \
    | jq -e '
      if type != "array"
        or any(.[]; type != "object" or (.check_runs | type) != "array")
      then
        error("check-run pagination response has an invalid page schema")
      elif any(.[].check_runs[];
        type != "object"
        or (.id | type) != "number"
        or (.name | type) != "string"
        or (.name | length) == 0
        or (.app | type) != "object"
        or (.app.id | type) != "number"
        or (.status | type) != "string"
        or (
          .conclusion != null
          and (.conclusion | type) != "string"
        )
      ) then
        error("check-run response contains an invalid run")
      else
        [.[].check_runs[] | {
          id,
          name,
          app_id: .app.id,
          status,
          conclusion,
          details_url,
          started_at,
          completed_at
        }]
      end
    '
)" || exit 1
COMMIT_STATUSES_RAW="$(
  gh api --paginate --slurp \
    "repos/synaptent/aragora/commits/$CANDIDATE_SHA/statuses?per_page=100"
)" || exit 1
COMMIT_STATUSES_JSON="$(
  printf '%s\n' "$COMMIT_STATUSES_RAW" \
    | jq -e '
      if type != "array" or any(.[]; type != "array") then
        error("commit-status pagination response is not an array of pages")
      elif any(.[][];
        type != "object"
        or (.id | type) != "number"
        or (.context | type) != "string"
        or (.context | length) == 0
        or (.state | type) != "string"
      ) then
        error("commit-status response contains an invalid status")
      else
        [.[][] | {
          id,
          context,
          state,
          target_url,
          creator: (.creator.login // null),
          updated_at
        }]
      end
    '
)" || exit 1

jq -n \
  --argjson policy "$REQUIRED_POLICY_JSON" \
  --argjson runs "$CHECK_RUNS_JSON" \
  --argjson statuses "$COMMIT_STATUSES_JSON" \
  '{
    policy_requirement_count: (
      ($policy.checks | length)
      + ($policy.status_or_checks | length)
      + ($policy.legacy_contexts | length)
    ),
    checks: [
      $policy.checks[] as $requirement
      | [$runs[] | select(
          .name == $requirement.context
          and (
            $requirement.app_id == null
            or $requirement.app_id == -1
            or .app_id == $requirement.app_id
          )
        )] as $matches
      | {
          kind: "check_run",
          context: $requirement.context,
          app_id: $requirement.app_id,
          sources: $requirement.sources,
          expected_skip: ($requirement.context == "aragora-merge-quorum"),
          found: ($matches | length > 0),
          latest: (
            if any($matches[]; (.id | type) != "number")
            then null
            else ($matches | max_by(.id))
            end
          )
        }
    ],
    status_or_checks: [
      $policy.status_or_checks[] as $requirement
      | [$runs[] | select(.name == $requirement.context)] as $check_matches
      | [$statuses[] | select(.context == $requirement.context)] as $status_matches
      | any($check_matches[]; (.id | type) != "number") as $invalid_check_proof
      | any($status_matches[];
          (.id | type) != "number"
        ) as $invalid_status_proof
      | (
          if $invalid_check_proof
          then null
          else ($check_matches | max_by(.id))
          end
        ) as $latest_check
      | (
          if $invalid_status_proof
          then null
          else ($status_matches | max_by(.id))
          end
        ) as $latest_status
      | (
          $latest_check != null
          and $latest_check.status == "completed"
          and (
            $latest_check.conclusion == "success"
            or (
              $requirement.context == "aragora-merge-quorum"
              and $latest_check.conclusion == "skipped"
            )
          )
        ) as $check_green
      | (
          $latest_status != null
          and $latest_status.state == "success"
        ) as $status_green
      | (
          $latest_check != null
          and $latest_status != null
          and $check_green != $status_green
        ) as $conflict
      | {
          kind: "status_or_check",
          context: $requirement.context,
          sources: $requirement.sources,
          expected_skip: ($requirement.context == "aragora-merge-quorum"),
          found: ($latest_check != null or $latest_status != null),
          latest_check: $latest_check,
          latest_status: $latest_status,
          proof_complete: (($invalid_check_proof or $invalid_status_proof) | not),
          conflict: $conflict,
          satisfied: (
            ($check_green or $status_green)
            and ($conflict | not)
            and (($invalid_check_proof or $invalid_status_proof) | not)
          )
        }
    ],
    statuses: [
      $policy.legacy_contexts[] as $context
      | [$statuses[] | select(.context == $context)] as $matches
      | {
          kind: "commit_status",
          context: $context,
          found: ($matches | length > 0),
          latest: (
            if any($matches[];
              (.id | type) != "number"
            )
            then null
            else ($matches | max_by(.id))
            end
          )
        }
    ]
  }' \
  | tee "$EVIDENCE_DIR/required-contexts.json"

jq -e \
  '.policy_requirement_count > 0
    and all(.checks[];
      .found
      and .latest.status == "completed"
      and (
        .latest.conclusion == "success"
        or (.expected_skip and .latest.conclusion == "skipped")
      )
    )
    and all(.status_or_checks[];
      .found
      and .proof_complete
      and (.conflict | not)
      and .satisfied
    )
    and all(.statuses[]; .found and .latest.state == "success")' \
  "$EVIDENCE_DIR/required-contexts.json"
REQUIRED_CONTEXT_EVIDENCE
```

Inspect every row in all three requirement arrays in `required-contexts.json`.
A missing
ruleset or branch-protection policy response, missing app-bound check, app-id
mismatch, missing unbound context proof, conflicting status/check result,
empty normalized policy, or missing legacy status is `evidence_incomplete`. A main-applicable
required check whose latest run did not complete successfully, or a required
legacy status whose latest state is not `success`, is `main_red`; a check
designed to skip on main (currently `aragora-merge-quorum`) must remain visible
with `expected_skip: true` and be identified as an expected main-only skip in
the packet rather than silently treated as green. The expected-skip identity is
currently keyed by the literal context name, so update this runbook if the
quorum context is renamed. The commit-status payload does not expose a GitHub
App ID; if an app-bound requirement is reported only through commit statuses,
this collector cannot attribute it and must classify the result
`evidence_incomplete`. This procedure currently requires both the ruleset and
classic branch-protection policy responses. If the repository migrates to
rulesets-only protection and the classic endpoint returns 404, stop with
`evidence_incomplete` and revise this collector with a separately reviewed
proof of non-applicability; never substitute an empty classic policy. An API
outage, pagination failure, rate limit, or schema mismatch is also
`evidence_incomplete`, not green. Retry in a later bounded cycle; do not
substitute old PR checks for current-main checks.

## 5. Build The Human Packet

The re-arm packet must contain:

- full `CANDIDATE_SHA`, commit time, and subject;
- halt-marker body and its pre-run SHA-256;
- Python, pytest, PATH mypy path/version, and declared mypy requirement;
- exact required/full commands, exit codes, timestamps, and log hashes;
- proof that both suites tested the same SHA;
- all branch-protection required contexts and their current-main check URLs;
- the start and end of the observed green interval;
- every anomaly, retry, skipped surface, or unavailable evidence source;
- an explicit statement that no baseline, workflow, branch protection,
  settlement, or halt mutation was used to obtain green.

Use one of these terminal classifications:

| Classification | Meaning | Action |
| --- | --- | --- |
| `main_green_candidate` | Toolchain valid; both local suites and hosted required contexts pass at one unchanged SHA | Ask a human for exact-head re-arm review |
| `main_red` | Toolchain valid; at least one repository check fails | Keep the halt; file or update one exact-head incident |
| `infra_error` | Runner, dependency, launch, timeout, fetch, or worktree failure | Keep the halt; repair infrastructure and rerun |
| `evidence_incomplete` | Head drift, API outage, missing logs, or unmatched SHA | Keep the halt; collect a complete pair later |

## 6. Human Re-Arm Only

The operating contract requires main to remain green for at least one hour
unless the user explicitly waives that interval. A human must review the
packet and authorize the exact `CANDIDATE_SHA`; generic continuation text is
not exact-head re-arm authority.

Immediately before human deletion, run the guards and deletion through one
non-interactive fail-closed shell command. Do not extract or paste individual
lines from its quoted program:

```bash
sh -euc '
  halt_file=$1
  halt_sha256=$2
  repo_root=$3
  candidate_sha=$4
  actual_halt_sha256=$(shasum -a 256 "$halt_file")
  test "${actual_halt_sha256%% *}" = "$halt_sha256"
  git -C "$repo_root" fetch origin +refs/heads/main:refs/remotes/origin/main
  test "$(git -C "$repo_root" rev-parse origin/main)" = "$candidate_sha"
  actual_halt_sha256=$(shasum -a 256 "$halt_file")
  test "${actual_halt_sha256%% *}" = "$halt_sha256"
  rm -- "$halt_file"
  test ! -e "$halt_file"
' sh "$HALT_FILE" "$HALT_SHA256" "$REPO_ROOT" "$CANDIDATE_SHA"
```

If either guard fails, preserve the marker and rebuild the packet. Re-arming
does not itself authorize a PR merge, settlement, CI rerun, workflow dispatch,
or branch-protection change; those actions retain their normal gates.
