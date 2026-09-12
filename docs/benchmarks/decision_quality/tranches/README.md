# Decision Quality Corpus Tranches

These files are construction inputs for the outcome-backed decision-quality
benchmark. They are not independently eligible for a counted benchmark run.

`software-development-1` contributes the four software-engineering development
cases required by the planned 24-case corpus. Every evidence URL is pinned to
an immutable Git commit or release tag, and the outcome answer key remains in a
separate hash-bound sidecar.

`business-operations-1` contributes four business/operations development
cases. Its acquisition scenarios deliberately balance two completed and two
terminated transactions. Pre-cutoff packets combine the signed transaction
with a public litigation or regulator signal; outcomes remain in the separate
hash-bound sidecar.

`policy-compliance-1` contributes four nonpartisan policy/compliance
development cases. The tranche balances two rules published within the stated
horizon and two standards or rules published after the stated horizon. All
model-visible evidence is an official pre-cutoff publication; later outcome
evidence remains in the hash-bound sidecar.

`science-forecasting-1` contributes four science/forecasting development
cases. It balances two observed outcomes that met the forecast threshold and
two delayed missions that did not. Model-visible evidence is limited to
official pre-cutoff NASA or NOAA material; the measured outcomes remain in the
hash-bound sidecar.

`software-engineering-holdout-1` contributes the two software-engineering
holdout cases. One roadmap commitment was fulfilled and one announced language
semantic change did not ship on schedule. Both cases use immutable upstream
release or source-history evidence, and their outcomes remain in the separate
hash-bound sidecar.

`business-operations-holdout-1` contributes the two business/operations
holdout cases. One regulatory return-to-service milestone was met and one
aircraft delivery milestone was formally delayed. Both cases use immutable SEC
filings, with the outcome answer key kept in the separate hash-bound sidecar.

`policy-compliance-holdout-1` contributes the two policy/compliance holdout
cases. One final rule was published within the stated readiness horizon and one
was published just after it. Both cases use immutable GovInfo Federal Register
documents, with the outcome answer key kept in the separate hash-bound sidecar.

`science-forecasting-holdout-1` contributes the two science/forecasting holdout
cases. One sample-return milestone was completed within its recovery horizon
and one first-flight launch moved beyond its operating horizon. Both cases use
official NASA publications, with the outcome answer key kept in the separate
hash-bound sidecar.

The forecast target is outcome-aligned in exactly 12 of the 24 cases. Each
domain contributes three aligned and three non-aligned targets, split as two
of four development cases and one of two holdout cases. Every question uses
the same neutral forecast template, and each case's options are ordered
lexicographically by `option_id` so wording polarity and option position do
not disclose the answer key.

Digests below are SHA-256 values over canonical JSON serialized with sorted
keys, compact separators, and UTF-8 output (`ensure_ascii=False`). They are
not hashes of the formatted file bytes.

Software-engineering development tranche:

- corpus: `e9ec5a9a62b6d2d9a6cd9664989d3be6e45b7cc7cbfe0d57919a4238e0770b27`
- outcome sidecar: `cb3f1c0b7762b144142044a510f8c0cb489a15699ce6a7c6e262e2f35b17938d`

Business/operations tranche:

- corpus: `ac9676ff9715b724a436ac3f697e3599aba8416e061fe009088eea4360ad8bba`
- outcome sidecar: `ce281b2caab29f79b07d7784c3d19a08243ad914e1e384226dd17ff63f1452d4`

Policy/compliance tranche:

- corpus: `17bce195c719c30c128b0ce86e906754c076e2c03da4a10f6421d9e80f57943b`
- outcome sidecar: `171cb032ca3047305ecb2086ad0913417d5a95fcfaec8dc228ba1b4f1dcf197b`

Science/forecasting tranche:

- corpus: `2fc5525c8b7a23c5f57faed12967cb170be1e83c6afcba58ac45b43cefa18445`
- outcome sidecar: `061f6dc846889b01a22e3562b998d6b2b43f3bcf24efbe048f33b2089286de38`

Software-engineering holdout tranche:

- corpus: `97da356b5d70618c332e5fc52a0510996e28c6723aa00111206e663dc581295e`
- outcome sidecar: `1db3bd542e913b09c820af98a9ce4237f7dbfe8bbfed53d77f35fcf7f0bce292`

Business/operations holdout tranche:

- corpus: `2036afb2a909e1ffd16d5764fefd1fbccbeb298dd29924222d6034ec30d7e855`
- outcome sidecar: `05a6640cbee4878d0726d8dbbe92f6e9ebcb97a7eae7b0a03939cea2829358ff`

Policy/compliance holdout tranche:

- corpus: `318c209ccfc5d24b82f6083f284334fb89f752a9dfc6a8ab0ee68d6f5a5dbd4d`
- outcome sidecar: `247848041189c398c20a57547901aafff6d30d51fd98206e5e5a5e0c4689e8a1`

Science/forecasting holdout tranche:

- corpus: `503a5cc94a26fcd38f8c0bb264413ac82b2ae7a3489da8d22e6d646254702ed6`
- outcome sidecar: `9d93b2f085b1c8586f67ee73538219bc1a98888ef0d4b3d11f196b9976b4e7d4`

These tranches are construction inputs, not frozen benchmark artifacts. Run
`python3 scripts/validate_outcome_backed_corpus.py --json` to check JSON
structure, corpus/outcome case and option bindings, information cutoffs,
source hashes, answer-key balance, canonical digests, and outcome leakage
across the assembled 24-case corpus. The adjacent `benchmark-manifest.json`
and `scripts/validate_outcome_decision_quality_manifest.py` bind those exact
canonical and aggregate corpus digests together with the prompt, roster,
scorer metrics, budget, and repeated-holdout invalidation contract. The
manifest validator complements rather than replaces the structural and
outcome-leakage validator. Counted inference remains prohibited until the
benchmark runner also lands on `main`.

Together the eight tranches provide all 24 planned cases: four development and
two holdout cases in each required domain.

Do not run model inference from a tranche. Counted inference begins only after
all 24 cases, the scoring contract, prompts, roster, and both corpus digests are
merged and frozen together.
