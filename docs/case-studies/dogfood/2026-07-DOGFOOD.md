# M8 Dogfood Report: CI Review Gate on Real Aragora PRs

> **Date:** 2026-07-10
> **Feature:** m8-dogfood-gate
> **Milestone:** M8 — Dogfood the CI Review Gate
> **Spend ledger:** [`spend-ledger.json`](spend-ledger.json) (M8 sub-total: ~$0.23 of $100 cap)

## Executive Summary

We dogfooded the Aragora CI review gate on **5 recent real `synaptent/aragora` PRs** using a
heterogeneous quorum of **2 reachable provider families** (xAI/Grok + Mistral). Each PR received
genuine, independent multi-model reviews, and every review produced a verifiable
Open Decision Receipt (ODR) artifact. All 5 receipts independently verify with
`aragora-verify` at **exit 0** (schema_conformance=pass, quorum_consistency=pass).

The quorum produced genuine model findings and dissent on 3 PRs (grok blocked where mistral
passed, or both blocked), and honestly recorded 2 PRs as clean passes. However, after
independent exact-head verification, **zero model findings were confirmed as real defects** —
the headline PR #9030 "catch" (a `None`-return type-contract violation) is a model false
positive disproven by the reviewed code (the caller guards `None` via a truthiness check
before iterating). This is an honest result: a 2-family quorum that flags risks but whose
flags did not correspond to confirmed defects on this PR slice. Limitations are documented
below, not hidden, and each named gap links a follow-up issue.

## Provider Selection

Per mission constraints, ANTHROPIC, OPENAI, and DeepSeek keys are absent. We confirmed
connectivity with a tiny probe call before batch runs:

| Family | Agent Type | API Key Env | Status |
|--------|-----------|-------------|--------|
| xAI/Grok | `grok` | `XAI_API_KEY` | **Connected** (grok-4-latest) |
| Mistral | `mistral-api` | `MISTRAL_API_KEY` | **Connected** (mistral-large-2512) |
| Gemini | `gemini` | `GEMINI_API_KEY` | **Failed** — key invalid (HTTP 400) |
| OpenRouter | `mistral` (OpenRouter transport) | `OPENROUTER_API_KEY` | **Failed** — placeholder key (HTTP 401) |

The heterogeneous quorum uses **xAI and Mistral** — 2 distinct model families, both reachable,
neither mapping to the absent set (Anthropic/OpenAI/DeepSeek). This satisfies the
`distinct_model_families >= 2` requirement. A 3rd family (Gemini) was attempted but its API key
is expired/invalid; this is recorded as a limitation, not hidden.

> **Note on `collect_quorum_evidence.py`:** The Action's standard evidence collector
> (`scripts/collect_quorum_evidence.py`) routes the "mistral" family through an OpenRouter
> transport agent, which failed due to the broken OpenRouter key. To use the direct Mistral API
> (`mistral-api` agent type with `MISTRAL_API_KEY`), the original live run invoked
> `aragora.agents.create_agent("grok")` and `create_agent("mistral-api")` directly. The raw
> reviewer outputs from that live run are committed as fixtures
> (`raw-reviews/pr-<N>-reviewers.json`), and the ODR receipts are regenerated from them through
> the canonical `collect_outcome_to_decision_receipt` + `decision_receipt_to_odr` pipeline
> (the same transform `scripts/emit_pr_receipt.py` uses) by the committed offline replay driver
> [`replay_dogfood_receipts.py`](replay_dogfood_receipts.py). No merge-authority, quorum,
> settle, or receipt-pipeline code was modified.

## PR Selection

5 recent merged PRs representing a mix of test code, feature code, and bug fixes:

