# Merge Gate Reconciliation

**Status:** active
**Last updated:** 2026-05-21
**Purpose:** Align GitHub branch protection on `main` with the review authority
already defined in `docs/REVIEW_AUTHORITY_PRINCIPLES.md` and
`docs/briefs/automation-merge-contract.md`.

## Why this exists

The operator (`@an0mium`) authors essentially every PR, and `.github/CODEOWNERS`
routes every path to `@an0mium`. While branch protection required a human
approving review, no PR could ever satisfy that requirement honestly: an author
cannot approve their own PR, and using a second GitHub identity controlled by the
same person is a symbolic approval with no independent competence behind it —
explicitly disallowed by `REVIEW_AUTHORITY_PRINCIPLES.md`.

The repo already has the real reviewer: the heterogeneous model-review quorum,
plus the operator acting as accountable risk settler for Tier 3-4. The fix is to
make that quorum the enforced GitHub gate and to stop branch protection from
requiring a human `APPROVE` that cannot be produced honestly.

## The two workflows

| Workflow | Role | Can fail a PR? |
| --- | --- | --- |
| `aragora-review-gate.yml` ("Aragora Code Review") | Advisory — runs the model review, posts findings as a comment | No (kept advisory by `scripts/check_aragora_review_gate_policy.py`) |
| `aragora-merge-quorum.yml` ("aragora-merge-quorum") | Enforcing — required status check; builds the `merge-packet` and gates the merge | Yes |

`aragora-merge-quorum` is the GitHub-visible second reviewer. It is a status
check, not a bot `APPROVE` review.

## Target state for `main` branch protection

Required status checks (must pass before merge):

- the existing CI required checks — keep whatever is configured today
- `aragora-merge-quorum` — the new enforcing check

Require a pull request before merging: **keep ON.** Every change to `main` must
still go through a PR so the status checks apply. Do not remove this.

Required approvals: **0.** Remove the approving-review count and the "Require
review from Code Owners" requirement. The model quorum is the technical
reviewer; the operator's recorded risk settlement carries human accountability
for Tier 3-4.

Enforce on administrators: **ON.** Without this the enforcing check is theatre —
an admin (or admin-token automation) could merge past a red quorum check. For a
genuine "the gate itself is broken" emergency, toggle this off briefly; branch
protection changes are logged in the repo audit trail.

`.github/CODEOWNERS` may stay in the repo — it still requests reviewers and
documents ownership. It just must not be a *required* merge gate.

## Applying it (operator, repo admin)

The safest path is the GitHub UI, because it shows the full resulting state.
**Settings → Branches → Branch protection rules → `main`:**

1. Keep **Require a pull request before merging** checked.
2. Under it, set **Require approvals** to `0` (or uncheck it) and uncheck
   **Require review from Code Owners**.
3. Under **Require status checks to pass before merging**, add
   `aragora-merge-quorum` to the required list, alongside the existing CI
   checks. (This name only appears in the picker after the workflow has run
   once — see Rollout order below.)
4. Check **Do not allow bypassing the above settings** / **Include
   administrators**.
5. Save.

Equivalent `gh` commands for reference (run as a repo admin — then verify the
result in the UI). Apply them in the order shown: drop the review requirement
**before** enabling `enforce_admins`, so there is no window where administrators
are enforced while an unsatisfiable review requirement is still active.

```bash
# Set required approvals to 0 and drop CODEOWNERS gating,
# WITHOUT removing the "PR required" rule itself.
gh api --method PATCH \
  repos/synaptent/aragora/branches/main/protection/required_pull_request_reviews \
  -F required_approving_review_count=0 \
  -F require_code_owner_reviews=false

# Enforce branch protection on administrators.
gh api --method POST \
  repos/synaptent/aragora/branches/main/protection/enforce_admins

# Inspect current required status checks before changing them.
gh api repos/synaptent/aragora/branches/main/protection/required_status_checks
```

Add `aragora-merge-quorum` to the required status checks via the UI (step 3) —
it is safer than editing the status-check set through the API.

## Recording Tier 3-4 human settlement

Tier 0-2 PRs merge on the model quorum alone. Tier 3-4 PRs additionally require
a head-SHA-bound human settlement signal. The enforcing check fails closed until
that signal exists.

