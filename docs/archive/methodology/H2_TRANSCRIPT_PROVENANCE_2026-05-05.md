# H2 Transcript Provenance Guard

Date: 2026-05-05

## Problem

Round 31b H2 exposed a receipt-to-transcript preservation gap. The final
single-family baseline receipt survived at
`docs/receipts/heterogeneity/baseline-single-family-anthropic-20260504T030352Z.receipt.json`,
but the matching transcript sidecar
`.aragora/evolve-round/2026-05-01b/transcripts/baseline-single-family-anthropic-20260504T030352Z.transcripts.json`
was not present on disk. That made a symmetric raw-text re-judge under the
post-#7014 judge contract impossible without re-running baseline panel calls.

## Guard

New heterogeneity probe receipts can carry a top-level `source_artifacts` array.
For transcript evidence, each artifact records:

- `role: transcript_sidecar`
- `path`
- `sha256`
- `bytes`
- `format`
- `hash_spec: sha256(raw file bytes)`
- `required_for_rejudge`
- `text_capture`
- `created_before_receipt_id`

The artifact metadata is included in `receipt_id` hashing. If transcript bytes
change after receipt production, the binding no longer validates.

## Policy

New settlement-grade receipts should fail closed when source artifacts are
missing or hash-mismatched. Legacy `heterogeneity_probe_receipt.v1` receipts
without `source_artifacts` are still readable, but comparison receipts label
them `legacy_unbound` and set `comparison_canonical: false`.

This PR does not retroactively hash old receipts. Retroactive hashing would turn
an honest "artifact not bound at production time" into a false provenance claim.

## Legacy Receipts

The following known receipts remain valid historical receipts but are
provenance-unbound unless a future operator explicitly reruns the producer:

- `docs/receipts/heterogeneity/baseline-single-family-anthropic-20260504T030352Z.receipt.json`
- `.aragora/evolve-round/2026-05-04-round-31b-h2/phase-h2-panel.json`
- `.aragora/evolve-round/2026-05-04-round-31b-h2/phase-h2-comparison.json`
- `.aragora/evolve-round/2026-05-04-round-31b-h2/round-receipt-final.json`

## Non-Claims

This guard does not re-judge any receipt, rerun the H2 panel, mutate historical
H2 artifacts, settle H2, close #6375, or modify the strict CI-separation
verdict rule. It only binds future receipt evidence to transcript sidecars.

Ledger-to-receipt hash binding is a separate follow-up. This guard binds probe
receipts to transcript evidence, not round ledgers to every downstream receipt.
