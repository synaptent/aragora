# Bounded Operator Delegation: Product-Readiness Pilot

**Status:** PROPOSED ONLY. Default off; no grant is issued by this document.
**Scope:** repository-wide policy design, campaign-specific authority.
**Risk:** Tier 4 authority proposal, including when its diff is Markdown-only.
**Baseline:** `ebe1bfd262f3c9f942679a0a6e2da24e3bd71534` (2026-09-07).

This proposal changes no enforcement, permissions, required checks, schedules,
or existing human-settlement semantics. Approval to prepare or publish this
draft is not approval to implement, activate, or merge it. A model verdict,
ordinary PR approval, or this document's presence on main issues no grant.

## 1. Purpose and Existing Authority

Reduce repetitive operator decisions for a finite product-readiness campaign
without delegating control of the authority system itself. Success is corrected
runtime behavior and effective regressions on main, not more PRs or consults.

Extend, rather than replace, the following existing primitives:

- [Agent Operating Contract](../AGENT_OPERATING_CONTRACT.md), particularly
  section Conductor, remains authoritative until an approved amendment lands.
- [Review Authority Principles](../REVIEW_AUTHORITY_PRINCIPLES.md) continues
  to define tier classification, independent review, dissent, and human gates.
- [Operator Delegation Policy](OPERATOR_DELEGATION_POLICY.md) supplies the
  allocation of routine decisions and irreducible operator-only tripwires.
- [Delegation Contract v0.1](DELEGATION_CONTRACT_V0_1_SPEC.md), implemented in
  [`delegation_contract.py`](../../aragora/policy/delegation_contract.py), supplies
  goal, scope, budget, and narrowing concepts. Its signature placeholder is not
  authentication. Existing unsigned contracts confer no new merge authority.
- [`predicate_oracle.py`](../../aragora/policy/predicate_oracle.py) supplies
  deterministic predicates, not proof of operator identity or approval.

Current policy wins every disagreement. In particular, v0.1 lists merge actions
among actions requiring explicit human approval. This proposal does not remove
that rule. Existing Bucket B closure heuristics cannot override the policy's
operator-only rule for closing another agent's PR. Closure is outside this pilot.

### Classification History: #7388

