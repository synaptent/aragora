#!/usr/bin/env bash
# Shared deterministic rerun-target selection for the two Tier 4 quorum
# evidence-retrigger surfaces (docs/specs/QUORUM_EVIDENCE_RETRIGGER.md):
#
#   * the evidence-retrigger job in .github/workflows/aragora-merge-quorum.yml
#   * .github/workflows/aragora-merge-quorum-retrigger.yml (standalone helper)
#
# Both check this file out from the BASE repository's default branch and
# run it, so the selection semantics exist in exactly one place and the
# surfaces cannot drift apart (the PR #9754 incident class). Contract
# pinned by tests/governance/test_quorum_evidence_retrigger.py.
#
# Env contract: GH_TOKEN (read PR/run state + re-run workflow runs),
# GH_REPO (owner/repo), PR_NUMBER.
#
# The ONLY mutating action is the single rerun request at the end, on the
# newest surviving head-bound pull_request evaluation; every other path is
# a read followed by a no-op exit 0.
set -euo pipefail

: "${GH_REPO:?GH_REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"

# Same gate-deferral rule as the enforcing workflow: drafts and closed
# PRs have no active gate to refresh.
pr_json="$(gh api "repos/${GH_REPO}/pulls/${PR_NUMBER}")"
pr_state="$(jq -r '.state' <<<"$pr_json")"
pr_draft="$(jq -r '.draft' <<<"$pr_json")"
head_sha="$(jq -r '.head.sha' <<<"$pr_json")"
if [[ -z "$head_sha" || "$head_sha" == "null" ]]; then
  echo "::warning::could not resolve head SHA for PR #${PR_NUMBER}; nothing to do."
  exit 0
fi
if [[ "$pr_state" != "open" || "$pr_draft" != "false" ]]; then
  echo "PR #${PR_NUMBER} state=${pr_state} draft=${pr_draft} — gate not active; no-op."
  exit 0
fi
echo "PR #${PR_NUMBER} current head: ${head_sha}"

# Deterministically select the ONLY legitimate rerun target. A rerun
# re-executes the run's ORIGINAL frozen event payload, so re-running a
# draft-era evaluation replays its draft short-circuit SUCCESS over the
# truthful newest ready-state result, and falling back past a busy
# newest run re-executes exactly such a stale evaluation (PR #9754).
# So: enumerate ALL head-bound pull_request evaluations (full
# pagination, reconciled against total_count), drop runs created before
# the newest ready_for_review transition, order by ((run_started_at //
# created_at), run_id, run_attempt) — run_started_at is null while a
# run is still queued, and a null key must not sort the newest run
# below an older completed one — and consider ONLY the newest survivor.
# In-flight or green newest: no-op. Never fall back.
runs_url="repos/${GH_REPO}/actions/workflows/aragora-merge-quorum.yml/runs?event=pull_request&head_sha=${head_sha}"
total_count="$(gh api "${runs_url}&per_page=1" --jq '.total_count')"
runs_json="$(gh api --paginate "${runs_url}&per_page=100" \
  --jq '.workflow_runs[] | {id, run_attempt, status, conclusion, created_at, run_started_at}' \
  | jq -s '.')"
if [[ "$(jq 'length' <<<"$runs_json")" -ne "$total_count" ]]; then
  echo "::warning::head-bound run listing inconsistent with total_count=${total_count}; no-op."
  exit 0
fi
ready_at="$(gh api --paginate "repos/${GH_REPO}/issues/${PR_NUMBER}/events?per_page=100" \
  --jq '.[] | select(.event == "ready_for_review") | .created_at' | sort | tail -n1)"
target_json="$(jq -c --arg ready "${ready_at}" \
  '[.[] | select(($ready == "") or (.created_at >= $ready))]
   | sort_by((.run_started_at // .created_at), .id, .run_attempt) | last // empty' <<<"$runs_json")"
if [[ -z "$target_json" ]]; then
  echo "No non-draft head-bound evaluation run for ${head_sha} — no-op."
  exit 0
fi
run_id="$(jq -r '.id' <<<"$target_json")"
run_status="$(jq -r '.status' <<<"$target_json")"
run_conclusion="$(jq -r '.conclusion' <<<"$target_json")"
if [[ "$run_status" != "completed" ]]; then
  echo "Newest non-draft evaluation run ${run_id} is ${run_status} — it will already see the current evidence; no-op."
  exit 0
fi
if [[ "$run_conclusion" == "success" ]]; then
  echo "Newest non-draft evaluation run ${run_id} already succeeded — no-op."
  exit 0
fi

# Every retrigger surface computes this same target, so a fresh status
# read immediately before the request collapses a comment burst into
# ONE rerun: losers see a non-completed run and no-op.
fresh_status="$(gh api "repos/${GH_REPO}/actions/runs/${run_id}" --jq '.status')"
if [[ "$fresh_status" != "completed" ]]; then
  echo "Evaluation run ${run_id} is already ${fresh_status} (concurrent retrigger won) — no-op."
  exit 0
fi
echo "Re-running stale evaluation run ${run_id} (conclusion=${run_conclusion}) for PR #${PR_NUMBER} head ${head_sha}."
# A rejected rerun (already re-running) must not turn comment activity
# into red noise; the A1 reconciler remains the safety net.
gh run rerun "$run_id" --repo "$GH_REPO" \
  || echo "::warning::rerun request for run ${run_id} failed (possibly already re-running); no-op."
