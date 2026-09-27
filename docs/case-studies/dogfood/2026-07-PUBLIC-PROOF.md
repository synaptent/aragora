# Review, Receipt, Verify: Public Proof from Real Code Reviews

**Published:** 2026-07-11
**Repository:** [synaptent/aragora](https://github.com/synaptent/aragora)
**Evidence:** 5 real Aragora PRs, 3 external benchmark PRs, 8 independently verifiable receipts

## The claim, in plain language

Aragora asks independent models to review the same proposed change, preserves
their agreement and disagreement in a portable JSON receipt, and lets anyone
check that receipt with a standalone verifier.

This report tests two narrow claims:

1. **The process leaves an independently checkable record.** Five real Aragora
   PRs went through two-family review, receipt generation, and offline
   verification.
2. **Combining independent reviewers can add coverage over one named model.**
   On a small external benchmark, the Grok-plus-Mistral union found two
   validated defects that the named Mistral baseline missed.

The evidence does **not** show that every quorum finding is correct, that this
two-model quorum beats its strongest member, or that the result generalizes to
all repositories. Those boundaries are part of the proof.

## What review, receipt, and verify mean

1. **Review:** xAI Grok and Mistral independently inspect the same exact code
   change and return `PASS` or `CHANGES_REQUESTED` with findings.
2. **Receipt:** Aragora's checked-in collector converts those responses into an
   Open Decision Receipt (ODR). The receipt identifies the subject, reviewers,
   model families, verdict, dissent, and content digest.
3. **Verify:** `aragora-verify` checks the ODR schema, canonical digest, and
   quorum consistency offline. Verification does not require an Aragora
   account or trust in an Aragora server.

In this evidence set, `CHANGES_REQUESTED` means that the review recorded a
blocking opinion. It does not by itself prove that the opinion was correct.

## Evidence set A: dogfood on five real Aragora PRs

The [M8 dogfood run](2026-07-DOGFOOD.md) reviewed a
representative slice of recent Aragora work: one test change, two feature
changes, and two bug fixes.

| PR | Change type | Review result | What the record shows |
|---|---|---|---|
| [#9193](https://github.com/synaptent/aragora/pull/9193) | Test | Split: Grok requested changes, Mistral passed | Dissent preserved; exact-head adjudication did not confirm the proposed defect |
| [#9062](https://github.com/synaptent/aragora/pull/9062) | Feature | Split: Grok requested changes, Mistral passed | Dissent preserved; the main blocking finding referenced parameters absent from the reviewed function |
| [#9030](https://github.com/synaptent/aragora/pull/9030) | Bug fix | Both requested changes | The unanimous finding was a false positive; the caller already guarded the `None` result |
| [#9056](https://github.com/synaptent/aragora/pull/9056) | Feature | Both passed | A clean pass with the two-family quorum recorded |
| [#9027](https://github.com/synaptent/aragora/pull/9027) | Bug fix | Both passed | A clean pass; the noted path concern was already covered by existing defenses |

The honest M8 result is **zero confirmed real catches** after independent
inspection of the reviewed heads. That result still demonstrates the complete
review-to-receipt-to-verify path, including real disagreement and false
positives that remain visible instead of being rewritten as successes.

## Evidence set B: a defect benchmark with known answers

The M9 benchmark uses three exact-head PRs from the public
[`review-droid-benchmark`](https://github.com/droid-code-review-evals/review-droid-benchmark)
corpus. Human validation files identify five known true-positive defects, so
the reviewers can be measured against an answer key rather than a merge
outcome.

At publication time, benchmark PR
[#9225](https://github.com/synaptent/aragora/pull/9225) remained open. Its
evidence is therefore referenced at immutable head
[`a2da802f0bfc6427306181ecfbbc3ff0e78b3d86`](https://github.com/synaptent/aragora/commit/a2da802f0bfc6427306181ecfbbc3ff0e78b3d86),
not at a moving branch.

<!--
Live status checked 2026-07-11 with:
gh pr view 9225 --repo synaptent/aragora --json state,headRefOid
Result: OPEN, a2da802f0bfc6427306181ecfbbc3ff0e78b3d86.
Re-run that command before changing this status statement.
-->

The pinned [benchmark report](https://github.com/synaptent/aragora/blob/a2da802f0bfc6427306181ecfbbc3ff0e78b3d86/docs/benchmarks/2026-07-factory-review-quorum-vs-single.md)
and [machine-readable results](https://github.com/synaptent/aragora/blob/a2da802f0bfc6427306181ecfbbc3ff0e78b3d86/docs/benchmarks/factory_review_quorum_vs_single_results.json)
record:

| Case | Known defects | Named Mistral baseline | Grok | Two-family union |
|---|---:|---:|---:|---:|
| Sentry PR 6 | 1 | 0/1 | 1/1 | 1/1 |
| Grafana PR 1 | 1 | 1/1 | 1/1 | 1/1 |
| Keycloak PR 7 | 3 | 0/3 | 1/3 | 1/3 |
| **Total** | **5** | **1/5 (20%)** | **3/5 (60%)** | **3/5 (60%)** |

The two additional catches over the named baseline were:

- a negative Django QuerySet slice in Sentry, which raises at runtime; and
- an Italian TOTP instruction copied into Keycloak's Lithuanian locale.

This supports only the narrow claim that the **two-family union added coverage
over the named Mistral baseline** on this slice. The union tied Grok alone at
3/5 and still missed two validated Keycloak defects.

## Eight receipts, independently checked

All receipts below were produced through Aragora's checked-in
review-to-receipt collector. No receipt was hand-constructed for this report.

| Evidence | Receipt | Verdict | `aragora-verify` | Schema | Quorum | Signature |
|---|---|---|---:|---|---|---|
| Aragora #9193 | [ODR](pr-9193-receipt.odr.json) | `CHANGES_REQUESTED` | 0 | pass | pass | warn, unsigned |
| Aragora #9062 | [ODR](pr-9062-receipt.odr.json) | `CHANGES_REQUESTED` | 0 | pass | pass | warn, unsigned |
| Aragora #9030 | [ODR](pr-9030-receipt.odr.json) | `CHANGES_REQUESTED` | 0 | pass | pass | warn, unsigned |
| Aragora #9056 | [ODR](pr-9056-receipt.odr.json) | `PASS` | 0 | pass | pass | warn, unsigned |
| Aragora #9027 | [ODR](pr-9027-receipt.odr.json) | `PASS` | 0 | pass | pass | warn, unsigned |
| Benchmark Sentry | [ODR at pinned head](https://github.com/synaptent/aragora/blob/a2da802f0bfc6427306181ecfbbc3ff0e78b3d86/docs/benchmarks/receipts/droid-sentry-pr-6-receipt.odr.json) | `CHANGES_REQUESTED` | 0 | pass | pass | warn, unsigned |
| Benchmark Grafana | [ODR at pinned head](https://github.com/synaptent/aragora/blob/a2da802f0bfc6427306181ecfbbc3ff0e78b3d86/docs/benchmarks/receipts/droid-grafana-pr-1-receipt.odr.json) | `CHANGES_REQUESTED` | 0 | pass | pass | warn, unsigned |
| Benchmark Keycloak | [ODR at pinned head](https://github.com/synaptent/aragora/blob/a2da802f0bfc6427306181ecfbbc3ff0e78b3d86/docs/benchmarks/receipts/droid-keycloak-pr-7-receipt.odr.json) | `CHANGES_REQUESTED` | 0 | pass | pass | warn, unsigned |

The eight observed verifier runs all returned exit `0` with
`schema_conformance=pass` and `quorum_consistency=pass`.

### Authenticity disclosure

All eight receipts have `signatures: []`. The verifier therefore reports
`signature=warn`: document integrity and quorum consistency pass, but
cryptographic issuer and provider identity are **not authenticated**. These
are verifiable unsigned receipts, not signed attestations.

### Re-run the receipt checks

From a checkout containing the M8 dogfood artifacts:

```bash
for receipt in docs/case-studies/dogfood/pr-*-receipt.odr.json; do
  PYTHONPATH=aragora-verify/src python3 -m aragora_verify "$receipt" --json
done
```

PR #9225 is still open, so fetch and verify its three receipts at the exact
head rather than relying on a moving branch:

```bash
BENCHMARK_HEAD=a2da802f0bfc6427306181ecfbbc3ff0e78b3d86
git fetch origin "$BENCHMARK_HEAD"
mkdir -p /tmp/aragora-m9-proof

for name in droid-sentry-pr-6 droid-grafana-pr-1 droid-keycloak-pr-7; do
  git show "${BENCHMARK_HEAD}:docs/benchmarks/receipts/${name}-receipt.odr.json" \
    > "/tmp/aragora-m9-proof/${name}-receipt.odr.json"
  PYTHONPATH=aragora-verify/src python3 -m aragora_verify \
    "/tmp/aragora-m9-proof/${name}-receipt.odr.json" --json
done
```

Each command is offline after the pinned commit is fetched. No model call is
made, so receipt verification adds no LLM spend.

## Shared spend ledger

The only M8+M9 spend source is
[`docs/case-studies/dogfood/spend-ledger.json`](spend-ledger.json).
The M8 report cites that same path.

| Scope | Estimated spend |
|---|---:|
| M8 dogfood | `$0.2301` |
| M9 benchmark | `$0.3301` |
| **Cumulative** | **`$0.5602 / $100`** |
| Remaining cap | `$99.4398` |

The ledger has 11 per-run entries. Their stored `estimated_cost_usd` values
sum exactly to `0.5602`, matching `cumulative_usd`. Costs are conservative
token-price estimates because provider invoices were unavailable.

The ledger also names the failed **OpenRouter HTTP-401 connectivity probe** in
the M8 probe entry and records that it had **zero billable usage**. This report
made no additional model calls and added `$0` spend.

## What this evidence supports

- The system can review real changes with two disclosed model families,
  preserve dissent, emit portable ODR receipts, and verify them independently.
- The benchmark shows two validated catches added by the two-family union over
  one named baseline on a small, pinned defect set.
- The artifacts expose false positives, misses, unresolved dissent, unsigned
  authenticity, and spend instead of hiding them.

## What this evidence does not support

1. **Not a full-corpus result.** The benchmark covers 3 of 50 corpus PRs and one
   run per provider, so it has no confidence interval or variance estimate.
   Follow-up: [#7226](https://github.com/synaptent/aragora/issues/7226).
2. **Not evidence that the quorum beats its strongest member.** Grok alone and
   the union both matched 3/5 validated defects.
   Follow-up: [#7226](https://github.com/synaptent/aragora/issues/7226).
3. **Not a precision claim.** The benchmark contains 24 unmatched findings that
   remain unscored, and the M8 slice produced zero independently confirmed
   catches.
   Follow-ups: [#7226](https://github.com/synaptent/aragora/issues/7226) and
   [#9208](https://github.com/synaptent/aragora/issues/9208).
4. **Not a live pre-merge trial.** The five Aragora PR reviews were
   retrospective, which demonstrates the artifact path but not a live blocking
   intervention.
   Follow-up: [#9211](https://github.com/synaptent/aragora/issues/9211).
5. **Not a broad jury.** Only xAI and Mistral were reachable, which is
   heterogeneous but minimal.
   Follow-up: [#9206](https://github.com/synaptent/aragora/issues/9206).
6. **Not cryptographic authenticity.** The receipts are intentionally unsigned.
   Follow-up: [#8225](https://github.com/synaptent/aragora/issues/8225).
7. **Not invoice-grade cost accounting.** Spend uses conservative estimates.
   Follow-up: [#9210](https://github.com/synaptent/aragora/issues/9210).

## Bottom line

The strongest supported statement is modest and checkable: **eight real review
artifacts complete the review-to-receipt-to-verify loop, and a pinned
three-case benchmark shows a two-family union catching two validated defects
missed by the named Mistral baseline.** Every referenced receipt verifies at
exit `0`; every receipt is disclosed as unsigned; the combined estimated spend
is `$0.5602`, well below the `$100` cap.
