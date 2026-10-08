# Factory Review Benchmark: Two-Family Quorum vs One Named Model

- **Run date:** 2026-07-11
- **Scope:** the three-PR smoke slice in
  [`factory_review_benchmark_manifest.json`](factory_review_benchmark_manifest.json)
- **Named single-model baseline:** `mistral-api` (`mistral-large-2512`)
- **Review quorum:** xAI `grok-4-latest` plus Mistral
  `mistral-large-2512`, two disclosed model families

## Result in one sentence

On this five-golden-defect smoke slice, the named Mistral baseline matched
**1/5** validated defects, while the union of the two-family review quorum
matched **3/5**. The quorum therefore carried two validated catches that the
named baseline missed. It did **not** beat the strongest member: Grok alone also
matched 3/5. This is a small proof case, not a general quality claim.

The complete machine-readable evidence is
[`factory_review_quorum_vs_single_results.json`](factory_review_quorum_vs_single_results.json).
It includes each model's finding set, the matched golden comment IDs, misses,
unmatched findings, the two-family disclosure, receipt paths, and the named
baseline comparison.

## Immutable dataset and PR pointers

The external benchmark is pinned to commit
[`2dfbbd6edcd5eea19495e725d611cb104c9e8f4d`](https://github.com/droid-code-review-evals/review-droid-benchmark/tree/2dfbbd6edcd5eea19495e725d611cb104c9e8f4d).
Its source `manifest.json` blob is
[`a810d4319a798c7980deccedef1f5df8cc86568f`](https://github.com/droid-code-review-evals/review-droid-benchmark/blob/2dfbbd6edcd5eea19495e725d611cb104c9e8f4d/manifest.json).
Every row below binds the PR to exact base/head commits and the human validation
to its blob SHA. No result depends on a moving branch URL.

| Case | Exact base → head | Human validation at benchmark commit | Validation blob |
|---|---|---|---|
| `droid-sentry-pr-6` | [`1a440b4`](https://github.com/droid-code-review-evals/droid-sentry/commit/1a440b410a2b617f22db936658bb3272e4774ac6) → [`cb7212e`](https://github.com/droid-code-review-evals/droid-sentry/commit/cb7212e11dbdbc1813237ad129c7bc108f944e3d) | [pinned JSON](https://raw.githubusercontent.com/droid-code-review-evals/review-droid-benchmark/2dfbbd6edcd5eea19495e725d611cb104c9e8f4d/results/review_droid_run_gpt_5p2_2026-01-28/validations/droid-sentry_pr_6_validation.json) | `29067be0cc2bc91fa32c6669436d83cd851ebbb4` |
| `droid-grafana-pr-1` | [`ed86583`](https://github.com/droid-code-review-evals/droid-grafana/commit/ed865831071a0c0a63c75ad0cfa6661107dabcaf) → [`3647ba7`](https://github.com/droid-code-review-evals/droid-grafana/commit/3647ba7360b8d157e4a294a650a365b6aca070d8) | [pinned JSON](https://raw.githubusercontent.com/droid-code-review-evals/review-droid-benchmark/2dfbbd6edcd5eea19495e725d611cb104c9e8f4d/results/review_droid_run_gpt_5p2_2026-01-28/validations/droid-grafana_pr_1_validation.json) | `f1a2057d21993c39dd761ad4083c9133f4f9bf45` |
| `droid-keycloak-pr-7` | [`21d5311`](https://github.com/droid-code-review-evals/droid-keycloak/commit/21d53112849fe55f328f3de2f071989b8763de61) → [`5d77e7e`](https://github.com/droid-code-review-evals/droid-keycloak/commit/5d77e7ea7d431aa0a6b65904457b7471bd050e81) | [pinned JSON](https://raw.githubusercontent.com/droid-code-review-evals/review-droid-benchmark/2dfbbd6edcd5eea19495e725d611cb104c9e8f4d/results/review_droid_run_gpt_5p2_2026-01-28/validations/droid-keycloak_pr_7_validation.json) | `95f5e20c1d6b510c96a425b63ba3ded4bd2d9442` |

The committed manifest records the same `base_sha`, `head_sha`,
`benchmark_head_sha`, `manifest_blob_sha`, `validation_blob_sha`, and
commit-pinned `validation_url` values.

## Method

1. The existing
   [`run_factory_review_benchmark_smoke.py`](../../scripts/run_factory_review_benchmark_smoke.py)
   established the no-publish, exact-head smoke path. This run fixed its handling
   of `review-pr` exit 2: a completed `CHANGES_REQUESTED` review is evidence, not
   an infrastructure failure.
2. The committed
   [`measure_factory_review_quorum_vs_single.py`](../../scripts/measure_factory_review_quorum_vs_single.py)
   collected one live response per model per case. It uses the same
   `review-pr` exact-head target, bounded diff, and strict JSON prompt helpers,
   but invokes direct Mistral because the generic `review-pr --reviewer
   mistral-api` route stopped at its non-Codex route guard before generation.
3. We compared findings only to `true_positive` records in each pinned human
   validation. A match required the same concrete defect, not merely the same
   file. The exact head was independently inspected before a model finding was
   promoted to a match.
4. The named single-model score is Mistral's matched golden set. The review
   quorum score is the union of matched golden IDs from the disclosed Grok and
   Mistral families. Unmatched model findings remain explicitly unscored.
5. The measurement command emits a genuine `CollectOutcome` fixture per case.
   The canonical [`emit_pr_receipt.py`](../../scripts/emit_pr_receipt.py)
   bridge turns each fixture into an ODR. No `DecisionReceipt` is hand-built.

### Live collection command

Set valid direct `XAI_API_KEY` and `MISTRAL_API_KEY` credentials, then run:

```bash
ARAGORA_USE_SECRETS_MANAGER=false ARAGORA_SECRETS_STRICT=false \
  PYTHONPATH=. python3 scripts/measure_factory_review_quorum_vs_single.py collect \
  --providers grok mistral-api \
  --allow-external-output \
  --output /tmp/factory-review-live-collection.json
```

This command makes six model calls and posts no PR comments. The committed
[`factory_review_quorum_vs_single_live_collection.json`](factory_review_quorum_vs_single_live_collection.json)
preserves all six raw provider responses and normalized findings. Its canonical JSON SHA-256 is
`8c675aa9f61d9962fcbe71f5e8265f68f9e334358d04dd5365f4fd4e59e603a9`.
The separate [`factory_review_quorum_vs_single_evidence.json`](factory_review_quorum_vs_single_evidence.json)
contains manual `golden_comment_id` mappings against the pinned validation records,
and is not represented as raw model output.

`grok` remains the provider and historical replay-fixture identifier used to
invoke xAI. The machine-readable measurement result normalizes that provider's
model family to canonical `xai`, matching the ODR receipts, and includes a
`family_aliases` mapping. Keeping the fixture reviewer identifier unchanged
preserves deterministic replay of the committed receipts.

### Deterministic measurement command

```bash
PYTHONPATH=. python3 scripts/measure_factory_review_quorum_vs_single.py measure
```

The default command writes only to the committed in-repository result and fixture
paths. A read-only checkout can instead use explicit external destinations:

```bash
PYTHONPATH=. python3 scripts/measure_factory_review_quorum_vs_single.py measure \
  --allow-external-output \
  --outcome-dir /tmp/factory-review-outcomes \
  --output /tmp/factory-review-results.json
```

That command spends nothing. It fails closed on missing cases, mismatched SHAs,
moving validation URLs, changed provider/finding sets, unknown golden IDs, or
fewer than two model families. Finding text is taken from the committed live
collection, not the adjudication file. The command regenerates the result JSON
and all three committed `CollectOutcome` fixtures.

## Per-case results

The denominator is the pinned human-validated true-positive set, not every
finding either model emitted.

| Case | Goldens | Mistral baseline | Grok | Two-family union | Outcome |
|---|---:|---:|---:|---:|---|
| Sentry PR 6 | 1 | 0/1 | 1/1 | 1/1 | quorum adds golden `2743651586` |
| Grafana PR 1 | 1 | 1/1 | 1/1 | 1/1 | tie, both identify the TOCTOU race |
| Keycloak PR 7 | 3 | 0/3 | 1/3 | 1/3 | quorum adds golden `2743702342`, misses two |
| **Total** | **5** | **1/5 (20%)** | **3/5 (60%)** | **3/5 (60%)** | **+2 goldens vs named baseline** |

### Receipt-evidenced single-model misses

Two cases meet the narrow claim. Both are machine-readable in the result JSON:

- **Sentry, golden `2743651586`:** Grok finding `grok-2` identifies the
  negative QuerySet slice and is mapped to the validation record. The named
  Mistral baseline has an empty matched set and lists `2743651586` in
  `missed_golden_ids`. Exact-head inspection confirms
  `queryset[start_offset:stop]` receives the negative `cursor.offset`.
- **Keycloak, golden `2743702342`:** Grok finding `grok-2` identifies the
  Italian `totpStep1` in the Lithuanian bundle. The named Mistral baseline has
  no matched golden and lists `2743702342` as missed. Exact-head inspection
  confirms the literal Italian string.

For each case, `quorum.distinct_model_families` is `2`,
`quorum.families` is `["mistral", "xai"]`, and `receipt_path` points to a
verifiable ODR produced from the paired live findings. The result JSON and each
fixture carry the live collection digest plus a manual-adjudication disclosure:

| Case | Receipt | Verdict | Content digest | Authenticity |
|---|---|---|---|---|
| Sentry | [`droid-sentry-pr-6-receipt.odr.json`](receipts/droid-sentry-pr-6-receipt.odr.json) | `CHANGES_REQUESTED` | `f586b4272e1a1915f95cee2a02fa207dce487a237a71fd32889d87e174fc4072` | unsigned, identity not authenticated |
| Grafana | [`droid-grafana-pr-1-receipt.odr.json`](receipts/droid-grafana-pr-1-receipt.odr.json) | `CHANGES_REQUESTED` | `e64756e813dac4064562bf8b6aed2d72fcace76f97d00f7331a6783972a196e2` | unsigned, identity not authenticated |
| Keycloak | [`droid-keycloak-pr-7-receipt.odr.json`](receipts/droid-keycloak-pr-7-receipt.odr.json) | `CHANGES_REQUESTED` | `bfa673e02701f0dfb727fd8d990e815f3bb089cdd32841d8564d75ccaa2a0ad2` | unsigned, identity not authenticated |

All three receipts return `aragora-verify` exit 0 with
`schema_conformance=pass` and `quorum_consistency=pass`. They disclose two
families and structured dissent. They are review-quorum evidence, not a
supportive merge quorum: both reviewers requested changes, so
`quorum.reached=false`.

## Zero-spend offline receipt replay

This is the cheap validator path. It uses only a committed `CollectOutcome`
fixture and the shipping receipt bridge:

```bash
PYTHONPATH=. python3 scripts/emit_pr_receipt.py \
  --outcome docs/benchmarks/fixtures/droid-sentry-pr-6.collect-outcome.json \
  --out /tmp/m9-benchmark-replay.odr.json \
  --verify
PYTHONPATH=aragora-verify/src python3 -m aragora_verify \
  /tmp/m9-benchmark-replay.odr.json --json
```

Observed result: both commands exit 0; the verifier reports
`schema_conformance=pass`, `canonical_digest=pass`, and
`quorum_consistency=pass`. The signature check is `warn` because the receipt is
unsigned. This replay makes no model or network call and costs `$0`.

## Honest limitations

1. This is the pre-authorized 3-PR smoke slice, not the external corpus's 50
   PRs. Full-corpus execution remains gated on smoke review
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
2. There is one run per provider per case, so there are no confidence intervals,
   repeat-run variance, or judge-swap variance yet
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
3. The quorum does not beat its strongest member here: Grok and the two-family
   union both match 3/5 goldens. The demonstrated claim is only that the union
   catches two defects missed by the **named Mistral baseline**
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
4. The quorum misses 2/5 goldens, both in Keycloak: the Simplified/Traditional
   Chinese mismatch (`2743702343`) and substring-bounds crash (`2743702347`)
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
5. The models emit 24 findings not mapped to the five validated goldens. They
   are unscored, not silently counted as true or false positives, so this run
   does not claim precision
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
6. The Keycloak PR exceeds the review path's 60,000-character diff cap. The
   exact-head prompt is bounded and may omit relevant later hunks, which may
   contribute to the two misses
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
7. Only two provider families were reachable in this environment. This is
   heterogeneous, but it is a minimal quorum rather than a broad jury
   ([#9206](https://github.com/synaptent/aragora/issues/9206)).
8. The ODRs are intentionally unsigned. Their schema, digest, and quorum
   consistency verify, and their text is traceable to the committed raw
   collection. Provider identity/authenticity is still not established until
   the shipping signing path lands
   ([#8225](https://github.com/synaptent/aragora/issues/8225)).
9. Golden mappings are manual adjudication against pinned validation files and
   exact PR heads. Receipts prove replay, not independent judge correctness
   ([#7226](https://github.com/synaptent/aragora/issues/7226)).
10. Spend uses conservative token and published-price estimates because provider
   invoices were unavailable in-session
   ([#9210](https://github.com/synaptent/aragora/issues/9210)).

## Spend

The single source of truth is the shared
[`spend-ledger.json`](../case-studies/dogfood/spend-ledger.json), also cited by
the M8 dogfood report. M9 records `$0.3301` estimated spend, including the
connectivity probe, an initial Grok smoke pass, the six-call two-family run, a
zero-cost blocked routing attempt, and zero-cost offline replay. Cumulative
M8+M9 estimated spend is **`$0.5602 / $100`**, leaving `$99.4398`.
