# Plan: Aragora Public Wedge Contract-Closure Campaign

## Mission

Harden Aragora's documented public journey from review through a native Decision Receipt,
portable ODR export/signing, offline verification, and Python/TypeScript SDK consumption. The
campaign advances one bounded, non-overlapping Tier 0-2 PR at a time from fresh `origin/main`
until the fixed five-cell journey matrix or a mechanical stop condition is satisfied.

This Elves run stages and executes only the first campaign unit. A new fresh-main worktree,
ownership check, lease, and draft PR are required for every later unit.

## Scope

### In Scope

- Deterministic executable contracts for existing public review, receipt, ODR, verifier, and SDK
  interfaces.
- The smallest repair for a proved contract gap, bounded to at most eight files and roughly 500
  changed lines excluding generated fixtures.
- Clean-install or isolated-package validation when packaging behavior is part of the contract.
- One independent non-countable review before exact-head evidence and governed Tier 0-2 landing.
- An uncommitted campaign ledger under `.aragora/conductor_cycles/`.

### Out of Scope

- Workflows, protected governance, merge/evidence infrastructure, deployment, secrets,
  dependency versions, paid infrastructure, and live inference.
- New public endpoints, breaking public API/SDK changes, or a new receipt/verifier subsystem.
- Outcome-backed decision-quality contracts, duplicate-issue queues, or any active task, lane,
  lease, branch, open-PR file set, or reviewer reservation.
- Current SDK `modes`/`spectate`, keyless-doctor, recurring-status, provider-neutral deployment,
  and ODR-verifier-parity work, including all paths touched by PR #9015.
- Admin merge, force push, squash merge, Tier 3-4 settlement, or more than one active campaign PR.

## Journey Matrix

1. Zero-key `demo --offline` -> native receipt verification -> ODR export -> standalone
   `aragora-verify`, from clean package installations.
2. `review-pr` with deterministic fake providers -> grounded findings -> receipt accepted by the
   public verifier, with truthful provider/quorum failures.
3. Python and TypeScript SDK parity for existing review and receipt interfaces against canonical
   OpenAPI.
4. Signed-receipt authenticity and tamper rejection across existing CLI/verifier interfaces,
   excluding any path touched by PR #9015.
5. Quickstart, CLI, SDK, and cold-reviewer examples executable against those same contracts.

## Batch 1: Compose the zero-key offline receipt proof

### Baseline finding

Current main separately proves demo/native verification, ODR export, and an installed standalone
verifier against different fixtures. It does not execute one demo-produced artifact through the
entire documented chain. A manual clean temporary-directory run at
`eaaac1a07480b64d3ba4a060fbf36773ae36e589` passed, demonstrating a missing regression contract
rather than a known product defect.

### Tasks

- [x] Add one deterministic subprocess-based contract in
  `tests/cli/test_receipt_roundtrip.py` that removes provider credentials and runs the existing
  offline demo, native verifier, ODR exporter, and standalone verifier on one artifact.
- [x] Build the root package and `aragora-verify` wheels from the checked-out source, install them
  outside the source tree, and invoke the installed modules from a temporary working directory.
- [x] Assert the expected exit-code and receipt-ID continuity contract at every seam.
- [x] Add mutation/break coverage proving the installed standalone verifier rejects a tampered ODR
  derived from that same demo receipt.
- [ ] Run focused tests, wheel/install smoke validation, repository CI-equivalent gates, and one
  independent non-countable review.
- [x] Remove operational Elves artifacts before final readiness while retaining this durable plan.

### Acceptance criteria

- [x] No provider or inference transport is invoked; the test explicitly removes all supported
  provider credential variables.
- [x] Demo, native verify, ODR export, and untampered standalone verify each exit `0`.
- [x] The native receipt, exported ODR, and verifier JSON report the same non-empty `receipt_id`.
- [x] The local source wheels are built and installed outside the repo; the subprocess working
  directory is outside the source tree.
- [x] Removing the required ODR claim verdict after export makes the installed standalone verifier
  exit `1` with failed schema conformance rather than accepting the artifact.
- [x] Existing focused receipt/export/walkthrough tests remain green and no existing test is
  weakened or removed.
- [x] Final product diff stays within eight files and roughly 500 changed lines, with no overlap
  against an active lane or open PR.

### Docs likely touched

- This plan only. Public docs change only if the executable contract proves a documented command
  false; no such drift is known at staging.

### Bounded review repair

The first exact-head independent review found one P2: target-installed wheels still inherited host
site packages, wheel builds could fetch build backends, Kimi was not scrubbed, and startup could
hydrate a local secure store. The one permitted repair now builds offline with `uv`, installs both
wheels and their lock-constrained dependency closure into a fresh virtual environment, runs
`pip check`, disables Secrets Manager, clears every `*_API_KEY`, and redirects secure storage to
an empty temporary path. Cumulative validation passed; one fresh terminal review remains required.

### Risk

The main risk is a slow or network-dependent packaging test. Prefer local wheel builds and
already-declared test dependencies; fail clearly in CI rather than skipping the contract.

## Later campaign units

The remaining four matrix cells are not authorized file scopes for this branch. After Batch 1
lands and current-main required checks are healthy, refresh all ownership/overlap inputs and stage
the next eligible cell from a fresh disposable worktree. Skip a cell when all expected files are
owned or when its repair would require a new public API, Tier 3-4 authority, credentials, or an
excluded subsystem.

## Non-Negotiables

- Refresh `origin/main`, ownership, leases, tasks, processes, open-PR files, reviewer reservations,
  required checks, disk, and outbox before every unit; reject any intersecting candidate.
- Do not weaken, delete, or rewrite an existing test merely to obtain green results.
- One bounded P2 repair is permitted after independent review; a second P2 parks the PR and ends
  the campaign with an exact handoff.
- Evidence is exact-head and evidence-last. Governed Tier 0-2 landing uses a regular merge commit
  only, never `--admin` or squash, and only when all live helper gates authorize it.
- Any product/API behavior expansion beyond an existing documented interface is a hard stop.

## Test Strategy

- **Primary contract:** `tests/cli/test_receipt_roundtrip.py` with plugin autoload disabled.
- **Receipt/export regression:** focused `tests/gauntlet/test_odr_export.py` and existing CLI verify
  tests that avoid PR #9015 paths.
- **Packaging proof:** local root and verifier wheels installed into isolated temporary targets;
  run the installed CLI/module from a non-repo working directory.
- **CI-equivalent gates:** use the repository's current required-gate commands discovered at the
  exact implementation head; do not edit workflows to change them.
- **Review:** independent non-countable exact-head review, then at most one bounded P2 repair and
  one terminal review.

## Successful Termination

Complete the persistent campaign goal on the first applicable condition:

1. All five journey cells pass from clean installations with no skipped contract tests or open
   P0-P2 findings.
2. Three consecutive discovery passes find no eligible unowned gap.
3. Twelve governed PRs merge and remaining gaps require new public APIs, Tier 3-4 authority,
   credentials, or overlapping ownership.
4. A second-review P2, unstable main, unavailable quorum transport, or ownership conflict prevents
   safe continuation.
