# Plan: Provider-Neutral Production Canary and AWS Retirement

## Mission

Restore a verifiable Aragora API on provider-neutral runtime seams instead of attempting to
recover the retired AWS control plane. The migration will use the existing container runtime,
standard PostgreSQL configuration suitable for Supabase, mounted secret custody, and external
health, WebSocket, persistence, and signed-receipt verification. AWS workflow and governance
cleanup remains a separate Tier-4 PR after the replacement canary is proven.

## Authority and sequencing

- The operator approved this migration direction on 2026-08-19.
- This is Tier 4 because it changes secret and deployment behavior. Human implementation
  preapproval is recorded by the approving instruction; exact-head human risk settlement is still
  required before merge.
- No merge-on-green authority was granted. This run never merges.
- The AWS retirement/noise PR is not part of this branch. It may be staged only after live canary
  proof and a fresh exact-scope inventory.

## Scope

### In scope

- Provider-neutral mounted-directory secret loading while retaining AWS compatibility.
- Non-AWS Ed25519 ODR signing-key custody without raw private keys in environment variables.
- A bounded canary container configuration for an external PostgreSQL `DATABASE_URL`, local Redis,
  and Cloudflare tunnel routing.
- External verification of health, WebSocket upgrade, persistence, public signing-key discovery,
  signed receipt production, and offline signature validation.
- Reclassifying issue #9391 as the migration ledger and recording exact evidence there.
- Preparing the exact follow-up inventory and authorization packet for AWS workflow/doc retirement.

### Out of scope

- AWS login, MFA, billing recovery, EC2/SSM diagnosis, restart, or redeploy.
- Changes to GitHub Actions, branch protection, required checks, governance, or settlement helpers.
- Provider-specific branches in application code.
- Replacing standard PostgreSQL access with Supabase-specific application persistence.
- Reusing or modifying the stale July 17 contingency worktrees or their uncommitted files.
- Creating a paid Hetzner server without an existing authorized target or explicit budget.
- Settling or merging either this PR or the later AWS-retirement PR.

## Batches

### Batch 1: Provider-neutral secret custody

**Tasks:**

- Extend `aragora/config/secrets.py` with a mounted-directory source selected by configuration.
- Preserve existing AWS and development environment behavior.
- Make strict production mode accept protected mounted files for critical secrets while continuing
  to reject raw environment fallbacks.
- Add presence/audit source labels and focused tests for precedence, permissions, refresh, and
  fail-closed behavior.

**Acceptance criteria:**

- Focused secret tests pass with AWS compatibility preserved.
- Directory paths and filenames are validated; secrets never appear in logs or error text.
- A configured invalid directory fails closed for critical secrets.
- No provider name appears in consuming application modules.

**Risk:** `SecretManager` is widely consumed; precedence and strict-mode regressions are the main
risk and require a regression-focused review.

### Batch 2: Non-AWS ODR signing

**Tasks:**

- Extend the existing ODR signer with protected mounted-file key custody.
- Retain the current AWS secret-id path for compatibility.
- Refuse missing, non-regular, overly permissive, empty, or invalid PEM files without falling back.
- Add a bounded provisioning helper or documented operator command if the existing signing helpers
  cannot generate a mode-0600 Ed25519 key safely.

**Acceptance criteria:**

- Signing tests cover successful file custody and every fail-closed boundary.
- Existing AWS signer tests remain green.
- The public key and signed receipt verify through the existing offline verifier.
- Private key bytes never transit an environment variable or committed file.

**Risk:** Signing-key precedence must never silently downgrade to unsigned receipts or another
backend after an explicitly configured file fails.

### Batch 3: Canary deployment pack

**Tasks:**

- Add a small deployment pack that uses the existing Aragora container image and standard runtime
  variables.
- Configure external PostgreSQL through `DATABASE_URL`, local Redis, mounted secrets, and an
  optional Cloudflare tunnel sidecar.
- Keep Hetzner, Supabase, and Cloudflare choices in deployment configuration and operator docs.
- Pin image/runtime inputs and document rollback without editing workflows.

**Acceptance criteria:**

- `docker compose config --quiet` validates the pack with placeholder non-secret inputs.
- No database or private-key secret is embedded in compose, examples, or generated output.
- Standard self-hosted deployment remains unchanged.
- The pack documents exact prerequisite, deploy, rollback, and evidence commands.

**Risk:** Container orchestration can accidentally weaken existing security defaults or create a
parallel deployment architecture; the pack must remain small and reuse the existing image/runtime.

