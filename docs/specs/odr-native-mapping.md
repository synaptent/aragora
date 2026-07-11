# Native `DecisionReceipt` → ODR field mapping

**Status:** normative companion to
[`OPEN_DECISION_RECEIPT.md`](./OPEN_DECISION_RECEIPT.md) §9.4.

This document is the field-by-field contract between the native
`aragora.gauntlet.DecisionReceipt` (the internal audit record) and the
portable Open Decision Receipt (ODR) content profile emitted by
`aragora/gauntlet/odr_export.py::decision_receipt_to_odr`.

**Invariants:**

- The emitter **never fabricates** — a field with no real source carries an
  absent marker (see ODR §3), it is not invented.
- Every ODR top-level field below is covered by a drift-guard test
  (`tests/gauntlet/test_odr_native_mapping.py`): if the emitter grows or renames
  a top-level field and this doc is not updated, the test fails.
- The on-wire `odr_version` is independent of the native
  `DecisionReceipt.schema_version` (ODR §9.4); the latter is recorded under
  `source.schema_version`.

## Top-level field mapping

| ODR field | Native source | Emitter mapping | Notes |
|---|---|---|---|
| `odr_version` | (constant) | `ODR_VERSION` in `odr_export.py` | On-wire profile version; stays `"0.1"` until the coordinated GA flip (ODR §9.5). |
| `profile` | (constant) | `ODR_PROFILE_URI` in `odr_export.py` | Profile URI; revs with a major bump. |
| `receipt_id` | `DecisionReceipt.receipt_id` | copied verbatim | Stable identifier; also echoed in `source.receipt_id`. |
| `issued_at` | `DecisionReceipt.timestamp` | `receipt.timestamp or None` | ISO-8601 UTC; `None` when the source has no timestamp. |
| `subject` | `DecisionReceipt` (question / debate identity, artifact hash) | `_map_subject(receipt)` | What the decision was about; carries the subject digest. |
| `claim` | `DecisionReceipt` (verdict + statement) | `_map_claim(receipt)` | What is asserted (e.g. verdict + one-line statement). |
| `reasoning` | `DecisionReceipt` reasoning summary | `_map_reasoning(receipt)` | Provisional; absent marker when no summary exists. |
| `quorum` | `DecisionReceipt.consensus` / participants | `_map_quorum(receipt)` + `_map_participants(receipt)` | Adversarial-quorum verdict: method, reached, supporting/dissenting agents, participants, independence. |
| `confidence` | `DecisionReceipt` confidence + optional calibration | `_map_confidence(receipt, calibration_provenance)` | Provisional; optional `provenance_ref` when calibration data is supplied. |
| `cruxes` | optional `crux_set` argument | `_map_cruxes(crux_set)` | Load-bearing disagreement; absent marker when no crux set is passed. |
| `attestation` | optional `attestation` argument | `_map_attestation(attestation)` | Human accountability; honest `autonomous` disposition when omitted. |
| `epistemic` | `DecisionReceipt.unverified` / `assumptions` / `falsification` | `_map_epistemic(receipt)` when at least one epistemic limit exists | Optional decision-limit block: what was not verified, accepted assumptions, and future observation/check date that would falsify the decision. |
| `routing` | (reserved) | `{"status": "reserved"}` | Reserved tier; no compatibility promise until defined (ODR §9.1). |
| `signatures` | (none at export) | `[]` | Always empty at export; detached signing is a separate step (ODR §8, item 4). |
| `source` | `DecisionReceipt` provenance | inline block | Native-record provenance: `system`, `schema`, `schema_version` (= `receipt.schema_version`), `receipt_id`, `artifact_hash`. |

## Keeping this in sync

When `decision_receipt_to_odr` adds, removes, or renames a top-level field:

1. Update the table above (wrap the field name in backticks).
2. Run `pytest tests/gauntlet/test_odr_native_mapping.py -v` — it asserts every
   emitted top-level field appears here.
3. If the change is more than additive-optional, also revisit ODR §9
   (Versioning and Stability) — it may require a minor or major bump.
