# AWS Retirement Migration Execution Log

## Run Digest

- **Last updated:** 2026-08-19 09:31 America/Chicago
- **Current phase:** Launched; pre-Batch-1 gates
- **Active batch:** Batch 1: Provider-neutral secret custody
- **Last completed batch:** none
- **Next exact batch:** Batch 1: Provider-neutral secret custody
- **Active PR:** #9800
- **Docs promoted:** none
- **Elves Report:** not generated

## Session Setup: 2026-08-19 09:10 America/Chicago

**Phase:** staging complete

**Branch:** `codex/aws-retirement-migration-9391`

**PR:** #9800, draft, `operator-review-required`; verify the live exact head at launch after the
final staging-receipt push.

**Worktree:** `$HOME/.codex/worktrees/aws-retirement-migration-9391-20260819/aragora`

**Base/collision tripwire:** `6955ab420ed959dcce9cece4120b298453adc9c3`

**Lease:** `803c32bd-760`, work ID `issue:9391`, owner
`codex-elves-aws-retirement-9391-20260819`

**Authority:** operator approved the provider-neutral migration direction and ordered execution.
The run records Tier-4 implementation preapproval for this bounded migration plan; it does not
infer exact-head settlement or merge authority.

**Batch breakdown:**

1. Provider-neutral secret custody.
2. Non-AWS ODR signing.
3. Canary deployment pack.
4. External canary verifier.
5. Live canary and evidence.
6. AWS retirement follow-up packet, without workflow edits.

**Live grounding:**

- Issue #9391 remains open and still describes AWS recovery as the next action.
- Current main is `6955ab420ed959dcce9cece4120b298453adc9c3`.
- Five runners labeled `aragora` are online.
- No relevant open PR was found from the initial title/branch scan.
- A stale `contingency/hetzner-prod-pack` branch has two July 17 worktrees with uncommitted ODR
  signing experiments, no process, lane, lease, or PR. Preserved untouched.
- The fresh branch had no steering message before claim.

**Architecture survey:**

- `aragora/config/secrets.py` is the shared AWS-first secret abstraction and strict production
  policy surface.
- `aragora/gauntlet/odr_signing.py` directly loads a dedicated AWS secret.
- `deploy/self-hosted/docker-compose.yml` is the reusable container baseline.
- `deploy/helm/aragora/values-supabase.yaml` proves Supabase is already standard external
  PostgreSQL, not an application-specific backend requirement.
- `scripts/verify_websocket.sh` and `scripts/verify_receipt.py` provide existing verification
  primitives to compose rather than replace.

**Preflight:**

- Git remote, push dry-run, and `gh` authentication: PASS.
- Dedicated worktree and branch ownership: PASS.
- Lease: PASS.
- Focused tests after matching CI-side-loaded packages: 125 passed.
- Targeted Ruff: PASS.
- Targeted mypy: PASS.
- Existing self-hosted Compose config: PASS with expected missing-password warning.
- Repository-wide Ruff: WARN, ambient failure in
  `.github/workflows/contract_drift_trusted_launcher.py`; protected and outside scope.
- Docker CLI installed but daemon unavailable: WARN.
- Supabase CLI authenticated: PASS.
- Hetzner and Cloudflare auth: unavailable; live canary Batch 5 gated.
- No paid or long-running resource started.
- Issue #9391 was re-titled as the AWS-retirement/provider-neutral migration ledger. The complete
  original incident body remains preserved under its historical section.

**Decision notes:**

- Do not salvage or clean stale contingency worktrees. They are user-owned prior art.
- Keep the first PR under the 800-line discipline and exclude workflow/governance cleanup.
- Treat the current approval as bounded Tier-4 implementation preapproval only. Require separate
  exact-head human settlement before merge.
- Do not create paid Hetzner infrastructure without a named existing target or explicit budget.

**Launch readiness:** READY after the issue ledger is updated and this receipt commit is pushed.

**Launch prompt:**

> The run is staged. Start now. Use
> `$HOME/.codex/worktrees/aws-retirement-migration-9391-20260819/aragora` and read
> `docs/elves/aws-retirement-migration-9391/survival-guide.md` first, followed by
> `.elves-session.json`, learnings, plan, and execution log. Set the Stop Gate to no, re-read
> steering, renew lease `803c32bd-760`, verify the live PR #9800 head matches the checked-out and
> remote branch tip, recheck current-main overlap and runner health, and
> create `elves/pre-batch-1`. Execute Batches 1-4 through implementation, validation, independent
> non-countable review, documentation, commit, and push. Then attempt Batch 5 only with an existing
> authorized target and live Hetzner/Cloudflare/Supabase access; otherwise record the exact access
> blocker and continue to Batch 6. Do not attempt AWS recovery, touch workflows or protected
> governance, create paid infrastructure, collect quorum evidence, settle, merge, or modify the two
> stale contingency worktrees. There is no hard stop.

**Next:** commit/push this final staging receipt, poll PR checks, then stop at the mandatory
fresh-launch boundary.

## Launch: 2026-08-19 09:31 America/Chicago

The operator launched the finite run, supplied exact PR head
`a9b5de83502426ff83415e64b9b27dc562161e1d`, and removed any hard deadline. The Stop Gate is
now `no`; checkpoints do not permit stopping. Pre-Batch-1 gates are in progress before any product
edit.

**Pre-Batch-1 gates:**

- Steering: no matched lane and no messages; no receipt required.
- Lease: renewed lease `803c32bd-760` through `2026-08-19T22:32:38Z` for the recorded owner.
- Exact head: checkout, `origin/codex/aws-retirement-migration-9391`, and PR #9800 all matched
  `a9b5de83502426ff83415e64b9b27dc562161e1d`.
- Main overlap: `origin/main` remained `6955ab420ed959dcce9cece4120b298453adc9c3`, the merge base;
  there was no new overlap to reconcile.
- Runner floor: five online `aragora` runners, all idle at the check.
- PR required checks: `lint`, `typecheck`, `sdk-parity`, `Generate & Validate`,
  `TypeScript SDK Type Check`, and `aragora-merge-quorum` all passed on the staged head.
- Main health: the non-required scheduled `Uptime Monitor` is red because the retired AWS-backed
  production endpoint returns Cloudflare 522. This is the known migration trigger, not a required
  main check and not authority to attempt AWS recovery.
- Rollback tag: the exact requested local name `elves/pre-batch-1` was already occupied by unrelated
  historical commit `17af7a7a590e3e04543e1f0f1b9df2faf039dc96`. It was preserved. Created and pushed the
  run-qualified tag `elves/aws-retirement-migration-9391/pre-batch-1` at the verified PR head.

**Decision:** proceed with Batch 1. The only red live signal is non-required AWS uptime noise that
the approved migration is designed to replace; all required branch checks and the runner floor are
healthy.
