# Executable Claim Manifests

This directory holds manually curated executable claim manifests for the first
Epistemic CI tranche. A claim manifest is not a test runner and does not mutate
the live queue. It is a stable contract that turns important project claims into
evidence-linked objects that a later runner can evaluate.

The initial contract is deliberately small:

- `claim_id`: stable dotted identifier
- `statement`: the claim being made in prose
- `owner`: accountable project lane or team
- `scope`: where the claim applies
- `confidence`: current confidence level, one of `low`, `medium`, `high`
- `evidence`: one or more evidence links, usually repo paths or workflow names
- `freshness_sla_hours`: maximum acceptable age for the evidence before the
  claim should be considered stale by a runner
- `truth_status` (optional): report-only declaration of whether the claim is
  `live`, `unsupported`, or `aspirational`. A live claim must include a
  timezone-aware `last_verified_at`; the freshness report derives `stale` when
  that timestamp exceeds `freshness_sla_hours`.
- `verification`: verifier kind and command or reference
- `failure`: severity and allowed repair/reporting behavior
- `receipts`: receipt or receipt-class links that should eventually bind the
  claim to signed provenance

Allowed claim result states for later runners are `pass`, `fail`, `stale`,
`unsupported`, and `error`. This DIC-13 tranche defines the schema and examples
only; DIC-14 owns evaluation.

Queue policy: failed or stale claims must not directly create `boss-ready` work
from this manifest. DIC-17 may later propose bounded follow-up issues, still
subject to proof-first queue governance.

## Time-Aware Report

`python3 scripts/report_claim_freshness.py` reads these manifests and emits a
Markdown or JSON inventory of `live`, `stale`, `unsupported`, and
`aspirational` claims. It never executes verification commands and never
creates queue work. Claims without `truth_status` remain valid under schema
version 1 and are reported as `unsupported` until they are deliberately
annotated. This is the migration path for existing manifests.

## Current Manifests

- `proof_first_claims.yaml` - initial proof-first runtime and queue-policy
  claims for the Epistemic CI tranche.
- `outsider_verifiable_claims.yaml` - Jul 2026 preservation claims for the
  outsider-verifiable ODR path, public dogfood artifact reproducibility,
  strategy durability, and question-battery tracking.
