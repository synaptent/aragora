---
title: Aragora Docs
description: Auditable execution control plane for AI-assisted decisions.
---

# Aragora Documentation

Aragora is an auditable execution control plane for AI-assisted decisions:
multi-model review in, a verifiable Decision Receipt out. It uses multi-model
review, receipts, provenance, and truthful gates so software and organizational
decisions can be inspected instead of merely trusted.

This site is the published view of the canonical docs in `docs/`. If you are
reviewing the project cold, start with the proof path below before diving into
the full API surface.

## Review Path

- [Cold Reviewer Guide](/docs/contributing/cold-reviewer-guide) explains what
  Aragora is good for today, what is aspirational, and how to verify the serious
  surfaces quickly.
- [Supported API Surface](/docs/api/supported-surface) separates stable,
  beta, internal, and experimental contracts so the generated API catalog is not
  mistaken for a blanket stability promise.
- [Benchmark Truth Status](/docs/contributing/b0-benchmark-truth-status) and
  [Rescue Productization Status](/docs/contributing/tw03-rescue-productization-status)
  are the recurring proof surfaces for the current reliability wedge.

## Build Path

- [Getting Started](/docs/getting-started/overview)
- [GitHub PR Review API](/docs/api/github-pr-review)
- [API Reference](/docs/api/reference)
- [Canonical Goals](/docs/contributing/canonical-goals)
- [Evolution Roadmap](/docs/contributing/aragora-evolution-roadmap)

## Current Boundary

Today, Aragora is strongest as a proof-first review and execution governance
layer for bounded AI-assisted software work. The maximalist direction is larger:
an organization substrate for the full idea-to-goal-to-plan-to-action-to-receipt
loop. The roadmap is valuable only when each stage keeps the same fail-closed
contract: explicit evidence, review, receipts, and truthful stops.