### Batch 4: External canary verifier

**Tasks:**

- Compose existing health, WebSocket, and receipt-verification helpers into one bounded verifier.
- Add persistence round-trip or database connectivity proof that does not expose data or secrets.
- Emit a machine-readable evidence artifact bound to URL, image SHA/digest, key fingerprint, and
  verification time.
- Add offline tests with local fixtures and failure-path coverage.

**Acceptance criteria:**

- The verifier checks `/healthz`, `/api/health`, WebSocket upgrade, persistence, signing-key
  discovery, signed receipt generation, and independent signature verification.
- Failure in any required surface produces a nonzero exit and a redacted artifact.
- Focused verifier tests, lint, and typecheck pass.
- Existing standalone verification helpers keep working.

**Risk:** A shallow HTTP-200 check could falsely claim readiness; proof must exercise all named
contracts and bind evidence to the deployed artifact.

### Batch 5: Live canary and evidence

**Tasks:**

- Recheck owner/lease, runner floor, exact branch head, and credentials without printing secrets.
- Use an existing authorized Hetzner target and Supabase project; do not create paid infrastructure
  without separately recorded target/budget authority.
- Deploy the exact current image through the canary pack and route a canary hostname through
  Cloudflare.
- Run the verifier, restart once, rerun persistence and signing checks, and record rollback proof.
- Update #9391 with the exact evidence and remaining blockers.

**Acceptance criteria:**

- External evidence is green twice, including once after restart.
- Evidence records deployed SHA/digest, Supabase persistence result, WebSocket result, and signing
  key fingerprint without secret material.
- Rollback is tested or dry-run proved and no paid/long-running resource is left ambiguous.
- If Hetzner or Cloudflare access is unavailable, stop only this batch with the exact missing access
  and preserve the review-ready implementation work.

**Risk:** This batch mutates external infrastructure. Every action must be reversible, target-bound,
and supported by live credentials and an existing authorized target.

### Batch 6: AWS retirement follow-up packet

**Tasks:**

- Inventory AWS-only deploy, monitor, runbook, governance, and compliance surfaces after canary
  evidence is green.
- Classify what should be disabled, archived, corrected, or preserved as history.
- Post an exact, bounded Tier-4 implementation-authorization request for a separate draft PR.
- Do not edit workflows or protected governance in this branch.

**Acceptance criteria:**

- The inventory names exact files and intended disposition.
- #9391 links the canary evidence and the separate follow-up scope.
- No AWS workflow or governance file appears in this PR diff.
- The run stops with a paste-ready exact authorization request; it does not settle or merge.

**Risk:** Combining cleanup with migration would make rollback and review ambiguous; the follow-up
must remain a separate exact-scope Tier-4 lane.

## Non-negotiables

- Do not spend cycles on AWS recovery or diagnosis.
- Do not place provider selection in application code.
- Do not expose, print, commit, or transmit private secrets in review/evidence artifacts.
- Do not touch workflows, protected governance, branch protection, settlement, or merge helpers.
- Preserve the stale contingency worktrees untouched.
- Never merge; exact-head OWNER settlement remains a separate human action.

## Test strategy

- Locked environment: `uv run --locked --extra dev --extra test`; install the repository's
  CI-side-loaded `boto3` and `cryptography` packages into the worktree venv for focused tests.
- Focused baseline: `tests/config/test_secrets.py`, `tests/gauntlet/test_odr_signing.py`, and
  `tests/scripts/test_verify_receipt.py`.
- Static gates: targeted Ruff and mypy on changed Python files.
- Deployment gate: `docker compose config --quiet` with placeholder inputs; live container proof
  only when a Docker/remote runtime is available.
- Final gate: cumulative diff review, focused tests, current required checks, independent
  non-countable review, and exact-head Tier-4 readiness packet.

## Known staging constraints

- Current main at staging: `6955ab420ed959dcce9cece4120b298453adc9c3`.
- Runner floor is healthy: five online runners labeled `aragora`.
- Supabase CLI authentication is available.
- Local Docker daemon, Hetzner authentication, and Cloudflare tunnel authentication are not
  currently available. These do not block Batches 1-4, but they block the live deployment unless
  a remote target or credentials become available.
- Repository-wide Ruff is ambient-red on
  `.github/workflows/contract_drift_trusted_launcher.py`; targeted touched-file Ruff is the local
  gate unless that unrelated main failure is repaired separately.
- Two stale July 17 worktrees contain uncommitted ODR signing experiments with no live process,
  lane, lease, or PR. They are prior art only and remain untouched.
