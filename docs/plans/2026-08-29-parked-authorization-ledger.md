# Parked Authorization Ledger

The parked-authorization ledger is a read-only transport helper for exact-head
human decisions already requested on open pull requests. It scans open
non-Dependabot PR comments, identifies the latest terminal authorization or
preapproval request, and omits an ask only when a later decisive operator reply
addresses the same PR or exact head.

Rows rank current-head asks first when all five non-quorum protected checks are
green and GitHub reports `MERGEABLE` with `CLEAN` or `BLOCKED`. Lower tiers rank
before higher tiers. Stale asks remain visible at the bottom as `HEAD MOVED -
re-ask`; the helper never treats an old authorization as applying to a new head.

The generated packet uses the `## Pending Rulings` table schema consumed by
`scripts/founder_decision_queue.py`. Because these decisions require full
exact-head authorization text, the legacy `One-word reply` column points to a
copy-ready block below the table instead of inventing a weaker shorthand.

This ledger grants nothing. It does not post comments, mark PRs ready, rerun
checks, collect evidence, record settlement, merge, or mutate workflows or
branch protection. Every reply block remains subject to live head, ownership,
required-check, tier, and settlement revalidation at execution time.
