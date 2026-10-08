# Project Learnings

## Promotion Rules

Keep only stable, reusable, actionable facts here. Batch chronology and one-off outputs
belong in the execution log. Retire rather than silently delete facts that later become stale.

## Repo Conventions

- 2026-07-22: `aragora/live/package.json` already uses npm `overrides` for bounded
  transitive dependency remediation; preserve the existing Next.js version unless a
  separate plan explicitly authorizes changing it. This lane later received exact
  operator approval for the security-fixed Next.js 16.2.11 patch after new advisories
  affected 16.2.9.
- 2026-07-22: Dependency/security PRs are operator-review-required and must not be
  treated as eligible for autonomous settlement or merge.

## Validation and Tooling

- 2026-07-22: `npm audit --omit=dev` still includes optional production dependencies.
  On exact main `24ecf7e79a`, it reports indirect `sharp@0.34.5` through Next.js.
- 2026-07-22: For native/platform dependency families, compare parsed
  `package-lock.json.packages` keys before and after; a short `git diff --stat` can hide
  many distinct transitive package changes.

## Review Heuristics

- 2026-07-22: A security-fixed version is not automatically a compatibility-safe
  version. Read upstream release notes, engine requirements, the parent's declared
  semver range, and then prove the real build surface.

## Product and Domain Invariants

- 2026-07-22: `aragora/live` must build on the operator-approved stable
  `next@16.2.11` security patch in this lane. Canary packages and later Next.js
  releases remain outside scope.

## Known Traps

- 2026-07-22: `aragora/live/Dockerfile` historically pinned Node 18.19 even while
  the live app's Next 16.2.11 dependency requires Node >=20.9. Dependency reviews
  must check deploy and self-hosted runtime images, not only local build success.
- 2026-07-22: sharp 0.35.0 is the first advisory-patched version, but upstream marks
  that release as breaking and raises the Node requirement to >=20.9.0. Next 16.2.11
  declares `sharp: ^0.34.5`, which excludes 0.35.x.
- 2026-07-22: The current lockfile contains 26 sharp-family package entries. Measure
  the actual changed set and honor the operating contract's >5 transitive-change halt.
- 2026-07-22: On the staged npm 11 lock, a `sharp: ^0.35.3` override changes 29
  transitive entries: 27 sharp/@img entries plus `@emnapi/runtime` and sharp's nested
  `semver`. This exceeds the repo's automatic dependency authority and requires exact
  operator approval even though the product-file diff is only two files.

## Retired Learnings

- None.
