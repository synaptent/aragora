# Operator Guide: Questions That Produce Action

Use these prompts when a session is producing plausible strategy but not a
testable decision or durable result. They are operator practice, not a product
subsystem. The product-side question batteries for receipts, intake, modes, and
harvest remain tracked in [#8815](https://github.com/synaptent/aragora/issues/8815).

## Common Contract

Every prompt below follows the same contract:

1. Start from live evidence, not transcript assumptions.
2. Name the outsider, belief, object, or assumption being tested.
3. Produce a repo-visible artifact: a test result, issue, focused patch, receipt,
   or explicit no-action rationale.
4. Authorize at most one bounded, reversible action when the evidence is clear.
5. Stop at ownership, human-risk, destructive, security, or ambiguous-product
   boundaries. Report the exact missing decision instead of routing around it.

Reusable wrapper:

```text
Start from live truth. Evaluate this question: <question>.

Name the evidence that would prove the current belief wrong. Inspect that
evidence directly. If it supports exactly one bounded, reversible action within
the stated authority, take that action and verify the result. Otherwise stop and
record the exact blocker, owner, or decision required.

Leave a durable artifact: <expected artifact>. Do not substitute strategy prose
or self-reported success for evidence.
```

## Outsider Falsification

**Use when:** A public claim, install path, demo, receipt, or workflow is said to
work but has not recently been tested from outside the development environment.

```text
Act as a <stranger/customer/auditor> with no repository context. Test our
strongest relevant public claim against the live public surface. Record every
command, elapsed step, failure, and confusing term. Fix only the first thing
that makes the claim untrue when the repair is bounded and authorized; otherwise
file the exact friction and stop.
```

**Durable artifact:** A timestamped stranger-test transcript, reproducible issue,
or focused repair with before/after proof.

**Stop instead of acting when:** The test needs private credentials, coaching,
production mutation, or a policy decision. Do not impersonate the real outsider
when human cold-eyes evidence is the acceptance criterion.

## Belief-Reality Audit

**Use when:** A dashboard, queue state, green check, release claim, or operating
assumption conflicts with observed behavior.

```text
List what we currently believe is working. For each belief, name the observation
that would falsify it and locate the newest live proof. Test the highest-impact
belief first. If the proof is stale or contradictory, classify the failure and
make one bounded repair or truthfulness update; otherwise record the fresh proof
and stop.
```

**Durable artifact:** A compact belief/evidence table with timestamps and source
links, plus one issue or patch only when the evidence requires it.

**Stop instead of acting when:** The evidence sources disagree and no authority
defines which is canonical, or the proposed fix would change policy rather than
repair an implementation.

## Deletion Question

**Use when:** Repeated maintenance, duplicate abstractions, stale branches, or
automation loops consume attention without producing proof or user value.

```text
What should we stop doing, delete, defer, or stop routing through agents? Measure
the cost and identify every unique consumer, artifact, commit, or behavior that
would be lost. Prefer retirement or consolidation only when live evidence proves
the value is duplicated or obsolete. Preserve anything uncertain and record the
decision before cleanup.
```

**Durable artifact:** An adopt/fold/retire disposition with equivalence evidence,
owner state, and a preservation or cleanup command that remains unexecuted until
its authority is explicit.

**Stop instead of acting when:** Content is dirty, uniquely committed,
active-owned, public, security-sensitive, or not demonstrably superseded. Never
turn uncertainty into destructive cleanup.

## Unverified-Assumption Audit

**Use when:** An answer, plan, receipt, review, or merge recommendation sounds
complete but depends on facts that were not checked.

```text
What did this result not verify? List the assumptions it treated as given, then
rank them by expected impact times likelihood of being wrong. Test the top
assumption on the real surface. If it fails, repair or reopen the decision within
the current authority; if it passes, attach the proof and leave the remaining
limitations explicit.
```

**Durable artifact:** An assumptions/unverified/falsification block attached to
the decision artifact, with a check-by date or reopen condition where useful.

**Stop instead of acting when:** Verification would require protected data,
unsafe production access, or a broader decision than the current operator owns.

## Should This Exist?

**Use when:** A proposed subsystem, framework, integration, or automation may be
making Aragora more elaborate without making it more useful or externally
verifiable.

```text
Would this work make Aragora measurably more useful to an outsider, or only make
the system more elaborate? Name the user, changed behavior, and proof surface.
Compare against composition with existing primitives and the option of doing
nothing. Proceed with the smallest proof-producing version only if the benefit
and verification method are concrete; otherwise defer or reject it with a
reason.
```

**Durable artifact:** A one-page proceed/defer/reject note naming the user,
existing alternatives, smallest experiment, success signal, and stop condition.

**Stop instead of acting when:** There is no named user, no observable outcome,
no bounded experiment, or the proposal duplicates an existing authority.

## Choosing The Prompt

| Situation | Start with |
| --- | --- |
| Public claim or first-hour path may be untrue | Outsider falsification |
| Internal status conflicts with observed behavior | Belief-reality audit |
| Maintenance or abstraction appears to be pure drag | Deletion question |
| Recommendation rests on unchecked facts | Unverified-assumption audit |
| New work lacks a clear user or proof surface | Should-this-exist prompt |

Use one prompt family first. If its evidence exposes a different question, leave
that as the next explicit unit rather than chaining multiple investigations and
actions into the same session.
