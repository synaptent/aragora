# AI Attack Vector Resistance: Design Document

**Date:** 2026-03-05
**Status:** Approved
**Branch:** Strategic documentation updates

---

## Problem Statement

LLM attack research (2025–2026) has produced two novel attack classes with direct relevance to
Aragora's multi-agent architecture. Neither is adequately represented in the current canonical docs:

### Brainworm-class: Context Injection / Config C2

Semantic hijacking of AI agents via trusted configuration files. No binary artifacts required —
the attacker injects natural language instructions into files the agent trusts by convention
(`CLAUDE.md`, `MEMORY.md`, retrieved Obsidian notes, fetched tool output). The attack exploits
**trust domain collapse**: the model's context window does not distinguish between operator
instructions and retrieved data. A sufficiently subtle injection in a trusted file can redirect
agent behavior across sessions without triggering any signature-based detection.

**Why it matters for Aragora:** The Nomic Loop ingests `CLAUDE.md`, memory files, and retrieved
knowledge as context. A compromised knowledge source or tampered config file could influence agent
proposals in ways that survive casual review but accumulate effect across cycles.

### OBLITERATUS-class: Weight Surgery

SVD-based projection techniques that remove refusal behaviors from open-weight LLMs by operating
directly on model weights, not inputs. A lobotomized model is indistinguishable from a legitimate
endpoint at the API level — it accepts the same request format and returns plausible-looking
responses, but without safety-trained constraints.

**Why it matters for Aragora:** The execution gate enforces provider + model-family diversity, but
relies on configured ensemble quality. An open-weight participant that has been weight-surgered
cannot be detected through normal API interaction — it must be caught by behavioral divergence in
debate, not by metadata inspection.

---

## Current State

Aragora has **emergent defenses** against both attack classes by virtue of its architecture:

- Adversarial critique loop: compromised proposals are challenged by intact heterogeneous peers
- Execution gate: provider + model-family diversity means a single lobotomized model is outvoted
- Trickster: hollow consensus detection flags unanimous agreement that lacks genuine critique
- Brier calibration: model credibility is weighted by historical accuracy, not just current output

These are **real defenses** — not marketing claims. But they are not:
- Documented as canonical security properties
- Surfaced as a competitive differentiator
- Backed by explicit roadmap items to close the remaining gaps

The threat model (Section 3.4) previously lacked explicit rows for context/config poisoning and
authority collapse attacks. Section 3.6 (Model & Consensus Integrity) was missing entirely from
the version in this worktree.

---

## Design Decision

**Option C selected**: Add "AI Attack Vector Resistance" as a first-class section across three
documents, structured as a **two-table defense registry** (proven defenses vs. gaps with roadmap
items). This is more honest than claiming a new pillar for aspirational capabilities.

---

## Defense Taxonomy

### Proven Defenses (structural, by design)

| Attack | Why It Fails Against Aragora | Strength |
|--------|------------------------------|----------|
| Prompt injection → single model | Adversarial critique loop: compromised proposals are challenged; one bad output doesn't reach consensus without N-1 agreeing agents ignoring critique | Strong |
| Jailbreak / sycophancy on one model | Trickster detects hollow consensus; RhetoricalObserver flags rhetorical patterns; dissent is recorded in receipt | Strong |
| OBLITERATUS-class (refusal ablation on open-weight participant) | Execution gate enforces provider + model-family diversity; lobotomized model must outvote intact heterogeneous peers across multiple rounds | Medium |
| Single-source hallucination | Cross-verification phase; consensus proof requires independent agreement; dissent capture preserves minority positions | Strong |
| Correlated failure / shared blind spot | Heterogeneous models from different training lineages and RLHF targets reduce correlated failure surface | Medium |

### Defense Gaps (with roadmap items G1–G4)

| Gap | Attack Vector | Planned Mitigation | Roadmap ID |
|-----|--------------|-------------------|------------|
| No signed context manifests | Brainworm: malicious `CLAUDE.md`/memory file passes undetected into agent context | Cryptographic signing of trusted context sources; agents verify provenance before elevating trust | G1 |
| No trust-tier taint tracking | Context authority collapse: injected instructions propagate through debate without flag; tainted proposals appear normal in receipts | Taint flag propagates: if retrieved/injected context influences a proposal, receipt carries taint annotation | G2 |
| No runtime model attestation | OBLITERATUS endpoint substitution: modified open-weight model served behind expected alias | Behavior-signature challenge at registration; periodic behavioral probing against known-good baselines | G3 |
| No mandatory external verification gate | Correlated failure: all models share blind spot; no independent check before high-impact execution | External verifier requirement for decisions above configurable impact threshold | G4 |

---

## Files Updated

1. **`docs/CANONICAL_GOALS.md`** — new `### AI Attack Vector Resistance` subsection under Foundational Thesis
2. **`docs/plans/ARAGORA_EVOLUTION_ROADMAP.md`** — new `## Security-as-Architecture` section before Phase 0
3. **`docs/security/THREAT_MODEL.md`** — added context-poisoning rows to §3.4, new §3.6 (Model & Consensus Integrity), updated Risk Matrix and Testing Priorities

---

## Implementation Scope

This design doc covers **documentation updates only**. Implementing G1–G4 is future engineering
work. Each gap item is surfaced in the Evolution Roadmap as a named roadmap item so it can be
tracked, prioritized, and owned.

Relative prioritization of G1–G4 when engineering capacity is available:

1. **G2 (Taint tracking)** — highest leverage; requires debate orchestrator changes; surfaces
   attack attempts in receipts where humans can see them
2. **G1 (Signed context manifests)** — blocks the injection point; requires context ingestion
   pipeline changes + key management for signing
3. **G4 (External verification gate)** — closes the correlated-failure gap for high-stakes
   decisions; can be implemented as an opt-in policy flag initially
4. **G3 (Runtime model attestation)** — most complex; open-weight models are diverse; behavioral
   fingerprinting is probabilistic not cryptographic

---

*This document is the output of the brainstorming/design phase. Implementation planning tracked
in writing-plans output.*
