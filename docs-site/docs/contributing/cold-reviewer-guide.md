---
title: Cold Reviewer Guide
description: Cold Reviewer Guide
---

# Cold Reviewer Guide

Last updated: 2026-04-24

This guide is the shortest serious path for a reviewer, auditor, investor, or
new maintainer who is inspecting Aragora without prior context.

## One-Sentence Thesis

Aragora is an auditable execution control plane for AI-assisted decisions:
multi-model review in, a verifiable Decision Receipt out. It coordinates
heterogeneous agents, requires evidence-backed review, preserves receipts and
provenance, and stops truthfully when a task lacks enough support to proceed.

## What Aragora Is Good For Today

Aragora is strongest when the work is too consequential for a single model
answer but still bounded enough to verify:

- PR review and merge settlement where multiple agents inspect the same diff,
  dissent is preserved, and merge readiness is tied to evidence.
- Autonomous or semi-autonomous software execution where work orders, validation
  plans, receipts, and stop states matter more than raw coding speed.
- Decision records that need provenance, claims, disagreement, and later
  reassessment instead of ephemeral chat transcripts.
- Calibration loops that compare agent recommendations against later outcomes.
- Fail-closed automation where admin-scoped approvals and truth surfaces are
  required before high-impact actions advance.

## What Is Still Aspirational

The long-term roadmap is larger than the current wedge: an organization substrate
for the full `idea -> goal -> plan -> action -> receipt -> later settlement`
loop. The repo contains real building blocks for that direction, but reviewers
should not judge every future-facing document as a shipped product claim.

The near-term discipline is proof-first: every stage should add a smaller,
inspectable capability with tests, receipts, and clear stop/go semantics before
the project expands the surface area.

## Why This Is Not Just Another Agent Framework

Generic orchestration, chat UX, and coding-agent execution are likely to be
replicated by large model providers and workflow frameworks. Aragora's more
defensible layer is the governance substrate around those executors:

- vendor-neutral review and dissent across heterogeneous agents
- durable receipts, claims, and provenance
- calibrated trust based on observed outcomes
- explicit admin approvals and bounded delegation
- executable claims and stale-evidence repair loops
- API and SDK contracts separated from internal experimental machinery

## Inspect These First

1. [README](https://github.com/synaptent/aragora/blob/main/README.md) for product framing and install paths.
2. [Supported API Surface](../api/supported-surface) for what is stable, beta,
   internal, or experimental.
3. [Canonical Goals](./canonical-goals) and
   [Evolution Roadmap](./aragora-evolution-roadmap) for the staged
   maximalist thesis.
4. [Next Steps Canonical](./next-steps-canonical) for current execution
   priorities.
5. [B0 Benchmark Truth Status](./b0-benchmark-truth-status) and
   [TW03 Rescue Productization Status](./tw03-rescue-productization-status)
   for recurring proof surfaces.
6. [GitHub PR Review API](../api/github-pr-review) for the current practical
   control-plane wedge.

## Fast Verification

Run these from the repository root:

```bash
python scripts/inspect_cold_review_surface.py
python scripts/check_version_alignment.py
npm run build --prefix docs-site
```

The cold-review inspector checks the public framing, docs-site announcement,
reviewer/auditor entry points, supported-surface document, live queue alignment,
and OpenAPI scale summary. It is intentionally small and dependency-free so it
can run in local review, CI, or branch preflight.

## Quality Bar For New Work

New capabilities should be easy for a cold reviewer to classify:

- The user-visible promise is explicit.
- The supported API or CLI contract is documented.
- The validation command is listed and reproducible.
- The receipt, audit, or provenance surface is inspectable.
- Failure modes stop truthfully instead of silently degrading.
- Experimental pieces are labeled experimental and kept out of the stable
  contract until they have proof.

## Red Flags To Avoid

- Treating the generated OpenAPI catalog as a stability promise for every route.
- Adding broad agent/provider support without stronger receipts or verification.
- Letting stale roadmap docs override current proof surfaces.
- Claiming organization-scale autonomy when the shipped wedge is bounded
  software execution and review governance.
- Hiding missing evidence behind `healthy`, `success`, or `green` labels.

## Bottom Line

The project is valuable if it keeps tightening the gap between AI-generated work
and auditable organizational trust. The next phase should bias toward fewer,
better-proofed surfaces: PR settlement, receipts, calibration, review gates,
proof-carrying code, and cold-reviewable documentation.
