# PR #8945 Tier 4 Repair Spec

**Date:** 2026-07-08
**Status:** draft repair specification
**Target PR:** #8945 `feat(release): verify aragora-verify public install after publish`
**Target head:** `7b30e8ffbec35a4027d5bc70123b3abf9ca50208`
**Park record:** <https://github.com/synaptent/aragora/pull/8945#issuecomment-4918349774>
**Evidence blocker:** <https://github.com/synaptent/aragora/pull/8945#issuecomment-4897753812>

## Scope

This document turns the current-head #8945 park record into an executable repair
plan. It is intentionally docs-only. It does not edit workflow files, release
code, branch protection, model-quorum code, or the #8945 branch.

The actual repair remains Tier 4 because it changes
`.github/workflows/publish-aragora-verify.yml`, a release workflow. A future
implementer must have exact-head operator authorization before mutating that
workflow or attempting settlement.

## Current Blockers

At #8945 head `7b30e8ffbec35a4027d5bc70123b3abf9ca50208`, the dry-run review
found two concrete P2 blockers:

1. The public PyPI install verification runs after publishing but before GitHub
   Release creation, without bounded retry/backoff. PyPI index lag or raw
   version-string comparison can leave a package published while the expected
   release/tag path fails.
2. The public install probe runs inside the same `publish` job that has
   `id-token: write` and `contents: write`. Code fetched from the public package
   index can therefore execute while publishing/release credentials are still in
   job scope.

The repair must address both findings together. Fixing only retry/backoff while
leaving public package execution in a credentialed job is not acceptable.

## Target Workflow Shape

Keep the existing manual `workflow_dispatch` and confirmation gate. Split the
workflow into separate jobs with strictly separated authority:

1. `test`
   - Existing zero-Aragora dependency test job.
   - `permissions: contents: read`.

2. `publish`
   - `needs: test`.
   - Keeps the existing default-branch and `confirm == PUBLISH` guard.
   - Uses PyPI trusted publishing.
   - Declares job-level `permissions: {contents: read, id-token: write}`. GitHub
     Actions permissions are job-scoped; this specification does not imply that
     OIDC authority can be narrowed to only the PyPI upload step.
   - Must not install or execute the published package, or any package fetched
     from a public index, after upload while the job retains OIDC authority.
   - Must not create the GitHub Release.
   - Emits the requested version as a job output for later jobs.

3. `verify-public-install`
   - `needs: publish`.
   - Runs only after PyPI publish succeeds.
   - Target permission shape: `permissions: {}`.
   - Must not have `id-token: write` or `contents: write`.
   - Must not inherit a token with release or OIDC capability into the Python
     process that installs from PyPI.
   - Installs `aragora-verify==<version>` from public PyPI in a fresh virtualenv
     with `--no-cache-dir`.
   - Runs the post-publish probe from `scripts/verify_aragora_verify_publish.py`.
   - Uses bounded retry/backoff so normal PyPI index lag does not strand a
     published artifact before release creation.

4. `release`
   - `needs: verify-public-install`.
   - Runs only after the public install verification passes.
   - Grants `contents: write` only here.
   - Creates the GitHub tag/release.
   - Must not install or execute the just-published package.

If GitHub requires read-only checkout or artifact download in
`verify-public-install`, the repair must explicitly justify the narrowest
possible read-only permission and must drop/clear any token before running the
public install probe. The default target remains no release/OIDC-capable
credential in that job.

## Helper Repair Requirements

The #8945 branch introduces `scripts/verify_aragora_verify_publish.py`. Update
that helper on the #8945 branch so it has:

- bounded retry support for public install/version verification;
- an operator-tunable attempt count and delay, with sane defaults;
- bounded exponential or capped linear backoff;
- no unbounded polling;
- `--no-cache-dir` preserved for package installs;
- structured error messages that include the last failed command output;
- PEP 440-aware version comparison using `packaging.version.Version` instead of
  raw string equality;
- exact package-name checking so an unrelated CLI output cannot satisfy the
  guard accidentally.

The version check should accept semantically equivalent PEP 440 forms but still
reject a different version. Examples:

- requested `0.1.2rc1`, CLI output `aragora-verify 0.1.2rc1`: pass;
- requested `0.1.2`, CLI output `aragora-verify 0.1.1`: fail;
- malformed CLI output or package name mismatch: fail closed.

## Test Plan

Extend `tests/scripts/test_verify_aragora_verify_publish.py` on the #8945 branch
with focused unit coverage:

- retry succeeds after transient package-install failure;
- retry stops after the configured maximum attempts and reports the last
  failure;
- version comparison uses `packaging.version.Version` semantics;
- package-name mismatch fails even if the version substring matches;
- the helper continues to run the valid-receipt and spoofed-`key_id` probes;
- the helper preserves fresh virtualenv isolation and `--no-cache-dir`.

Add workflow-shape validation if the repo already has a workflow policy test
surface available in the #8945 branch. At minimum, the repair PR body must show
the final job permission map and the fact that public install verification no
longer runs in a job with `id-token: write` or `contents: write`.

## Acceptance Criteria

A repaired #8945 head is ready for fresh exact-head review only when all of the
following are true:

- `.github/workflows/publish-aragora-verify.yml` has separate publish,
  public-install verification, and release jobs.
- The `publish` job's `id-token: write` authority is explicitly job-scoped, and
  no public-index package installation or execution occurs after upload in that
  job.
- The public package install/probe does not run in any job with release or OIDC
  write authority.
- Release creation is gated on successful public install verification.
- PyPI index lag is handled by bounded retry/backoff, not by unbounded polling
  or by skipping verification.
- Version comparison is PEP 440-aware and fails closed on package-name mismatch.
- Focused helper tests pass.
- Workflow/job permission shape is documented in the PR body.
- No evidence is applied until a new exact head is reviewed cleanly under
  `docs/AGENT_OPERATING_CONTRACT.md` Section Conductor and
  `docs/REVIEW_AUTHORITY_PRINCIPLES.md`.

## Operator Reply Tokens

The repair can move forward when a repo-visible operator decision names one of
these tokens and the exact #8945 head:

- `authorize-8945-repair at 7b30e8ffbec35a4027d5bc70123b3abf9ca50208`:
  authorizes a bounded Tier 4 implementation of this repair spec on the #8945
  branch or a replacement repair branch.
- `settle-8945 at 7b30e8ffbec35a4027d5bc70123b3abf9ca50208`: accepts the
  current Tier 4 risk packet without this repair. This does not override any
  later live head/check/mergeability recheck.

Without one of these exact-head decisions, conductors should keep #8945 parked
and should not run evidence, settle, mark ready, merge, rerun CI, or edit the
release workflow.