[Issue #7388](https://github.com/synaptent/aragora/issues/7388) remains open at
the baseline review. Its eight comments expand the original ADC classification
concern to other unclassified tranches; they do not provide the missing
operator classification. The issue records v0.1 landing through #7357 and an
unclassified continuation roadmap. It is not authorization for that roadmap.

Proposed classification for the operator: **bounded product-readiness policy
experiment**, not general ADC rollout or fleet autonomy. Approval must identify
the exact scope and update the canonical current-gate classification through
the normal approved path before implementation. No ADC stage, issue, label,
signing draft, dispatch hook, or schedule is revived by association. This
proposal does not close #7388 or claim to resolve its wider classification debt.

## 2. Non-Negotiable Boundaries

The policy can represent eligible actions across Tiers 0-4, but a tier number
alone never makes an action delegable. Eligibility is the intersection of the
landed policy, authenticated grant, actual changed surfaces, and live gates.

| Decision | Proposed treatment |
|---|---|
| In-scope branch implementation and validation | Explicit action and surface grant; existing ownership and safety rules still apply |
| Draft publication, ready transition, evidence application, protected squash | Separate permitted actions; one does not imply another |
| Tier 0-2 normal delivery | Current tier/check/review rules remain the minimum; a grant can narrow but not waive them |
| Eligible Tier 3/4 product work | Only after an explicit policy amendment allows named risk classes under a bounded operator grant; no blanket tier exemption |
| Authority policy, tier rules, validators, grant store, signer/trust roots, revocation controls, budgets, or audit enforcement | Always direct human approval; cannot be authorized by the mechanism being changed |
| Grant issuance, renewal, widening, reactivation, and operator revocation | Direct authenticated human action; no subdelegation or self-renewal |
| Holds, approval-required exceptions, unresolved dissent | Remain blocking; the delegate cannot lift or relabel them |

No grant in this pilot includes `--admin`, force-push, branch-protection or
workflow changes, destructive cleanup, branch/worktree deletion, production
deployment, credentials, automatic schedules, issue refill, or new paid-inference
authority. Existing reviewer reservations and provider budgets remain binding.
Already-held or parked objects do not become eligible because a grant exists.

## 3. Proposed Data Contracts (Not Implemented APIs)

Reuse the v0.1 goal/scope/budget vocabulary with an explicitly versioned,
authenticated extension. Do not reinterpret existing serialized records.
The following names describe required interfaces, not currently callable code.

### OperatorGrant

An immutable grant payload must include all of:

| Field group | Required content |
|---|---|
| Identity | Unique grant ID and version, schema version, repository immutable ID and canonical name, campaign ID, goal/spec digest |
| Issuer | Authenticated operator principal, approval-event reference and digest, issuance time, trust-root/key version |
| Delegate | Explicit agent principal and binding to its owner session/execution identity; a shared GitHub login is insufficient |
| Authority | Enumerated actions, eligible tier/risk classes, explicit denied actions, policy version and trusted enforcement digest |
| Surfaces | Enumerated branch/PR selectors, repository-relative write paths, semantic surface constraints and denials, acceptance-contract IDs |
| Acceptance | Finite acceptance matrix and digest, required validation commands/results, independent-review requirements |
| Lifetime | UTC issued/not-before/expiry times; revocation authority and freshness contract; no renewal by the delegate |
| Budget | One active PR; finite attempts, merges, wall time, and cost ceilings; zero subdelegation and zero additional paid-inference allowance |
| Authenticity | Canonical-payload digest, signature, algorithm/version, issuer key ID; unsigned or unverifiable records reject |

Missing or empty scope is **deny**, not unrestricted. This differs from v0.1
`AllowedSurfaces` empty-set behavior and must not be backported silently.
Unknown fields, schema versions, enum values, malformed dates, non-finite
budgets, and non-boolean authorization flags reject at the trust boundary.
Validate full changed paths, including old and new rename paths, deletions,
symlink targets, and generated inputs; path traversal or incomplete diff rejects.
Scope matching must use documented deterministic semantics, not model inference
or substring/glob-containment guesses. Semantic ambiguity requires human review.

A reusable grant need not enumerate future head SHAs, but each individual action
must bind an exact head. A new head invalidates prior action authorization and
evidence; it does not automatically authorize another repair or review attempt.
Scope or acceptance expansion requires a new direct operator decision.

### ActionRequest and AuthorizationDecision

`evaluate_delegated_action(grant, request, live_snapshot)` returns a deny or a
short-lived exact-action decision with machine-readable reason codes. It must
not issue a merge call. Inputs bind:

- Repository ID, PR number, head SHA, base SHA, branch and complete diff digest.
- Campaign/contract ID, grant ID/version/digest, action and unique action ID.
- Trusted policy/enforcement version, operator trust-root and revocation epoch.
- Required-check definition plus exact-head observations, validation and review
  artifact digests, tier, dissent/hold state, and snapshot observation times.
- Current owner/session/lease, grant budget version, reservation ID, and a
  deadline no later than the grant, lease, or snapshot freshness deadline.

Unknown or unavailable observations are not negative findings and never mean
clearance. Each reason reports which observation failed and its source/time.
All packet, steward, and executor consumers must agree on the same decision
inputs; disagreement is a blocker, not a reason to choose a permissive helper.

### DelegatedActionReceipt and Settlement Recognition

Use an authenticated, append-only action receipt linked to the grant and
decision above, containing validation/review references, actual actor, request
and result times, GitHub outcome/merge commit, budget transition, and recovery
state. A valid signature authenticates the issuer; it does not prove tests ran,
scope is correct, or review is sufficient. Verify those sources independently.

Keep `authorization_kind=direct_human` and
`authorization_kind=operator_delegated` distinct in proposed records and UI.
A delegated record must never write or masquerade as
`aragora/human-settlement`, or set `human_preapproval_recorded=true`.
Direct-human records retain their existing exact-head creator/approval rules.

An approved future gate may recognize delegated risk settlement/preapproval
through a separately named, versioned predicate, only for the grant's eligible
risk classes. Current consumers that understand only human settlement continue
to block rather than accepting a renamed boolean or forged human status.
Review evidence remains independent of either authorization kind.

## 4. Trust Model and Action Protocol

The operator's approval must authenticate a canonical structured payload, not
natural-language intent scraped from issue comments. Quoted text, code fences,
forwarded messages, account labels, PR titles, and model output are untrusted.
A digest or a signature made with a worker-readable shared secret does not
establish an independent operator trust boundary.

Recommended implementation decision: an operator-controlled signing interface
with a pinned verifier trust root inaccessible to workers. Choose the actual
signer, custody, canonical encoding, key rotation and recovery process at the
human design gate; this proposal creates none and reads no credentials.
Existing signing primitives may be reused only if they satisfy that isolation.

Trusted authorization evaluation runs from already-landed, approved code and
policy, not code in the PR under review, a dirty checkout, or its test process.
Untrusted PR tests must not receive the grant issuer's or merge executor's
credentials. Test artifacts and model reviews cannot change policy inputs.

Proposed execution sequence:

1. Validate issuer, delegate, repo, policy version, grant signature/lifetime,
   current revocation state, scope and campaign budget. Disabled/shadow mode
   returns no executable authority.
2. Acquire a current owner lease and atomic campaign action reservation, while
   enforcing one active PR. A stale historical lane is not permission to steal
   a live object. No ownership discovery or reservation means no action.
3. Capture exact-head gates and validation using the trusted snapshot interface.
   [PR #9880](https://github.com/synaptent/aragora/pull/9880) owns immutable
   `GateSnapshot` work and was open at this baseline. Coordinate its landed
   interface; do not duplicate or adopt its branch. Do not assume it has landed.
4. Require non-draft/MERGEABLE state and current allowed merge state, green
   required checks from an available authoritative surface, sufficient
   independent review, no blocking dissent, and no halt/steering/hold. All
   checks not proven optional remain blocking when their requiredness is unknown.
5. Immediately before mutation recheck the head, base-dependent proof,
   policy/grant/hold/revocation epochs, ownership, and reservation. Drift or
   elapsed freshness refuses and invalidates the action decision. No implicit
   recollection, repair, or retry is authorized by that refusal.
6. Persist an authenticated authorization-intent receipt before calling the
   executor. For a merge, request only normal protected squash with
   `--match-head-commit <exact-head>`, never `--admin`. A GitHub denial remains
   a denial; do not change protection or swap credentials to bypass it.
7. Reconcile the remote outcome and append the result receipt. A confirmed
   merge consumes the reserved merge budget exactly once; an unknown result
   retains the reservation and blocks another mutation until reconciled.

Budget and revocation checks need a trusted serialized store, not an
unprotected worktree JSON file. Compare-and-swap/transactions must enforce
reservation, grant version, and remaining budget together. An expired lease
does not refund an unresolved action. A failed audit write after remote success
produces a recoverable partial state, never a second merge or a green receipt.

GitHub and a local grant store are not one atomic transaction. Define the
executor dispatch point as the authorization linearization point: revocation
acknowledged before dispatch prevents the call; revocation during an in-flight
request blocks subsequent actions but cannot undo a merge already accepted by
GitHub. Report that residual race and reconcile the exact result. Do not claim
instant revocation of a completed or dispatched external action.

## 5. Threat Model and Required Denial Tests

Threat actors include a compromised worker, malicious PR content, a forged
operator message, a stale coordinator, and concurrent workers using one grant.
Provider outages, clock faults, and partial GitHub/store writes are also inputs.

| Attack or fault | Required mitigation and regression |
|---|---|
| Forged, unsigned, quoted, or fenced authorization; shared-login confusion | Reject without an independently authenticated structured grant/approval event |
| Wrong repo, PR, head, delegate, or action; replayed receipt | Bind all request fields and single-use action ID; reject cross-object reuse |
| Scope widening, renames, generated code, path traversal, empty allowlist | Validate complete semantic/path scope, deny first; reject unknown or missing data |
| Candidate alters its evaluator, policy, tiers, or grant records | Evaluate trusted landed code; authority-system changes cannot self-authorize |
| Expiry, clock uncertainty, revoked key/grant, stale revocation cache | Refuse mutation; no offline grace or self-renewal |
| Required-check lookup fails, missing/pending checks, red required row | Deny, even when cached rollups or optional rows appear green |
| Review liveness/grounding failure or blocking dissent | Retain normal review policy; approval record never substitutes for review |
| Head/base/policy/hold/owner moves after dry-run | Recheck before dispatch, invalidate decision, preserve original proof |
| Two workers consume last merge allowance or take one campaign | Atomic reservation admits at most one; loser makes zero mutation calls |
| Timeout after GitHub accepted merge; audit write fails | Preserve uncertain reservation, reconcile by exact action/head, no blind retry |
| Revocation races with dispatch | Deterministic ordering test plus explicit in-flight outcome, no false rollback claim |
| Runtime flag enabled without an authorized pilot | Require separate authenticated activation; configuration alone cannot authorize |

Every pre-dispatch rejection test must assert **zero merge calls**. Positive
tests assert exactly one protected, exact-head call and an authentic linked
receipt. Post-dispatch failure tests instead assert no duplicate call, retained
budget reservation, and truthful partial/reconciled state. Shadow evaluations
must have zero external mutations regardless of their would-allow result.

## 6. Compatibility and Enforcement Locations

The following are future integration sites, not edits in this proposal:

| Existing site | Required future responsibility |
|---|---|
| `aragora/policy/delegation_contract.py` and `predicate_oracle.py` | Versioned authenticated extension; deterministic validation without permissive legacy conversion |
| `scripts/check_work_lease.py` and `scripts/claim_active_agent_lane.py` | Bind current delegate/lease to a grant; do not turn a lease into operator authorization |
| `aragora/cli/commands/review_queue.py` and its helpers | Report direct/delegated authority separately, reject stale evidence and unknown gate inputs |
| `scripts/settle_one_pr.py` | Steward dry-run uses the same trusted decision and preserves all blockers |
| `aragora/swarm/auto_merge_green.py` and `scripts/merge_executor.py` | Consume exact authorized snapshot; enforce dispatch-time checks and protected merge only |
| Existing settlement receipt storage/recognition | Add a separately authenticated delegated record; preserve direct-human semantics |

Old records remain readable as historical planning data, not upgraded grants.
Old callers cannot activate delegation through omitted arguments or default
booleans. No wire/schema/status behavior changes until an approved versioned
implementation and migration land. CI, branch protection, schedules, and model
family eligibility do not change in this campaign.

The established Tier-4 human path must approve the proposal and enforcement
implementation. Higher-tier eligible product work remains blocked until both
the governing amendment and trusted recognition implementation are active.
Human-only risk classes remain human-only even after the pilot starts.

## 7. Migration, Pilot, and Rollback

1. **Proposal:** publish this draft and stop for human review. No active-policy
   edits, grant issuance, reviewer run, ready transition, or merge is included.
2. **Approved design:** record the narrow canonical classification for #7388,
   explicit eligible risk classes, interfaces, threat controls, and trust-root
   decision. Identify policy amendments; do not claim existing tripwires vanished.
3. **Default-off implementation:** separate reviewed PRs under existing human
   gates. Reuse the landed exact-head snapshot work; test packet/steward/executor
   parity and all denials. Missing dependency parks implementation, not takeover.
4. **Shadow:** replay frozen examples and compare decisions using a separate
   shadow budget namespace. Produce no grants with live authority, statuses,
   evidence posts, or merges. Compare false allows, false denials and missing data.
5. **Explicit pilot activation:** one human-issued campaign grant after clean
   shadow results and approved implementation. One active PR, no subdelegation,
   no added paid inference. Expire at seven days or ten merges, whichever occurs
   first, with finite attempts and no self-renewal. Never use ten as a merge quota.
6. **Review:** measure correct denials, successful authorized delivery, operator
   interventions, review/repair cost, and residual risk. No fleet-wide enablement
   or extension without a new direct human decision.

Rollback: disable future delegated dispatch, revoke the pilot grant, reconcile
in-flight actions, and fall back to existing direct-human workflows. Preserve
grants, branches, budgets, and receipts. Do not delete records, rewrite history,
automatically revert landed code, or relabel delegated records as human ones.
Automatic fail-closed suspension is allowed; changing revocation controls or
reactivating the pilot still requires direct human approval.

## 8. Proposed Pilot Acceptance Matrix

The finite candidate campaign is **Reliable Concurrent Debates**, not general
repo repair. Before any implementation grant, freeze exact files, test commands,
owner-clear proof, and a digest of these contracts. Already-correct behavior may
be verified without a gratuitous edit; it still needs a broken-witness check.

| ID | Required current-main behavior |
|---|---|
| RCD-01 | Cleanup cancels only explicitly owned tasks, never another arena or caller |
| RCD-02 | Exceptional/cancelled teardown is bounded, observable and idempotent; other cleanup still runs |
| RCD-03 | Finishing one arena preserves shared HTTP resources; application shutdown still releases them |
| RCD-04 | Simultaneous and repeated offline debates survive completion, cancellation and timeout without cross-session interference |
| RCD-05 | Jaccard cache capacity is enforced |
| RCD-06 | LRU eviction, hit promotion and clearing are correct |
| RCD-07 | Concurrent embedding reads return correct per-key vectors |
| RCD-08 | Concurrent embedding writes/readbacks preserve values and expose worker failures/incomplete joins |
| RCD-09 | Reputation concurrency verifies persisted aggregates, not only successful returns |
| RCD-10 | Session-cache expiry/cleanup preserves other sessions |

These local campaign IDs are not new CHR/ARCH entries. They confer no permission.
Use deterministic agents/local fixtures, repeated/order-varied concurrency tests,
targeted intentionally broken witnesses, and combined neighboring regressions.
Do not weaken assertions or add skips to obtain green results.

Exclude voting semantics, receipts, SDKs, global fixtures, workflows, installation
and packaging, Factory readiness/model-refresh/structural work, and
`aragora/debate/orchestrator_runner.py`. Refresh peer ownership before every unit.
No ownership information or a conflict means no action on that object.

Maintain one private campaign ledger with contract state, proofs, exact heads,
scope/owner checks, attempts, grants, landed commits, and blockers. After the
permitted repair/review budget, substantive dissent parks the object rather
than starting a second repair loop. Transport failures do not become code work.

Phase 1 ends at its human gate, not campaign success. Full success requires
approved delegation operating as specified, all ten contracts verified on
resulting current main, broken witnesses rejected, combined regressions passing,
and no unfinished owned delivery work. Three consecutive non-progress cycles
produce a blocked handoff. Pilot expiry or an exhausted review budget is not
completion. Production benefit and overall release readiness are separate claims.

## 9. Exact Human Decisions Still Required

No approval text in this draft is executable authorization. The operator must
make and authenticate these separate decisions, bound to the exact reviewed
artifact/version; placeholders, quoted copies, and inferred intent cannot count:

1. **Design/classification:** accept or revise this proposal at its exact PR head;
   classify this bounded experiment canonically without reviving the ADC roadmap.
2. **Authority boundary:** enumerate delegable actions/risk classes and explicitly
   amend conflicting human-per-PR rules. Keep authority-system control human-only.
3. **Trust and implementation:** approve signer custody, verifier trust root,
   canonical encoding, revocation/transaction store, freshness limits, and recovery;
   authorize a scoped default-off implementation under existing Tier-4 gates.
4. **Implementation acceptance:** approve the exact landed enforcement version
   after denial/parity/shadow evidence. This is not pilot activation.
5. **Pilot grant/activation:** authenticate the actual operator/delegate/repo,
   frozen campaign scope/acceptance digest, actions, limits, absolute expiry,
   revocation endpoint, and policy version. Seven days/ten merges are ceilings,
   not permission to issue a grant without those fields or to widen the scope.

**Current next action: human review of this draft only.** Do not implement,
issue a grant, advance peer PRs, or start the ten-contract campaign on its basis.
