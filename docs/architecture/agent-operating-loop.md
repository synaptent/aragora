# Agent Operating Loop

**Status:** Canonical projection contract, v1
**Runtime status:** Contract and executable traces only; source composition and
CLI wiring land in later governed batches.

This document defines the one agent-facing operating loop that projects Aragora's
existing sources of truth without replacing them:

`orient -> investigate -> plan -> propose -> authorize -> commit -> wait/cancel -> verify/reconcile -> learn -> handoff`

The projection is a cognitive instrument, not a new scheduler, database, ledger,
or authority service. Higher layers may compress lower layers, but cannot make
them more authoritative.

## Null hypothesis and authority

An agent should begin by assuming four layers are sufficient:

1. **Live authority:** exact Git anchor, halt, lease liveness, permissions, and
   protected checks, including the live settlement state behind a pull request.
2. **Durable state:** mission, session, work ledger, recorded settlement
   outcomes, and the outstanding obligations a lane must preserve, such as its
   lease.
3. **Commit evidence:** verified Nomic packs, planning results, and receipts bound
   to the exact repository identity and commit.
4. **Derived guidance:** work recommendations, beliefs, questions, and proposed
   actions.

The order above is strict. A lower layer can reveal a contradiction but cannot
override a higher-layer blocker. A `ready` work recommendation paired with a live
`BLOCKED` settlement therefore yields a blocked affordance and both records remain
visible.

## Linked abstraction tower

| Layer | Projection | Semantic owner |
|---|---|---|
| L0 | Runtime identity, permission, budget, custody | Existing capability and operator controls |
| L1 | Immutable source evidence and continuity | Git objects, native ledgers, receipts |
| L2 | Canonical repository, time, policy, and mission facts | Git, mission, work, session, lane, halt, checks |
| L3 | Derived observations and beliefs | Read-only orientation composition |
| L4 | `OrientationEnvelope` | `aragora.orientation.v1` |
| L5 | `InvestigationCase` and competing hypotheses | Bounded probe layer |
| L6 | Capability-valid `ActionAffordance` frontier | Existing capability authorization |
| L7 | `DecisionFrame` and canonical `DecisionReceipt` | Existing decision/receipt machinery |
| L8 | `PreparedEffect`, obligations, commit and observation | Existing mission/handoff contracts |
| L9 | `ExecutionEpisode`, verification, outcome attribution | Existing execution and verification owners |
| L10 | `ExperienceProposal` and `LoopHandoff` | Proposal and resumable handoff surfaces |

No layer stores a copied version of a lower owner. It records evidence handles
back to that owner. If an authority-bearing source is missing, malformed,
ambiguous, or anchor-drifted, the relevant action fails closed and names the next
legal action.

## `aragora.orientation.v1`

The normative machine contract is
[`docs/schemas/orientation.v1.json`](../schemas/orientation.v1.json). A full
envelope contains:

- exact repository identity, commit, tree, branch, and cleanliness;
- mission objective/progress, ranked work, and exact-commit Nomic state;
- evidence-backed facts separated from explicitly derived beliefs;
- questions and evidence deficits;
- capability-valid affordances with prerequisites, bounded cost, risk,
  permissions, reversibility, information value, and disposition;
- waits, leases, settlements, verification duties, and other obligations;
- source health, deterministic truncation facts, next legal actions, and the
  invariant `mutations: []`.

A compact `no_change` variant proves that the prior orientation fingerprint still
matches. Its sole `orientation_fingerprint` is the value matched from `--since`,
so the representation cannot encode two disagreeing fingerprints. It carries the
current anchor, its `generated_at`, and exactly one next legal action, but does
not repeat the full envelope. Without `generated_at` a caller could not tell a
fresh match from a stale one, which is the only question the variant answers.

Every derived record carries its lower-layer `basis_fingerprint`, evidence
references, authority, freshness, invalidators, and bounded cost. Evidence
handles use portable source URIs. Only source inputs and prepared-effect inputs
receive deterministic fingerprints; model reasoning must never be presented as
reproducible.

A derived record's own authority is always `derived_recommendation`; the cited
evidence handles retain their native authority. This prevents a synthesized
record from acquiring the authority of the live or durable state it summarizes.

## Freshness and failure semantics

- `fresh` means the evidence remains valid under its declared invalidators.
- `stale` remains visible for history but has no current authority.
- `unknown`, `unavailable`, or `ambiguous` on an authority-bearing source blocks
  dependent affordances.
- Anchor movement invalidates commit-bound Nomic results and decision evidence.
- Truncation is explicit, deterministic, and never silently removes a blocker.
  `truncation.emitted_bytes` is the exact byte length of the complete envelope
  serialized as compact, key-sorted UTF-8 JSON.
- A fact's authority cannot exceed the authority of any cited evidence handle.
- High-risk or permission-missing actions stop at `requires_authorization`; an
  orientation response never performs an effect.

## Agent-facing surfaces

`aragora orient` will read and compose this contract without launching models.
`aragora nomic plan` is the explicit model-bearing, commit-addressed planning
operation whose verified result may be discovered by a later orientation.
Existing `aragora nomic run` semantics remain unchanged.

## Executable traces

The fixtures under `tests/orientation/fixtures/` pin four required journeys:

1. fresh orientation;
2. interrupted resumption with active obligations;
3. uncertain high-risk action that requests authorization without an effect;
4. quiet no-change recheck within the compact response budget.

`tests/orientation/test_orientation_contract.py` validates the schema, authority
monotonicity, evidence metadata, no-effect rule, response budget, and links from
the thesis, roadmap, flywheel, mission, and Nomic plans. Runtime implementation
must conform to these traces rather than weakening them.