| PR | Title | Size | Type |
|----|-------|------|------|
| [#9193](https://github.com/synaptent/aragora/pull/9193) | tests(scripts): harden docs-site fallback mirror guard | 207+33, 1 file | Test |
| [#9062](https://github.com/synaptent/aragora/pull/9062) | feat(scripts): add OpenRouter fallback for Fable goal cycles | 371+18, 4 files | Feature |
| [#9030](https://github.com/synaptent/aragora/pull/9030) | fix(routing): handle empty LLM domain responses | 21+9, 2 files | Bug fix |
| [#9056](https://github.com/synaptent/aragora/pull/9056) | feat(swarm): wire PR-keyed round budget into A1 reconciler | 285+6, 4 files | Feature |
| [#9027](https://github.com/synaptent/aragora/pull/9027) | fix(scripts): accept operator-context dir in goal-cycle context | 27+8, 2 files | Bug fix |

Diffs were fetched via `gh pr diff <n> --repo synaptent/aragora` and reviewed at the PR's
merged head SHA.

## Results: Per-PR Review Table

| PR | Grok (xai) | Mistral (mistral) | Quorum Verdict | Dissent | Receipt |
|----|-----------|-------------------|----------------|---------|---------|
| #9193 | CHANGES_REQUESTED (3x P2) | PASS (1x P3) | CHANGES_REQUESTED | Yes (grok) | [receipt](pr-9193-receipt.odr.json) |
| #9062 | CHANGES_REQUESTED (2x P2, 1x P3) | PASS (3x P3) | CHANGES_REQUESTED | Yes (grok) | [receipt](pr-9062-receipt.odr.json) |
| #9030 | CHANGES_REQUESTED (2x P2) | CHANGES_REQUESTED (1x P1, 1x P2, 1x P3) | CHANGES_REQUESTED | No (unanimous block) | [receipt](pr-9030-receipt.odr.json) |
| #9056 | PASS (no findings) | PASS (1x P2) | PASS | No (unanimous pass) | [receipt](pr-9056-receipt.odr.json) |
| #9027 | PASS (no findings) | PASS (1x P2) | PASS | No (unanimous pass) | [receipt](pr-9027-receipt.odr.json) |

All receipts are **UNSIGNED** (`signatures: []`), which is the current shipping state — no ODR
signing path is wired in the Action. `aragora-verify` reports `signature=warn` (not fail) on
unsigned receipts. Authenticity is **UNVERIFIED** (no cryptographic signature). Each receipt's
authenticity state is disclosed here and in the `--json` output.

## Receipt Verification

Every receipt independently verified with `aragora-verify`:

```
$ aragora-verify <receipt>.odr.json --json
```

| Receipt | Exit Code | schema_conformance | quorum_consistency | signature | Warnings |
|---------|-----------|-------------------|-------------------|-----------|----------|
| pr-9193 | 0 | pass | pass | warn (unsigned) | attestation: autonomous |
| pr-9062 | 0 | pass | pass | warn (unsigned) | attestation: autonomous |
| pr-9030 | 0 | pass | pass | warn (unsigned) | attestation: autonomous |
| pr-9056 | 0 | pass | pass | warn (unsigned) | attestation: autonomous |
| pr-9027 | 0 | pass | pass | warn (unsigned) | attestation: autonomous |

### ODR field conformance (per validation contract)

Each receipt satisfies:
- **>=2 quorum.participants**: 2 participants (grok, mistral) per receipt
- **quorum.independence.disclosed = true**: yes, with `distinct_model_families = 2`
- **model_families**: `["mistral", "xai"]` — both reachable, none in {Anthropic, OpenAI, DeepSeek}
- **structured dissent**: present with >=1 view (PRs #9193, #9062, #9030) or explicitly `false` (PRs #9056, #9027)
- **claim.verdict**: `PASS` or `CHANGES_REQUESTED` — both in the documented verdict set
- **subject.identifier**: `merge-quorum/synaptent/aragora#<N>` — binds the real PR
- **subject.digest.status = present** (sha-256): yes, derived from `sha256("synaptent/aragora#<N>@<head_sha>")`

## Honest Report: Catches / Misses / Blocked / Couldn't-Decide

### Model Findings (not independently confirmed as real defects)

Per the **exact-head defect rule**, no model finding is classified as a "real catch"
unless it is independently confirmed against the reviewed PR's exact head. After
exact-head verification, **zero model findings were confirmed as real defects** on
this PR slice. All flagged items are recorded below as model findings, with the
exact-head analysis for each.

1. **PR #9030 — `None`-return type contract violation (P1/P2, unanimous) — MODEL FALSE
   POSITIVE:**
   Both models flagged that `_detect_with_llm` returns `None` on empty content, claiming
   the caller `detect()` "will crash when it tries to iterate over `None`." Exact-head
   analysis of `aragora/routing/domain_matcher.py` at head `6fe6ad588f4c` disproves this:
   the caller guards the return value with `if llm_result:` (a truthiness check) before
   any iteration, and falls back to `_detect_with_keywords()` when the result is `None`
   or empty. The return type already permitted `None` (the exception handler and
   no-valid-domains paths both returned `None` before this PR), and the PR's own test
   `test_llm_detection_empty_response_fallback` confirms the fallback works. This is a
   confirmed model false positive, not a real catch.

2. **PR #9062 — Timeout calculation ignores `api_fallback` (P2, grok) — UNCONFIRMED:**
   Grok flagged that `run_consult` computes `overall_timeout` as
   `timeout * (2 + int(openrouter_fallback))`, claiming it ignores `api_fallback`,
   `fallback_model`, and `_planned_attempt_count`. Exact-head analysis of
   `scripts/fable_goal_cycle.py` at head `0a37ec64bde1` shows `run_consult` has no
   `api_fallback`, `fallback_model`, or `_planned_attempt_count` parameters — the
   function's only fallback-related parameter is `openrouter_fallback`. The finding
   references parameters that do not exist in the reviewed function. This is an
   unconfirmed model finding (likely a hallucinated cross-reference), not a real catch.

3. **PR #9193 — Test environment Node dependency risk (P2, grok) — UNCONFIRMED:**
   Grok flagged that the test's `subprocess.run` invokes `node sync-docs.js` in a
   stripped tmp tree that may be missing `node_modules`/deps. Exact-head analysis of
   `tests/scripts/test_docs_site_sync_links.py` at head `65521e892675` shows the test
   copies `docs/` and `docs-site/scripts/` to a temp directory and runs `node
   sync-docs.js`. The PR merged with passing CI, confirming `sync-docs.js` is
   self-contained (no external `node_modules` required). This is an unconfirmed model
   finding (a theoretical risk that does not materialize), not a real catch.

**Honest summary: zero real catches.** The 2-family quorum produced model findings on
3 of 5 PRs, but none were independently confirmed as real defects against the exact
head. This is an acceptable, honest result for a 2-family retrospective dogfood: the
gate produces structured, dissent-bearing, verifiable receipts, but the model findings
on this particular PR slice did not correspond to confirmed defects.

### Missed (issues the quorum did not flag)

1. **PR #9056 — Both models passed cleanly.** Grok returned "No findings." Mistral returned a
   single P2 defensive-assert suggestion. Neither model found substantive issues. This PR
   appears genuinely clean (it was merged), so the "miss" may be a true negative — but we
   cannot confirm zero defects without a ground-truth oracle.

2. **PR #9027 — Both models passed.** Mistral noted a P2 path-traversal edge case (already
   handled by existing symlink-refusal tests). Grok returned "No findings." The path traversal
   concern was already mitigated, so this is a minor advisory, not a miss.

### Blocked (dissent — quorum could not reach unanimous pass)

1. **PR #9193 — Grok blocked, Mistral passed.** Grok's 3 P2 findings (Node deps, root_source_files
   logic, Node dependency in test) vs. Mistral's 1 P3. The quorum verdict is CHANGES_REQUESTED
   (dissent recorded). Exact-head analysis found Grok's Node-deps finding unconfirmed (the PR
   merged with passing CI; `sync-docs.js` is self-contained), so this dissent was based on an
   unconfirmed model finding rather than a real defect.

2. **PR #9062 — Grok blocked, Mistral passed.** Grok's 2 P2 findings (timeout calculation,
   prompt composition) vs. Mistral's 3 P3 findings. The quorum verdict is CHANGES_REQUESTED
   (dissent recorded). Exact-head analysis found Grok's timeout finding unconfirmed (it
   references parameters that do not exist in the reviewed function), so this dissent was
   based on an unconfirmed model finding rather than a real defect.

### Couldn't-Decide

1. **Whether the PR #9030 `None`-return caused a production issue.** Both models flagged it,
   but exact-head analysis disproved the finding (the caller guards `None` via `if llm_result:`
   before iterating). This is a confirmed model false positive, not an open question — the
   "couldn't-decide" is whether the quorum **should have** caught the false positive itself,
   which it cannot without an exact-head verification step in the pipeline.

2. **Whether a 3rd family would have broken the dissent ties on PRs #9193 and #9062.** With
   only 2 families, both dissent cases are 1-1 splits. A 3rd family (Gemini) was unreachable
   due to an invalid API key. Adding a 3rd family could have produced a majority verdict
   instead of an unresolved split. → Follow-up: [#9207](https://github.com/synaptent/aragora/issues/9207)

3. **Grok's higher blocking rate.** Grok returned CHANGES_REQUESTED on 3 of 5 PRs while
   Mistral returned CHANGES_REQUESTED on only 1. Since exact-head analysis found zero
   confirmed real catches, Grok's higher blocking rate may reflect over-blocking rather than
   genuine thoroughness. The 2-family quorum cannot adjudicate this calibration question.
   → Follow-up: [#9208](https://github.com/synaptent/aragora/issues/9208)

## Reproducibility

### Offline replay (zero LLM spend)

The 5 ODR receipts in this directory are regenerated from the committed raw reviewer
outputs by the offline replay driver
[`replay_dogfood_receipts.py`](replay_dogfood_receipts.py), which feeds the stored raw
model outputs (`raw-reviews/pr-<N>-reviewers.json`) through the canonical
`collect_outcome_to_decision_receipt` + `decision_receipt_to_odr` collector pipeline
(the same transform `scripts/emit_pr_receipt.py` uses). This path makes **zero live LLM
calls** and spends nothing.

```bash
# 1. Regenerate all 5 receipts through the canonical collector (no LLM calls, $0 spend)
#    Run from the repo root.  No venv or PYTHONPATH required — the script computes the
#    repo root from its own location and adds it to sys.path.  It fails closed (nonzero
#    exit) if any expected raw-review fixture is missing or any receipt is unproduced.
python3 docs/case-studies/dogfood/replay_dogfood_receipts.py

# 2. Verify each receipt (all exit 0: schema_conformance=pass, quorum_consistency=pass)
for f in docs/case-studies/dogfood/pr-*-receipt.odr.json; do
    aragora-verify "$f" --json
done
```

### Original live run (how the raw outputs were produced)

The raw reviewer outputs (`raw-reviews/pr-<N>-reviewers.json`) were produced by the
original live M8 run, which used `aragora.agents.create_agent("grok")` and
`create_agent("mistral-api")` to review each PR's diff. That live run is not reproducible
without provider keys, but its outputs are committed as fixtures so the receipt
regeneration above is fully reproducible offline.

```bash
# Original live run (requires reachable provider keys; NOT needed for receipt regeneration):
set -a; . .env; set +a  # load secrets from the repo root (never print/commit)
gh pr diff 9193 --repo synaptent/aragora > /tmp/pr-9193.diff  # fetch diffs
# Reviewers ran via create_agent("grok") + create_agent("mistral-api") per PR
```

### Provider set

- `grok` (xAI family, model: grok-4-latest, via XAI API)
- `mistral-api` (Mistral family, model: mistral-large-2512, via direct Mistral API)

### Reviewer prompt

Each reviewer received the same adversarial review prompt (mirroring
`collect_quorum_evidence.default_prompt_builder`): "Review ONLY the changes below... Begin your
reply with 'Verdict: PASS' or 'Verdict: CHANGES-REQUESTED'... tag [P1]/[P2]/[P3]..."

## Limitations

1. **Only 2 of 4 intended provider families were reachable.** Gemini's API key is invalid
   (HTTP 400 "API key not valid"). OpenRouter's key is a placeholder (HTTP 401). The quorum
   uses xAI + Mistral only — still heterogeneous (2 distinct families) but a 3rd family would
   strengthen tie-breaking on dissent cases.
   → Follow-up: [#9206](https://github.com/synaptent/aragora/issues/9206)

2. **Receipts are UNSIGNED.** No ODR signing path is wired in the shipped Action. All receipts
   have `signatures: []` and verify at exit 0 with `signature=warn`. Authenticity is
   **UNVERIFIED** — the receipts prove schema/digest/quorum integrity but not cryptographic
   authenticity. This is the current honest state of the product, not a dogfood artifact.
   → Follow-up: [#8544](https://github.com/synaptent/aragora/issues/8544)

3. **Costs are estimates.** Provider invoices are not available in-session. The spend ledger
   records conservative upper-bound estimates based on published per-token pricing, with an
   explicit rounding policy (see [Spend Ledger](#spend-ledger) below). Total estimated M8
   spend: $0.2301 (well under the $100 cap).
   → Follow-up: [#9210](https://github.com/synaptent/aragora/issues/9210)

4. **All reviewed PRs are already merged.** The dogfood reviews are retrospective — we review
   already-merged PRs to evaluate the gate's catch rate, not to block merges. The catches and
   misses are assessed against the known merged state, not a live merge decision.
   → Follow-up: [#9211](https://github.com/synaptent/aragora/issues/9211)

5. **2-family quorum cannot adjudicate dissent.** With 2 families, a 1-1 split (PRs #9193,
   #9062) produces an unresolved CHANGES_REQUESTED verdict. A 3-family quorum would produce a
   majority. This is an inherent limitation of the 2-family configuration, not a gate defect.
   → Follow-up: [#9207](https://github.com/synaptent/aragora/issues/9207)

6. **`aragora review` CLI does not directly emit ODR receipts.** The standard
   `aragora review` CLI produces a review.json but does not directly emit an ODR receipt.
   Receipts were produced through the canonical `collect_outcome_to_decision_receipt` +
   `decision_receipt_to_odr` transform (the same path `scripts/emit_pr_receipt.py` uses) via
   the committed offline replay driver [`replay_dogfood_receipts.py`](replay_dogfood_receipts.py).
   → Follow-up: [#9209](https://github.com/synaptent/aragora/issues/9209)

## Spend Ledger

The shared spend ledger is at [`spend-ledger.json`](spend-ledger.json). The ledger stores
the **exact** per-entry `estimated_cost_usd` values and the cumulative total is the exact
arithmetic sum (no rounding). Summary:

| Entry | PR | Est. Cost (USD) |
|-------|----|-----------------|
| connectivity probe | — | 0.0001 |
| review-pr-9193 | #9193 | 0.05 |
| review-pr-9062 | #9062 | 0.07 |
| review-pr-9030 | #9030 | 0.03 |
| review-pr-9056 | #9056 | 0.05 |
| review-pr-9027 | #9027 | 0.03 |
| **M8 exact sum** | | **0.2301** |
| **M9 exact sum** | | **0.3301** |
| **Cumulative** | | **0.5602 / 100.0** |

No unrecorded spend. The ledger accounts for the 10 M8 reviewer calls (2 per PR x 5 PRs),
the M8 connectivity probes, and every M9 benchmark/probe/replay entry. The exact M8 sum is
`0.0001 + 0.05 + 0.07 + 0.03 + 0.05 + 0.03 = 0.2301`; the ledger applies its stated
conservative rounding policy to M9 batches and stores the exact combined sum, `0.5602`.

## What This Proves

The dogfood demonstrates the **review → receipt → verify** loop end-to-end on real PRs:

1. **Review:** Real heterogeneous multi-model review (grok + mistral) on real Aragora PRs,
   producing genuine independent verdicts with real dissent.
2. **Receipt:** Each review produces a portable ODR artifact with quorum participants,
   disclosed model-family independence, structured dissent, and a PR-bound subject identifier —
   regenerated through the canonical `collect_outcome_to_decision_receipt` collector via the
   committed [`replay_dogfood_receipts.py`](replay_dogfood_receipts.py) offline replay driver.
3. **Verify:** Every receipt independently verifies with `aragora-verify` (exit 0,
   schema_conformance=pass, quorum_consistency=pass) — no Aragora install or account required.

The quorum produced genuine dissent (PRs #9193, #9062) and honestly passed clean PRs (#9056,
#9027). After exact-head verification, **zero model findings were confirmed as real defects**
— the headline PR #9030 "catch" was a model false positive (the caller guards `None` before
iterating). This is an honest result: the gate produces structured, verifiable, dissent-bearing
receipts, but the model findings on this PR slice did not correspond to confirmed defects.
Limitations (2 families, unsigned receipts, retrospective reviews, zero confirmed catches) are
documented above with follow-up issue links, not hidden.