```bash
PR=<number>
HEAD_SHA=$(gh pr view "$PR" --repo synaptent/aragora --json headRefOid --jq .headRefOid)

# 1. Write the local, head-bound human-risk settlement receipt.
python -m aragora.cli.main review-queue record-settlement "$PR" \
  --head-sha "$HEAD_SHA" \
  --action approve \
  --reason "Operator risk settlement: <one-line authorization>"

# 2. Publish the GitHub-visible settlement signal on the exact head SHA.
gh api --method POST "repos/synaptent/aragora/statuses/$HEAD_SHA" \
  -f state=success \
  -f context=aragora/human-settlement \
  -f "description=Operator risk settlement recorded for PR #$PR"

# 3. Re-run the merge-quorum check so it observes the signal.
#    (Or: PR page -> Checks -> aragora-merge-quorum -> Re-run.)
#    When settlement is recorded with `scripts/settle_tier4_pr.py --settle-only`,
#    its "Tier-4 Human Settlement Authorization" comment triggers this rerun
#    automatically once the status above exists (B1.1,
#    docs/specs/QUORUM_EVIDENCE_RETRIGGER.md); the manual rerun below remains
#    the fallback for hand-posted settlements.
BRANCH=$(gh pr view "$PR" --repo synaptent/aragora --json headRefName --jq .headRefName)
RUN_ID=$(gh run list --repo synaptent/aragora \
  --workflow=aragora-merge-quorum.yml --branch "$BRANCH" \
  --limit 1 --json databaseId --jq '.[0].databaseId')
gh run rerun --repo synaptent/aragora "$RUN_ID"
```

Do not write an `admin_squash_merge` settlement receipt before GitHub reports
the PR as merged. After a successful exact-head admin squash merge, record the
post-merge receipt:

```bash
python -m aragora.cli.main review-queue record-settlement "$PR" \
  --head-sha "$HEAD_SHA" \
  --action admin_squash_merge \
  --reason "Exact-head admin squash completed after operator risk settlement"
```

If a new commit is pushed, the head SHA changes and the settlement signal no
longer applies — re-record settlement against the new head. This is
intentional: settlement is bound to the exact reviewed state.

The `aragora/human-settlement` status MUST be set by the operator, not by
pipeline automation. It represents the operator's accountable acceptance of
risk. Setting it from an automated agent re-creates exactly the
symbolic-approval problem this reconciliation removes. The local settlement
receipt (step 1) remains the stronger, `merge_arbiter`-enforced human-risk
record; the commit status is only its GitHub-visible projection. The
`admin_squash_merge` receipt is a post-merge audit record, not the pre-merge
human-risk signal.

## Rollout order

1. Merge the enforcing workflow `.github/workflows/aragora-merge-quorum.yml`.
   This is a Tier 4 change (workflow policy and merge-authority
   self-modification) and needs explicit operator preapproval before
   implementation and before merge.
2. Let the workflow run once on an open non-draft PR so GitHub registers the
   `aragora-merge-quorum` check name.
3. Apply the branch-protection changes above.
4. `auto_merge_bucket_a.py` is safe to leave as-is. It passes `gh pr merge
   --admin` only when `mergeStateStatus == BLOCKED`, which today is caused
   solely by the review requirement. Once that requirement is removed, Bucket A
   PRs (green checks) become `CLEAN` and the script merges them with a normal
   `gh pr merge --squash` — no `--admin`. Its `defense_in_depth_tripwire`
   already requires CI green independently, so `--admin` never bypassed checks,
   only the review gate. `enforce_admins: ON` therefore does not break it.
   Re-verify the boss-loop / `merge_arbiter` path separately if it has its own
   merge call.
5. Retire the second-identity approval path: stop using any non-author GitHub
   login to satisfy review, and remove the isolated `gh` config created for it.

## What this retires

The earlier approach of authorizing merges with a second GitHub identity
(`scarmani`, or any operator-controlled non-author login) is retired. It
contradicted `REVIEW_AUTHORITY_PRINCIPLES.md` ("does not authorize bot-only
GitHub approvals"; the independence factor) and produced an audit trail that
implied an independent human review that did not happen. The model quorum plus
recorded operator settlement replaces it with an honest, inspectable trail.

## Health note

An enforcing check is only meaningful if it can fail and sometimes does. Track
the `aragora-merge-quorum` block rate. If it has never blocked a PR, the tier
classification or the quorum thresholds are mis-tuned and the gate is not doing
real work. The model quorum is also only a *partial* independent reviewer —
`REVIEW_AUTHORITY_PRINCIPLES.md` notes these reviewers are not yet calibrated to
replace human risk settlement for escalated classes — so the integrity of the
whole gate depends on Tier 3-4 classification staying honest and the operator
staying genuinely engaged on those tiers.
