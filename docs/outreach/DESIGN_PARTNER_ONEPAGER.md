# Aragora: Design Partner Brief

**Stop shipping AI-assisted decisions you can't explain.**

Aragora governs consequential AI-assisted work with multi-model review,
decision receipts, and truthful gates, so teams can move faster without losing
provenance or human control.

Last updated: 2026-03-25

---

## The Problem

Your team uses AI every day -- generating code, drafting plans, evaluating options.
But when something goes wrong, nobody can answer: *why did we decide that?*

- **No audit trail.** AI outputs are ephemeral. Decisions evaporate.
- **Single-model blind spots.** One LLM = one perspective. No adversarial vetting.
- **Compliance gaps.** Regulators want explainability. You have chat logs. EU AI Act enforcement begins August 2, 2026.
- **Painful recurring queues.** PR review, inbox triage, and bounded execution all speed up with AI until trust breaks at the approval step.

## Why Now

Agentic execution is now mainstream. OpenAI ships agent-building tools, Anthropic ships a terminal agent that edits files and creates commits, GitHub ships a background coding agent that opens pull requests for review, and Google sells centralized agent governance for the enterprise.

That is the market signal: the bottleneck is no longer "can AI take action?" It is "can operators stay in control of what the AI did, why it did it, and whether it should proceed?"

That makes auditable decision-making urgent now, not later. The EU AI Act becomes fully applicable on **August 2, 2026**, with general-purpose AI obligations already in force since **August 2, 2025**. Even before regulation bites, security, legal, and platform teams already want receipts, approvals, and clear stop conditions before AI actions reach production systems.

## What Aragora Does

Aragora is a **Decision Integrity Platform**. It runs adversarial multi-agent
review, then delivers audit-ready **decision receipts** that explain why the
system advanced or stopped.

```
Your input -> multi-agent debate -> consensus + receipt -> KM feedback -> Slack / GitHub / API
```

**Founder-safe differentiation:**

1. **Disagreement becomes evidence.** Multiple models challenge each other so
   the operator can see convergence, dissent, and unresolved judgment calls.

2. **Receipts are first-class outputs.** Aragora stores a receipt that captures
   outcome, provenance, and why the system advanced or stopped.

3. **Actions stay bounded.** Receipt-before-action and explicit approval policy
   matter more than generic autonomy claims.

## What Aragora Can Prove Today (March 24, 2026)

## Canonical Terms For Partner Conversations

