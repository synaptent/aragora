# Public Utility Mission Gated-File Audit

**Audit status:** **PASS-WITH-DISCLOSED-EXCEPTION.**

This audit found one merged mission pull request whose GitHub file manifest includes a gated
file: [PR #8957](https://github.com/synaptent/aragora/pull/8957) includes
`docs/CANONICAL_GOALS.md`. The patch only refreshes generated metric values, and the eventual
squash merge is an effective no-op because equivalent content had already reached `main`.
The strict manifest intersection is therefore exactly
{`docs/CANONICAL_GOALS.md` from PR #8957, adjudicated}, while the effective-delta
intersection is empty. The manifest touch remains disclosed rather than being silently converted
into a doctrine-prose-only check.

All other gated files are untouched at both the manifest and effective-delta levels. The README
top-line claim is byte-identical before and after the mission and across both merged mission pull
requests that touched `README.md`.

## 1. Snapshot and scope

| Item | Value |
|---|---|
| Audit date | 2026-07-11 |
| Pre-mission `origin/main` | `d780bd489808698ea20836f7b540f9301011f3c1` |
| Post-mission `origin/main` snapshot | `258fb97b821344e0f1e4fd597436108503e61759` |
| Post-mission merge | PR #9204, merged `2026-07-11T17:51:30Z` |
| Included pull requests | Every merged PR with a `factory/pum-` head through the post snapshot |
| Included PR count | 26 |
| Excluded work | Open or closed-unmerged mission PRs; unrelated PRs interleaved on `main` |

The pre-mission SHA is the baseline recorded by the mission's first committed baseline artifact,
[`PUBLIC_UTILITY_MISSION_BASELINE.md`](PUBLIC_UTILITY_MISSION_BASELINE.md). The post SHA is the
live `origin/main` snapshot at audit start. The deterministic PR inventory is bounded by the post
merge timestamp so rerunning the commands after this audit PR merges does not silently expand the
audited set.

### Gated paths

The full-file gates are:

```text
docs/THESIS.md
docs/CANONICAL_GOALS.md
docs/RECEIPT_CONTRACT.md
.github/workflows/**
aragora/gauntlet/odr_schema.json
aragora-verify/src/aragora_verify/odr_schema.json
```

`README.md` is not gated as a whole. Its gated surface is this top-line claim:

```markdown
**Aragora is an auditable execution control plane for AI-assisted decisions:
multi-model review in, a verifiable Decision Receipt out.**
```

## 2. Results

| Check | Result | Evidence |
|---|---|---|
| Per-PR GitHub file manifest, full-file gates | **PASS WITH DISCLOSED EXCEPTION** | 25/26 have no gated path; PR #8957 lists the single adjudicated `docs/CANONICAL_GOALS.md` exception |
| Union of GitHub PR file manifests | **PASS WITH DISCLOSED EXCEPTION** | Strict intersection is exactly {`docs/CANONICAL_GOALS.md` from PR #8957, adjudicated} |
| Per-PR effective squash-commit deltas | **PASS** | 26/26 effective deltas have no gated path |
| Union of effective squash-commit deltas | **PASS** | Empty intersection |
| README top-line claim, per README-touching PR | **PASS** | PRs #8955 and #8991 preserve the bytes |
| README top-line claim, pre/post snapshots | **PASS** | SHA-256 is `667fea0f1c04a36c5053fe521b0e77a36e43db54e8107a5944b1646294ddd122` at both endpoints |
| Both ODR schema copies, pre/post snapshots | **PASS** | Both remain byte-identical with SHA-256 `0d2a934981464d5835eb7d6651f8e6c21780e388100d0cd48828f0f75bb49411` |
| Overall result | **PASS-WITH-DISCLOSED-EXCEPTION** | Manifest intersection is the single adjudicated #8957 exception; effective-delta intersection is empty; all other gated files are untouched at both levels |

### Recorded exception

The exception is grounded in the repository-visible record for
[PR #8957](https://github.com/synaptent/aragora/pull/8957), not in a separate validation-contract
identifier. Its PR body limits the change to mechanical `doc_stats.py --write` metric-block
regeneration and records that protected files required operator review. The PR carried the
`operator-review-required` label, received two independent PASS comments, and was manually merged
by `an0mium` on `2026-07-07T17:01:39Z`. The resulting squash commit has an empty effective delta for
`docs/CANONICAL_GOALS.md`, as reproduced below.

For this audit, "modifies" is evaluated at both boundaries: the GitHub manifest touch remains a
disclosed exception, while the effective merged delta is empty. This document does not create a
general exemption for generated metrics or operator-reviewed changes. Any other gated-path touch,
or a non-empty effective delta for #8957, fails the audit.

### Why the PR manifest and effective merge results differ

PR #8957 was explicitly prepared as an operator-reviewed mechanical metrics regeneration. Its
GitHub patch changed four generated counts inside the metrics block in
`docs/CANONICAL_GOALS.md`:

- Python files: `4,260` to `4,262`
- lines of code: `1,975,628` to `1,976,521`
- test functions: `223,079` to `223,198`
- test files: `5,433` to `5,437`

The PR carried the `operator-review-required` label and two independent PASS comments. Before it
merged, equivalent content had already reached `main`. Consequently:

```text
PR head docs/CANONICAL_GOALS.md SHA-256:
bf963fde7c7abb7c4af2133990c6cbffebd679a5326453ddc1cb1cf4faf05a77

Merge parent docs/CANONICAL_GOALS.md SHA-256:
bf963fde7c7abb7c4af2133990c6cbffebd679a5326453ddc1cb1cf4faf05a77

Squash merge docs/CANONICAL_GOALS.md SHA-256:
bf963fde7c7abb7c4af2133990c6cbffebd679a5326453ddc1cb1cf4faf05a77
```

The squash commit `b60637ae2a3984bbeb7a9c93507c3a5527bd9151` therefore has an empty effective
tree delta. That protects the final repository state. It does not erase the PR-level gated-file
touch, which remains visible as the audit's single adjudicated exception.

### Endpoint hashes

| Gated artifact | Pre SHA-256 | Post SHA-256 | Equal |
|---|---|---|---|
| `docs/THESIS.md` | `c355f57ca164b965a9ecd6061adbe36586bb2bdc0de4fa2ddba96177cfa2bc68` | `c355f57ca164b965a9ecd6061adbe36586bb2bdc0de4fa2ddba96177cfa2bc68` | Yes |
| `docs/CANONICAL_GOALS.md` | `a12c57e30b79cb444920bffd0b87fcd6ea741a06e15ca750c8635ff05aef006b` | `af93890b8728ee812741211c7f11ec26906d107ec0d055b23b0902b674eb8f1c` | No |
| `docs/RECEIPT_CONTRACT.md` | `fc6e069a8eb5eb111ccaca4490ad50815a21f44b846ed3431f6437d4fb540ef3` | `fc6e069a8eb5eb111ccaca4490ad50815a21f44b846ed3431f6437d4fb540ef3` | Yes |
| `aragora/gauntlet/odr_schema.json` | `0d2a934981464d5835eb7d6651f8e6c21780e388100d0cd48828f0f75bb49411` | `0d2a934981464d5835eb7d6651f8e6c21780e388100d0cd48828f0f75bb49411` | Yes |
| `aragora-verify/src/aragora_verify/odr_schema.json` | `0d2a934981464d5835eb7d6651f8e6c21780e388100d0cd48828f0f75bb49411` | `0d2a934981464d5835eb7d6651f8e6c21780e388100d0cd48828f0f75bb49411` | Yes |

The `CANONICAL_GOALS.md` endpoint mismatch alone is not a mission attribution test. Unrelated PRs
were merged between the two snapshots, as were workflow changes. The mission-specific result comes
from the enumerated `factory/pum-*` PR manifests and effective commit deltas.

## 3. Per-PR ledger

`Manifest` checks the GitHub PR file list. `Effective` checks the final squash commit's tree delta.
`Top-line` is shown only for PRs that touched `README.md`.

| PR | Branch | Squash commit | Manifest | Effective | Top-line |
|---:|---|---|---|---|---|
| #8820 | `factory/pum-m2-receipt-reconciliation-doc` | `f2ba66b62499` | PASS | PASS | N/A |
| #8806 | `factory/pum-m0-baseline-map` | `19a85255c2f9` | PASS | PASS | N/A |
| #8829 | `factory/pum-m2-reconciliation-doc-pypi-claim-fix` | `2c6bfeda070d` | PASS | PASS | N/A |
| #8826 | `factory/pum-m2-odr-signed-and-chain-fixtures` | `d6158df3337e` | PASS | PASS | N/A |
| #8814 | `factory/pum-m1-pyproject-tagline-reframe` | `9e5aceec1596` | PASS | PASS | N/A |
| #8822 | `factory/pum-m2-odr-unsigned-state-fixtures` | `bfbbde4fa375` | PASS | PASS | N/A |
| #8832 | `factory/pum-m3-verifier-doc` | `d5ce2bb40178` | PASS | PASS | N/A |
| #8854 | `factory/pum-m3-verifier-hardening-tests` | `9001596cfc4c` | PASS | PASS | N/A |
| #8833 | `factory/pum-m3-pypi-status-corrections` | `535943bcf74d` | PASS | PASS | N/A |
| #8871 | `factory/pum-misc-odr-verify-docstring-honesty` | `5c37afdec1dc` | PASS | PASS | N/A |
| #8857 | `factory/pum-m3-receipt-verify-help-text` | `b014a6d52d1d` | PASS | PASS | N/A |
| #8870 | `factory/pum-misc-docsite-disaster-recovery-links` | `8531dfd43745` | PASS | PASS | N/A |
| #8953 | `factory/pum-misc-docsite-specs-mirror-boundary` | `8b600a3a8dbf` | PASS | PASS | N/A |
| #8955 | `factory/pum-m4-action-wedge-doc` | `7d4aebf68914` | PASS | PASS | PASS |
| #8957 | `factory/pum-misc-doc-stats-drift-fix` | `b60637ae2a39` | **ADJUDICATED EXCEPTION: `docs/CANONICAL_GOALS.md`** | PASS, empty commit delta | N/A |
| #8967 | `factory/pum-m5-install-matrix-doc` | `92af0c8df50f` | PASS | PASS | N/A |
| #8958 | `factory/pum-misc-specs-mirror-test-globbing` | `06c7f0f1b56e` | PASS | PASS | N/A |
| #8964 | `factory/pum-misc-action-doc-parity` | `5821f54592e3` | PASS | PASS | N/A |
| #8985 | `factory/pum-m5-install-matrix-pypi-regression-fix` | `b0797e2bf3c2` | PASS | PASS | N/A |
| #8991 | `factory/pum-m6-canonical-verbs-and-landing` | `77301f104408` | PASS | PASS | PASS |
| #9003 | `factory/pum-m6-canonical-consistency-sweep` | `2543ae8b42f6` | PASS | PASS | N/A |
| #9001 | `factory/pum-m6-docs-archive-collapse` | `2caed5d61fa0` | PASS | PASS | N/A |
| #9059 | `factory/pum-m6-user-testing-fixes` | `99a7a5cdd7e3` | PASS | PASS | N/A |
| #9067 | `factory/pum-misc-verify-tests-ruff-format` | `b67c139db339` | PASS | PASS | N/A |
| #9193 | `factory/pum-misc-mirror-guard-source-parity` | `a0f0c4179162` | PASS | PASS | N/A |
| #9204 | `factory/pum-m8-dogfood-gate` | `258fb97b8213` | PASS | PASS | N/A |

## 4. Reproduction commands

Run sections 4.1 through 4.4 in order from the same Bash shell in a checkout containing the post
snapshot. These commands require authenticated `gh`, `git`, `jq`, `awk`, `grep`, `paste`, `sort`,
and `shasum`. Section 4.1 creates one bounded snapshot of the PR inventory and each PR manifest;
the later sections reuse it. The manifest cache includes both `filename` and `previous_filename` so
a gated path renamed away cannot disappear from the audit.

GitHub's pull-request-files API returns at most 3,000 files for a pull request. The snapshot setup
compares every fetched manifest count with the PR's `changed_files` value and fails if they differ,
so an oversized or otherwise truncated manifest cannot be mistaken for complete evidence. None of
the 26 audited PRs reaches that limit.

### 4.1 Inventory the exact audited PR set

```bash
set -euo pipefail
POST_MERGED_AT=2026-07-11T17:51:30Z
EXPECTED_PR_COUNT=26
AUDIT_TMP=$(mktemp -d)
trap 'rm -rf "$AUDIT_TMP"' EXIT
PULLS_TSV="$AUDIT_TMP/pulls.tsv"

gh api --paginate \
  '/repos/synaptent/aragora/pulls?state=closed&per_page=100' \
  --jq '.[] |
    select(
      .merged_at != null and
      (.head.ref | startswith("factory/pum-")) and
      .merged_at <= "'"$POST_MERGED_AT"'"
    ) |
    [.merged_at, .number, .head.ref, .merge_commit_sha] | @tsv' |
  sort >"$PULLS_TSV"

actual_pr_count=$(wc -l <"$PULLS_TSV" | tr -d ' ')
if [ "$actual_pr_count" -ne "$EXPECTED_PR_COUNT" ]; then
  printf 'FAIL\tPR inventory\texpected=%s\tactual=%s\n' \
    "$EXPECTED_PR_COUNT" "$actual_pr_count" >&2
  exit 1
fi

while IFS=$'\t' read -r merged_at pr branch sha; do
  manifest="$AUDIT_TMP/pr-$pr-files.tsv"
  gh api --paginate \
    "/repos/synaptent/aragora/pulls/$pr/files?per_page=100" \
    --jq '.[] | [.filename, (.previous_filename // "")] | @tsv' >"$manifest"

  expected_files=$(gh api "/repos/synaptent/aragora/pulls/$pr" --jq '.changed_files')
  fetched_files=$(wc -l <"$manifest" | tr -d ' ')
  if [ "$fetched_files" -ne "$expected_files" ]; then
    printf 'FAIL\tPR #%s\tmanifest incomplete\texpected=%s\tfetched=%s\n' \
      "$pr" "$expected_files" "$fetched_files" >&2
    exit 1
  fi
done <"$PULLS_TSV"

cat "$PULLS_TSV"
```

Expected: 26 rows, from PR #8820 through PR #9204 by merge time.

### 4.2 Strict per-PR and aggregate manifest check

```bash
set -euo pipefail

is_gated='
  $0 == "docs/THESIS.md" ||
  $0 == "docs/CANONICAL_GOALS.md" ||
  $0 == "docs/RECEIPT_CONTRACT.md" ||
  $0 == "aragora/gauntlet/odr_schema.json" ||
  $0 == "aragora-verify/src/aragora_verify/odr_schema.json" ||
  index($0, ".github/workflows/") == 1
'

ALL_PATHS="$AUDIT_TMP/all-paths.txt"
: >"$ALL_PATHS"

while IFS=$'\t' read -r merged_at pr branch sha; do
  manifest="$AUDIT_TMP/pr-$pr-files.tsv"
  paths="$AUDIT_TMP/pr-$pr-paths.txt"
  awk -F '\t' '{ print $1; if ($2 != "") print $2 }' "$manifest" >"$paths"
  cat "$paths" >>"$ALL_PATHS"
  hits=$(awk "$is_gated" "$paths")

  if [ -z "$hits" ]; then
    printf 'PASS\tPR #%s\n' "$pr"
  elif [ "$pr" = 8957 ] && [ "$hits" = 'docs/CANONICAL_GOALS.md' ]; then
    printf 'EXCEPTION\tPR #%s\tdocs/CANONICAL_GOALS.md\n' "$pr"
  else
    printf 'FAIL\tPR #%s\t%s\n' "$pr" "$(printf '%s' "$hits" | paste -sd, -)"
    exit 1
  fi
done <"$PULLS_TSV"

aggregate_hits=$(sort -u "$ALL_PATHS" | awk "$is_gated")
if [ "$aggregate_hits" != 'docs/CANONICAL_GOALS.md' ]; then
  printf 'FAIL\taggregate manifest\texpected=docs/CANONICAL_GOALS.md\tactual=%s\n' \
    "$(printf '%s' "$aggregate_hits" | paste -sd, -)" >&2
  exit 1
fi
printf '%s\n' "$aggregate_hits"
```

Expected aggregate output:

```text
docs/CANONICAL_GOALS.md
```

### 4.3 Effective squash-commit union check

```bash
set -euo pipefail

while IFS=$'\t' read -r merged_at pr branch sha; do
  parent_count=$(git rev-list --parents -n 1 "$sha" | awk '{print NF - 1}')
  if [ "$parent_count" -ne 1 ]; then
    printf 'FAIL\t%s\tparent-count=%s\n' "$sha" "$parent_count" >&2
    exit 1
  fi
  git diff-tree --no-commit-id --name-only -r "$sha"
done <"$PULLS_TSV" |
  sort -u |
  awk '
    $0 == "docs/THESIS.md" ||
    $0 == "docs/CANONICAL_GOALS.md" ||
    $0 == "docs/RECEIPT_CONTRACT.md" ||
    $0 == "aragora/gauntlet/odr_schema.json" ||
    $0 == "aragora-verify/src/aragora_verify/odr_schema.json" ||
    index($0, ".github/workflows/") == 1
  '
```

Expected: no output and exit status 0. A merge commit with zero or multiple parents fails before
its paths can be mistaken for an empty effective delta.

### 4.4 README top-line claim check

```bash
set -euo pipefail

README_PRS=$(
  while IFS=$'\t' read -r merged_at pr branch sha; do
    manifest="$AUDIT_TMP/pr-$pr-files.tsv"
    if awk -F '\t' '$1 == "README.md" || $2 == "README.md" { found = 1 } END { exit !found }' \
      "$manifest"; then
      printf '%s\n' "$pr"
    fi
  done <"$PULLS_TSV"
)

actual_readme_prs=$(printf '%s\n' "$README_PRS" | sort -n | paste -sd, -)
if [ "$actual_readme_prs" != '8955,8991' ]; then
  printf 'FAIL\tREADME PR set\texpected=8955,8991\tactual=%s\n' \
    "$actual_readme_prs" >&2
  exit 1
fi

EXPECTED_CLAIM='**Aragora is an auditable execution control plane for AI-assisted decisions:
multi-model review in, a verifiable Decision Receipt out.**'

readme_claim_at() {
  git show "$1:README.md" |
    awk '
      /^\*\*Aragora is an auditable execution control plane for AI-assisted decisions:$/ {
        first = $0
        if (getline second) {
          print first "\n" second
        }
        exit
      }
    '
}

for pr in $README_PRS; do
  IFS=$'\t' read -r number branch sha < <(
    gh api "/repos/synaptent/aragora/pulls/$pr" \
      --jq '[.number, .head.ref, .merge_commit_sha] | @tsv'
  )
  before=$(readme_claim_at "$sha^")
  after=$(readme_claim_at "$sha")
  if [ "$before" = "$EXPECTED_CLAIM" ] && [ "$after" = "$EXPECTED_CLAIM" ]; then
    printf 'PASS\tPR #%s\t%s\n' "$pr" "$branch"
  else
    printf 'FAIL\tPR #%s\t%s\tclaim mismatch\n' "$pr" "$branch" >&2
    exit 1
  fi
done

for ref in \
  d780bd489808698ea20836f7b540f9301011f3c1 \
  258fb97b821344e0f1e4fd597436108503e61759
do
  claim=$(readme_claim_at "$ref")
  if [ "$claim" != "$EXPECTED_CLAIM" ]; then
    printf 'FAIL\t%s\tclaim mismatch\n' "$ref" >&2
    exit 1
  fi
  printf '%s\n' "$claim" | shasum -a 256
done
```

Expected: PRs #8955 and #8991 pass; both endpoint hashes are
`667fea0f1c04a36c5053fe521b0e77a36e43db54e8107a5944b1646294ddd122`.

### 4.5 Raw pre/post range, diagnostic only

```bash
git diff --name-only \
  d780bd489808698ea20836f7b540f9301011f3c1..\
258fb97b821344e0f1e4fd597436108503e61759 |
awk '
  $0 == "docs/THESIS.md" ||
  $0 == "docs/CANONICAL_GOALS.md" ||
  $0 == "docs/RECEIPT_CONTRACT.md" ||
  $0 == "aragora/gauntlet/odr_schema.json" ||
  $0 == "aragora-verify/src/aragora_verify/odr_schema.json" ||
  index($0, ".github/workflows/") == 1
'
```

This intentionally reports interleaved, unrelated changes:

```text
.github/workflows/aragora-merge-quorum.yml
.github/workflows/deploy-frontend.yml
.github/workflows/deploy-secure.yml
.github/workflows/lint.yml
.github/workflows/openapi.yml
.github/workflows/sdk-test.yml
docs/CANONICAL_GOALS.md
```

The raw range is useful as a drift diagnostic, but it cannot attribute those paths to this mission.
The PR manifest and enumerated squash-commit checks provide that attribution.

## 5. Contract disposition

| Assertion | Disposition |
|---|---|
| No mission-merged PR modifies a gated file | Satisfied with the recorded #8957 exception: the only manifest touch is `docs/CANONICAL_GOALS.md`, and its effective merged delta is empty |
| Full merged mission PR manifest union intersects empty | Satisfied under the recorded exception: strict manifest intersection is exactly {`docs/CANONICAL_GOALS.md` from PR #8957, adjudicated} |
| Effective merged squash-commit union intersects empty | Satisfied |
| README top-line claim unchanged | Satisfied |
| Audit artifact records commands and results | Satisfied by this document |
| Audit deliverable is docs-only | Satisfied by this audit branch |

The operator has adjudicated PR #8957's mechanical metrics-block touch as the single recorded
exception. The audit therefore passes with that manifest discrepancy disclosed, an empty effective
gated-path delta, and every other gated file untouched at both levels. A future pre-merge guard
should still check the GitHub PR file manifest, not only the effective commit delta, so an
eventually-empty squash cannot hide a protected-path touch.