Use these phrases consistently in outreach and sales conversations. The full
internal glossary lives in
[`docs/strategy/PRECISION_AND_TERMS.md`](../strategy/PRECISION_AND_TERMS.md#part-1-terminology-and-phrase-glossary).

- **Debate** = structured adversarial review, not generic multi-agent chatter.
- **Receipt** = the audit artifact that records evidence, dissent, confidence,
  and the reason an action did or did not happen.
- **Trust wedge** = the first narrow workflow where receipt-before-action earns
  trust. Today that is inbox triage.
- **Founder loop** = the repeatable live dogfood path the founder runs to prove
  the product on real work.
- **Control plane** = the governance layer above worker runtimes that routes
  work, enforces policy, preserves receipts, and stops truthfully.

## What Works End-to-End Today (March 23, 2026)

| Claim | Status | Minimum proof to show |
|-------|--------|-----------------------|
| Live decision review is repeatable on current `main` | **Proven** | One live run plus receipt ID/share link; if citing repeatability or speed, use the March 24, 2026 baseline: 5/5 consecutive founder-loop runs, 35-62s, all 7 acceptance items pass |
| Aragora shows why the system advanced or stopped | **Proven** | One stored or exported receipt showing consensus, dissent, provenance, and outcome shape; one verification surface (`aragora receipt verify`, API, or receipt store view) |
| Bounded actions can be gated on persisted receipts and explicit policy | **Dogfood-ready** | One policy-gated flow, such as inbox triage with `aragora triage auth` and `aragora triage run --dry-run`; show that receipt persistence happens before action |

## Reserve Proofs, Not Opening Claims

- **Inbox trust wedge:** Gmail -> debate -> receipt -> CLI approval -> action. Pitch as a narrow, policy-gated path that is ready for dogfood, not as broad autonomous email ops.
- **Ralph autonomous benchmark:** Use only as bounded autonomy evidence. It proves one validated benchmark path under explicit merge policy, not unrestricted autonomy.
- **EU AI Act artifacts:** Safe claim is that Aragora can generate artifact bundles from real receipts. Do not turn that into a certification claim.

## Default Partner Surface

**Decision review** is the default proof surface for partners today. Run a real
artifact (spec, PR, architecture proposal, inbox slice) through multi-agent
review, then share the receipt internally.

## First-Week Journey

The week-one goal is not "turn on full autonomy." It is to get from setup to
**one trustworthy result** on a narrow recurring workflow.

| Stage | Outcome |
|-------|---------|
| Day 0: qualify the lane | one workflow, one owner, one success metric, representative artifacts |
| Day 1: setup and readiness | live path works and produces a visible receipt or truthful blocker |
| Day 2: trust contract | explicit action policy, approval points, and stop conditions |
| Day 3: first real run | real artifact or inbox batch processed in a bounded lane |
| Day 4: review friction | receipt quality, evidence gaps, and trust blockers documented |
| Day 5: first trustworthy result | one receipt-backed decision a human can act on, reject, or hold |

Default order for week one:

1. Decision review
2. Inbox trust wedge in `--dry-run` or approval-gated mode
3. Bounded repo execution only after receipt review feels trustworthy

See the canonical journey and exit gate:
[`docs/outreach/DESIGN_PARTNER_OPERATIONS_PLAYBOOK.md`](./DESIGN_PARTNER_OPERATIONS_PLAYBOOK.md#part-4-first-week-journey).

## Explicit Truth Boundaries

What we can claim in week one:

- Aragora can run a bounded workflow through debate or gated execution.
- Aragora can produce visible receipts with evidence, provenance, and dissent.
- Aragora can stop with a specific blocker instead of pretending completion.

What we do **not** claim in week one:

- guaranteed correctness of the underlying business decision
- removal of the responsible human approver
- safe broad autonomy across an entire organization
- audit/certification completion just because receipts exist

If the receipt is missing, the evidence is weak, or the workflow needs
undocumented operator rescue, we treat that as a blocker, not a success.

## What Partners Get

- One receipt-backed pilot on a bounded recurring workflow
- Audit-ready decision receipts that can be exported and verified
- A narrow approval-gated automation path where it is warranted
- Priority support, roadmap influence, and direct access to the team
- Early access to enterprise features (OIDC/SAML SSO, RBAC, multi-tenancy)

## How Knowledge Mound Actually Learns

**Founder version:** Every strong receipt should make the next decision cheaper and
better. Knowledge Mound is how Aragora compounds vetted work into institutional
memory without pretending every model output is true.

**Buyer version:** Aragora stores governed knowledge with provenance. It learns
high-confidence claims, evidence, and resolution patterns; it does not auto-promote
raw AI output into policy.

| Gets learned | Does not get learned | Must be reviewed |
|--------------|----------------------|------------------|
| High-confidence debate outcomes that clear writeback thresholds | Low-confidence outcomes that do not clear the threshold | Contradictions between new knowledge and existing knowledge |
| Claims, facts, insights, and references with provenance | Unresolved disagreement as if it were settled truth | Promotion of important claims into verified operating knowledge |
| Reusable patterns such as decision style, risk tolerance, domain expertise, and resolution patterns | Sensitive cost telemetry unless the opt-in adapter is enabled | Any receipt with low confidence, meaningful dissent, or high-impact side effects |
| Staleness and contradiction signals so old knowledge can be challenged over time | Stale or superseded items as evergreen truth | Irreversible or policy-setting actions before they execute |

## What We Need From Partners

| From You | From Us |
|----------|---------|
| One bounded recurring workflow with a clear trigger and downside if wrong | Free access during partner period |
| 30 min onboarding + weekly 30 min check-in for 4-6 weeks | Hands-on onboarding to first receipt |
| Named buyer, daily user, evaluator, and likely blocker | Role-specific materials for each decision owner |
| Real artifacts (sanitized OK): inbox batch, design doc, bounded backlog | Priority feature requests and weekly iteration |
| Candid feedback on quality, friction, and trust | Co-marketing opportunity (anonymized case studies OK) |

## Default Bounded Pilot

Aragora pilots are intentionally narrow. We start with **one workflow, one
champion, one integration surface, and one agreed metric**. The default offer
is:

- **Scope:** Pick one wedge only: decision review, inbox trust wedge, or a
  bounded backlog lane. Out of scope for the pilot: broad org rollout,
  autonomous merges, open-ended custom builds, or multi-workflow deployment.
- **Duration:** Default **4 weeks**. Week 1 gets to the first live receipt.
  Weeks 2-3 run the real workflow and tighten prompts/policy. Week 4 ends with
  a go/no-go review.
- **Success criteria:** First live receipt in 7 days, at least 8 real
  receipt-backed runs during the pilot (or 3 full cycles for lower-frequency
  workflows), one agreed operational metric improves, and the champion wants to
  expand or convert.
- **Failure criteria:** No live receipt by day 7, repeated manual rescue after
  week 2, no measurable trust or speed improvement, or no clear expansion path
  by the final review.
- **Founder commitment:** The founder personally runs onboarding, joins the
  first live workflow, reviews failures weekly, ships or supervises pilot-
  critical fixes, and makes an honest go/no-go call instead of dragging the
  pilot out.

See also: [Bounded pilot structure](./DESIGN_PARTNER_OPERATIONS_PLAYBOOK.md#part-3-pilot-structure)

## Who This Is For

We are looking for **3-5 design partners** who:

- Have a painful Gmail or Google Workspace inbox triage workflow with a single clear owner
- Handle consequential messages where misses are costly: revenue, recruiting, partnerships, investor updates, or executive follow-up
- Can start with `archive`, `star`, `label`, and `ignore` before asking for reply/send automation
- Want explicit receipts and human approval before actions execute
- Have a champion who can provide sample artifacts, review receipts, and join a weekly loop

**Best-fit segments:** founder-led B2B teams, executives or chiefs of staff with painful inbox overload,
business development leaders, and recruiting-heavy operators who already feel the cost of manual triage.

## Supporting Facts, Not Opening Claims

- **227,451 automated tests** across 5,634 test files
- **Receipt-gated repo improvement** validated on the benchmark path
- **Inbox trust wedge** shipped from debate to signed receipt to action
- **Heterogeneous provider support** across CLI, API, and local-model workers
- **190+ WebSocket event types** for real-time streaming
- **Python + TypeScript SDKs** (191 Py / 189 TS namespaces)

## Next Step

**Primary CTA:** Book a 15-minute workflow scoping call.

**Secondary CTA:** Send one bounded artifact or recurring workflow and we will
show what the receipt path looks like.

**Tertiary CTA:** Reply with the team's current review bottleneck if you are
not ready for a call yet.

Contact options:

- Email: [your-email]
- Calendar: [booking-link]
- GitHub: https://github.com/synaptent/aragora

---

*Aragora is open source under the Apache 2.0 license.*
*Design partners get priority support, roadmap influence, and early access to enterprise features.*
