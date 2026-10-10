# Positioning And Messaging

Consolidated from:
- `docs/strategy/COMPETITIVE_POSITIONING_2026_03.md`
- `docs/strategy/MESSAGE_ARCHITECTURE_2026_03.md`
- `docs/strategy/WHY_NOT_GENERIC_AGENTS.md`
- `docs/strategy/STAKEHOLDER_MESSAGE_MAP_2026_03.md`
- `docs/outreach/STAKEHOLDER_NARRATIVE_VARIANTS.md`
- `docs/outreach/FOUNDER_STORY_VARIANTS.md`

Last updated: 2026-04-19

---

## Part 1: Core Positioning

### One-Sentence Framing

Aragora is best framed as an **auditable control plane for consequential
AI-assisted work**: it adds adversarial review, receipts, provenance, and
truthful gates above worker agents, review loops, and automation runtimes.

That is a more credible category than:

- "general-purpose agent framework"
- "faster PR review bot"
- "replacement for Temporal-style workflow engines"
- "replacement for accountable human decision makers"

### Category Boundary

Aragora is not a generic autonomous-agent platform. It is the governance and
truthfulness layer used when AI-assisted execution needs receipts, review,
provenance, and explicit terminal states.

### Category Statement

**Auditable execution control plane for AI-assisted work**

Do not lead with "multi-agent platform" or "43 agent types." Those are support
facts, not the wedge.

---

## Part 2: Why Not Generic Agents

**Aragora should not be sold as a generic agent platform.**

That category is already crowded, increasingly interchangeable, and hard to
defend. Model access, tool calling, plugin surfaces, routing, and lightweight
multi-agent orchestration are now table stakes.

If Aragora leads with breadth alone, it will collapse into the same story as:

- coding-agent shells
- model routers
- generic orchestration frameworks
- "build any agent" platforms

That is not a durable wedge.

### Why Generic Agent Positioning Fails

#### 1. The feature set is commodity

Buyers can already get:

- multi-provider access
- tool use
- terminal execution
- workflow graphs
- agent registries
- prompt templates
- plugin ecosystems

Those capabilities are useful, but they do not answer the harder question:
why should anyone trust the system when the outcome matters?

#### 2. Breadth obscures the actual product

When Aragora leads with:

- agent counts
- connector counts
- provider breadth
- generic workflow claims

it sounds like infrastructure looking for a use case. The real product is
governance over AI-assisted execution, not more substrate.

#### 3. The wrong comparison set is brutal

If Aragora positions as a generic agent platform, it gets compared against:

- OpenCode and Pi on execution simplicity
- Codex and Claude Code on developer velocity
- LangGraph and CrewAI on orchestration ecosystems
- generic cloud agent stacks on breadth and integrations

That is the wrong battlefield. Aragora does not need to beat those tools at
being worker runtimes. It needs to govern them when the work becomes
consequential.

### What Aragora Is Instead

#### 1. A system for turning disagreement into evidence

Most agent products treat disagreement as a routing problem.
Aragora treats disagreement as signal:

- convergence after challenge increases confidence
- dissent identifies where human judgment is still required
- receipts preserve both the outcome and the argument trail

#### 2. A control plane above worker runtimes

Codex, Claude Code, OpenCode, Pi, and similar tools can be excellent workers.
Aragora should use them, not imitate them.

Aragora owns the layer above execution:

- bounded delegation
- review
- receipts
- merge and publish gates
- truthful blocker handling

#### 3. A calibrated trust system over time

The long-term wedge is not "many agents." It is evidence-based accountability:

- historical receipts
- outcome labeling
- calibration by domain
- performance tracking across heterogeneous models

That foundation supports stronger trust guarantees later. Without it,
"multi-agent" is just choreography.

### Page Test

Every README, deck, landing page, and partner brief should pass this test:

If you remove the nouns "agents," "models," and "workflows," does the core
promise still make sense?

For Aragora, it should.

The remaining promise should still read roughly like this:

**Govern consequential AI-assisted execution with receipts, review, provenance,
and truthful stopping behavior.**

---

## Part 3: What The Repo Actually Shows Today

| Repo-visible capability | Evidence in repo | Safe claim |
|---|---|---|
| Multi-agent debate and review | [README](../../README.md), [Developer Quickstart](../quickstart.md) | Aragora can run structured multi-agent review flows and expose pass / changes-requested / blocked outcomes. |
| Review artifacts on real PR heads | [Developer Quickstart](../quickstart.md) | Aragora can review the current remote PR head and persist structured review artifacts to disk. |
| Decision receipts and audit-oriented artifacts | [README](../../README.md), [Feature Discovery](../status/FEATURE_DISCOVERY.md) | Aragora already treats receipts as first-class outputs, not just logs. |
| Bounded delegation with leases and isolated worktrees | [Feature Discovery](../status/FEATURE_DISCOVERY.md) | Aragora has supervisor, worker-launch, and reconciliation primitives for bounded multi-agent execution. |
| Queue / pipeline / workflow surfaces | [README](../../README.md), [Feature Discovery](../status/FEATURE_DISCOVERY.md) | Aragora has workflow and pipeline surfaces, but those should support the control-plane story rather than become the primary pitch. |
| Human approval and blocker handling | [Feature Discovery](../status/FEATURE_DISCOVERY.md) | Aragora is designed to stop, classify blockers, and route the next action instead of pretending every run is fully autonomous. |

The repo also shows constraints that should shape the pitch:

- [Feature Gap List](../FEATURE_GAP_LIST.md) still calls out control-plane truth
  gaps around universal per-lane receipts, claims, and integrator visibility.
- [Feature Discovery](../status/FEATURE_DISCOVERY.md) marks some receipt and inbox
  surfaces as integrated or partial rather than uniformly complete.
- The strongest "real today" proof path is review, debate, bounded delegation,
  and receipt capture, not "fully autonomous organization."

---

## Part 4: Competitive Frame By Category

Aragora sits next to four categories that buyers will naturally compare:

| Category | What that category is good at | Where Aragora should concede ground | Where Aragora has a real wedge | Correct positioning |
|---|---|---|---|---|
| Agent frameworks | Wiring tasks, tool calls, agent roles, and graph execution | They are usually simpler and better known for cooperative automation plumbing | Aragora is stronger when the work needs explicit disagreement, review evidence, receipts, and truthful stopping | Use frameworks to execute or orchestrate; use Aragora when the decision or merge step needs governance |
| Review tools | Fast feedback on code diffs, lint-like issues, and routine PR checks | Simple review bots are lower-friction for everyday diffs and narrow defect classes | Aragora is stronger for consequential review where dissent, blocker classification, and durable artifacts matter | Aragora is a governed review layer, not just a comment bot |
| Workflow tools | Durable retries, scheduling, queues, SLAs, and stateful automation | They are better default choices for generic business-process automation and background job reliability | Aragora is stronger at the judgment-heavy gates inside a workflow: review, approval, escalation, and evidence capture | Use workflow engines for execution reliability; call Aragora at high-consequence decision points |
| Internal human processes | Accountability, domain context, politics, and final approval authority | Humans still own accountability, exception handling, and irreversible decisions | Aragora is stronger at compressing first-pass analysis, preserving rationale, and surfacing disagreement before meetings or approvals | Aragora should tighten human review loops, not claim to replace them |

### Competitor Map

| Dimension | Aragora | LangGraph/CrewAI | OpenCode/Pi |
|-----------|---------|------------------|-------------|
| Status quo coordination: Slack, email, docs, meetings, checklists | Already deployed, flexible, no new procurement, humans absorb ambiguity | Decisions disappear into chat and docs, handoffs are slow, audit trails are incomplete, repeatability is weak | Replace only the recurring consequential workflows where missing provenance or repeated rework is already expensive |
| Generic agents: Codex, Claude Code, OpenCode, Pi, ChatGPT, similar single-agent tools | Fastest time to useful draft, low ceremony, strong local productivity | Review burden stays hidden, provenance is weak, blocker handling is uneven, one answer often looks more certain than it is | Treat them as worker runtimes under Aragora's review, receipts, routing, and bounded delegation layer |
| Bespoke internal workflows: scripts, prompt chains, GitHub Actions, MCP glue, eval harnesses | Tailored to one team's stack and one narrow workflow | Brittle ownership, scattered logic, hard-to-audit prompts, expensive to extend across teams and workflows | Replace patchwork governance with a standard control plane for policy, receipts, review, and outcome tracking |
| Human-only review and approval | Highest immediate trust, easiest answer for regulated or politically sensitive work | Slow, expensive, inconsistent, and still poorly documented unless someone captures the reasoning manually | Keep the human gate, but let Aragora compress pre-review work and preserve the evidence package |

### 1. Aragora Vs Agent Frameworks

Examples in the repo and surrounding docs include LangGraph, CrewAI, AutoGen,
and external framework integrations.

The honest comparison is:

- agent frameworks are primarily about coordination and execution structure
- Aragora's best story is not "more orchestration"
- Aragora's best story is "better governed judgment"

What to say:

- Aragora treats disagreement as a feature, not a routing failure.
- Aragora preserves receipts, provenance, and explicit terminal states.
- Aragora can sit above worker runtimes and frameworks rather than replace them.

What not to say:

- Aragora has a stronger orchestration ecosystem than the incumbent frameworks.
- Aragora is the easiest way to build ordinary cooperative automations.
- multi-provider breadth by itself is the moat.

The clean line is:

**Use an agent framework to run the work. Use Aragora to vet consequential
outputs before they ship, merge, or trigger irreversible actions.**

### 2. Aragora Vs Review Tools

This category includes PR review bots, static analyzers, CI gates, and
single-model review loops.

The honest comparison is:

- review tools are optimized for speed, coverage, and low ceremony
- Aragora adds overhead on purpose when the review outcome matters
- Aragora should win on review governance, not on "fewest seconds to first comment"

What to say:

- Aragora can review a live GitHub PR head and persist structured artifacts.
- Aragora can return `passed`, `changes_requested`, or `blocked` style outcomes.
- Aragora is a better fit when teams need evidence for why a change advanced or stopped.

What not to say:

- Aragora should replace every ordinary PR bot or static analysis rule.
- Aragora is always cheaper or faster than a single-reviewer path.
- every receipt is already complete enough for every compliance workflow.

The clean line is:

**Review bots are good at fast comments. Aragora is for review decisions that
need dissent, receipts, and truthful blocker handling.**

For code review specifically, the stronger product language is not "PR review
bot." It is:

**receipt-backed intelligence brief for consequential code changes**

That framing matters because the user problem is shifting from "how do I get
more review comments?" to "how do I settle more AI-generated PRs safely
without reading every diff line first?"

If automated review becomes table stakes, the wedge is not detection alone.
The wedge is heterogeneous judgment, provenance, explicit dissent, and
human-settled merge decisions.

### 3. Aragora Vs Workflow Tools

This category includes workflow engines, queue systems, and DAG runtimes.
The repo does show workflow and queue surfaces, but that does not mean Aragora
should be sold as a generic workflow winner.

The honest comparison is:

- workflow tools own durability, retries, scheduling, and operational cadence
- Aragora owns the judgment-heavy control points inside those flows
- the wedge is not "more DAGs"; it is "better governed decisions inside DAGs"

What to say:

- Aragora already has queue, pipeline, and workflow components.
- Those components are most useful when tied to receipts, approvals, and review evidence.
- Aragora can be the policy and evidence layer around a broader execution stack.

What not to say:

- Aragora should replace purpose-built workflow infrastructure everywhere.
- generic workflow breadth is the differentiator buyers should care about first.
- durable execution alone creates a moat.

The clean line is:

**Use workflow tooling to move work reliably. Use Aragora where the workflow
needs adversarial review, explicit approval, or truthful escalation.**

### 4. Aragora Vs Internal Human Processes

The honest comparison is:

- humans still own accountability, context, and exception handling
- many internal review loops are slow because evidence is fragmented or lost
- Aragora is most credible when it sharpens human review rather than bypassing it

What to say:

- Aragora can produce a durable record of who argued what and why a run stopped.
- Aragora can narrow the set of questions humans need to answer.
- Aragora can make handoffs and approvals more explicit.

What not to say:

- Aragora can replace domain owners, approvers, or legal/compliance judgment.
- every decision should be fully autonomous.
- a receipt is the same thing as accountability.

The clean line is:

**Aragora reduces review latency and preserves decision evidence, but humans
remain the accountable final authority.**

### Buyer Switching Triggers

Aragora becomes the better default when most of these are true:

- the workflow repeats often enough that rework and review latency matter
- multiple humans or models are already involved, even if informally
- the cost of an unexplainable decision is non-trivial
- someone will later ask why the work advanced, stopped, or was approved

If none of those are true, the buyer should probably stay with the simpler
alternative.

### ERC-8004 And Cryptoeconomic Accountability

This is a long-term bet, not a near-term lead. It requires durable decision
volume and calibration data before it becomes commercially meaningful.

### Canonical Comparison Frames

**Why not just use Codex, Claude Code, OpenCode, or Pi?**

Use them when raw execution speed is enough.
Use Aragora when you need:

- explicit review
- receipts
- provenance
- dissent handling
- merge and publish truthfulness

**Why not just use LangGraph or CrewAI?**

They are orchestration substrates.
Aragora is the governance layer for consequential execution.

The question Aragora answers is not "can agents coordinate?"
It is "can this outcome be defended, audited, and safely advanced?"

**Canonical Answer To "Why Not Just Use Generic Agents?"**

**Because generic agent platforms help models do work. Aragora governs whether
that work should be trusted, advanced, merged, published, or stopped.**

Short version:

**Aragora is where AI-assisted execution becomes reviewable, auditable, and
truthful.**

---

## Part 5: Messaging Spine

### Audience

Primary buyers and champions:

- engineering leaders running consequential AI-assisted workflows
- platform and security teams that need review, provenance, and approval trails
- AI-native teams that already use coding agents but cannot trust single-model output on its own

### Core Problem

Teams already use AI to draft code, plans, reviews, and operational decisions.
The problem starts when the work becomes consequential:

- one model's answer is not strong enough evidence
- logs are not the same thing as an auditable decision trail
- most agent tools optimize for output speed, not explicit review and stopping behavior

### Homepage Headline

**Govern AI-assisted work with receipts, review, and truthful gates.**

### Homepage Subheadline

Aragora orchestrates multi-model review around consequential decisions and
execution, preserves provenance, and stops truthfully when evidence is
insufficient, so teams can approve, audit, and improve AI-assisted work.

### Outreach Headline

**Stop shipping AI-assisted decisions you can't explain.**

### Outreach Subheadline

Aragora adds multi-model review, decision receipts, and truthful blocker
handling to the workflows your team already runs in GitHub, Slack, and the
terminal.

### Proof Points

Use these in priority order. On a homepage hero, use the first two. In outreach,
use the first three. Treat the fourth as integration comfort, not the lead.

#### 1. Disagreement becomes useful evidence

Aragora does not hide model disagreement behind one routed answer. It turns
challenge, dissent, and convergence into a review surface a human can inspect.

Support lines:

- models critique each other before work advances
- dissent shows exactly where judgment is still required
- convergence after challenge carries more weight than a single answer

#### 2. Every consequential action has a receipt

Aragora produces structured decision receipts with provenance, votes,
confidence, and next-action clarity.

Support lines:

- answer who said what, what evidence was used, and why the system advanced or stopped
- exportable receipts for review, audit, and compliance workflows
- receipts are a first-class product output, not a debug log

#### 3. Execution is bounded and truthful

Aragora governs work with review gates, lease-based coordination, and explicit
blocker handling instead of pretending automation succeeded when evidence is weak.

Support lines:

- human approval stays explicit on consequential transitions
- blockers terminalize truthfully instead of being papered over
- bounded autonomy is safer than "full agent" promises

#### 4. It sits above the tools teams already use

Aragora complements worker runtimes instead of trying to replace them.

Support lines:

- works above coding agents, provider APIs, and existing delivery channels
- routes governed outputs into GitHub, Slack, the terminal, and APIs
- lets teams keep fast execution tools where raw speed is enough

### Proof Bank

Use selectively. These are evidence atoms to support the wedge, not hero copy.

- production debate engine with heterogeneous agent support
- decision receipts and provenance already wired into real flows
- bounded autonomous repo-improvement path with receipt gates
- heavy automated test coverage and broad knowledge-adapter surface (exact counts in [../CANONICAL_GOALS.md](../CANONICAL_GOALS.md#canonical-metrics) — this doc should not drift from the canonical baseline)

### Proof Points That Fit The Story

Lead with evidence that reinforces the control-plane wedge:

- receipt-backed review flows
- bounded autonomous execution with human gates
- truthful blocker handling
- measurable catch-rate or quality deltas versus single-model review
- audit-ready artifacts for compliance-sensitive workflows

Treat these as supporting facts, not the thesis:

- breadth of agent registry
- connector counts
- generic SDK surface area
- raw orchestration flexibility

### Objections And Responses

**"Why not just use Codex, Claude Code, OpenCode, or Pi?"**

Those tools are strong worker runtimes. Aragora solves the layer above them:
review, provenance, receipts, dissent, and truthful stopping behavior.

**"Isn't multi-agent review slower and more expensive?"**

Yes, which is why Aragora should be used when the work is consequential. The
rule is to use the simplest layer that preserves the needed truthfulness.

**"Are receipts just logs with better branding?"**

No. Logs record events. Receipts explain the decision: evidence, participants,
confidence, dissent, and the explicit next action or blocker.

**"Do we have to replace our current stack?"**

No. Aragora is a control plane above existing models, coding agents, and
channels. Teams keep their current tools and add governance where it matters.

**"Can unattended execution actually be trusted?"**

Only when it is bounded and truthful. Aragora's claim is not infinite autonomy;
it is governed execution with explicit approval points and honest terminal states.

**"Why should we trust AI to judge AI?"**

You should not trust one model. Aragora makes models challenge each other,
records dissent, and keeps the human approval path explicit.

**"Is this too heavy for day-to-day use?"**

Not if it is attached to the right workflow. Aragora should be introduced where
a wrong answer is expensive, a review trail matters, or unattended execution
needs honest terminal states.

**"Are you selling compliance software?"**

No. Compliance artifacts are a consequence of the control-plane design. The
beachhead is consequential review and execution, with security and compliance as
amplifiers for buyers that need them.

### CTA Hierarchy

#### Homepage

1. **Primary:** Review a real artifact
2. **Secondary:** See a sample decision receipt
3. **Tertiary:** Self-host or read the quickstart

Rationale:

- primary CTA proves the wedge on real work
- secondary CTA makes the product output concrete
- tertiary CTA catches self-serve technical evaluators without diluting the main path

#### Outreach

1. **Primary:** Book a 15-minute workflow scoping call
2. **Secondary:** Send one bounded artifact for a pilot receipt
3. **Tertiary:** Reply with the team's current review bottleneck

Rationale:

- primary CTA is the shortest path to a design-partner conversation
- secondary CTA lowers friction for skeptical technical buyers
- tertiary CTA invites response even if the prospect is not ready for a call

### Copy Guardrails

- Lead with governance, review, receipts, and truthful gates.
- Do not lead with model count, adapter count, or generic orchestration breadth.
- Treat worker runtimes as complements, not enemies.
- Prefer "consequential AI-assisted work" over vague claims about all automation.
- Make the human next step explicit in every surface.

---

## Part 6: Stakeholder Message Map

The category claim stays fixed across stakeholders. What changes is the problem
framing, proof surface, and first workflow to land.

### Messaging Rules

- Lead with consequential work, not general-purpose AI productivity
- Lead with receipts, review, provenance, and truthful gating
- Treat worker runtimes as complements and substrates, not enemies
- Use model breadth as supporting evidence, never as the moat
- Do not promise full autonomy; promise bounded execution under explicit policy

### Stakeholder Matrix

| Stakeholder | Primary pain | Promise | Proof surface | Likely objection | Best first workflow |
|---|---|---|---|---|---|
| Founder | AI increases velocity but also hidden decision risk | More leverage without losing accountability | Receipt trail, dissent visibility, bounded execution | "Is this just orchestration overhead?" | High-value founder-owned review path |
| Operator | Ad hoc AI use creates inconsistent workflows and unclear ownership | Repeatable operations with explicit terminal states | Queueing, receipt-before-action, blocker summaries | "Will this add friction to the team?" | Recurring triage, review, or approval workflow |
| Security reviewer | Agents are opaque and hard to constrain | Governable AI-assisted execution with audit evidence | Approval gates, provenance, self-hosting, compliance artifacts | "How do you prevent silent unsafe actions?" | Review-heavy workflow with human approval |
| Technical buyer | Existing agent tools already handle execution | Control plane above execution substrates | Debate, receipts, calibration, API and SDK surfaces | "Why not just use Codex, Claude Code, or LangGraph?" | Consequential engineering review path |

### Proof Priority By Stakeholder

#### Founder

1. Explain the leverage story
2. Show one receipt that demonstrates accountability
3. Show how bounded execution increases trust rather than removing humans

#### Operator

1. Show a workflow trigger and terminal state
2. Show how blockers and handoffs are made explicit
3. Show that the next action is lower-friction, not higher-friction

#### Security Reviewer

1. Show trust boundaries and approval points
2. Show provenance and receipt artifacts
3. Show deployment and control options that fit the environment

#### Technical Buyer

1. Show where Aragora sits relative to existing agent tools
2. Show the review and evidence layer, not generic orchestration
3. Show how it plugs into current engineering systems

### Recommended Language

Preferred phrases:

- auditable execution control plane
- receipt-before-action
- adversarial review
- provenance and dissent trail
- truthful stop/go gating
- bounded delegation

Avoid as lead phrases:

- model marketplace
- orchestration framework
- autonomous swarm platform
- AI employees
- no-human-in-the-loop automation

### Anti-Patterns

- Do not pitch Aragora as "many agents in one place"
- Do not center connector count, provider count, or workflow template count
- Do not imply that disagreement disappears; show that it is made legible
- Do not sell cryptoeconomic accountability before the buyer accepts the
  control-plane wedge

---

## Part 7: Stakeholder Narrative Variants

Every variant should preserve these truths:

- Aragora sits above worker runtimes such as Codex, Claude Code, OpenCode, and Pi
- The wedge is not model breadth; it is receipts, review, provenance, and
  truthful blocker handling
- Aragora helps teams move faster on consequential work by making delegation
  governable rather than opaque
- The output is a decision receipt, not just an answer

### Founder Variant

**One-line framing:**
Aragora lets a small team operate with board-room rigor without adding board-room drag.

**Core narrative:**
You are already using AI to move faster, but speed stops being an advantage the
moment nobody can explain why an important decision was made. Aragora gives a
founder-led team a way to delegate more work to AI without creating hidden risk.
It runs adversarial review across multiple models, surfaces disagreement before
it becomes an incident, and produces a receipt you can share with customers,
investors, auditors, or your own team.

The real value is leverage with control. Instead of hiring a larger staff just
to create decision coverage, Aragora gives your existing team a repeatable way
to vet specs, PRs, vendor choices, policy changes, and other consequential
calls. You move faster because review is structured, not because governance is
removed.

**What the founder cares about:**

- Shipping faster without accumulating invisible AI risk
- Getting more leverage from a small team
- Having a credible story for customers, investors, and diligence
- Avoiding operational chaos from ungoverned agent use

**Proof points to emphasize:**

- Multi-agent debate with explicit dissent, not a single opaque model opinion
- Decision receipts with provenance and confidence trails
- Bounded execution with receipt gates and truthful stopping behavior
- Real review and execution flows already wired end to end on `main`

**Founder CTA:**
Start with one recurring high-value workflow where speed matters but an
unexplained mistake would be expensive.

### Operator Variant

**One-line framing:**
Aragora turns ad hoc AI usage into a repeatable operating system for consequential work.

**Core narrative:**
Operators do not need more model demos. They need a workflow that runs the same
way on Monday night as it does during an incident on Friday afternoon. Aragora
is useful when work has to be reviewed, routed, approved, and handed off without
losing the evidence trail. It takes inputs from channels your team already uses,
runs structured multi-agent vetting, and returns a receipt that makes the next
action obvious: proceed, escalate, or stop.

This matters because most AI usage fails operationally before it fails
technically. Ownership gets fuzzy, outputs are hard to audit, and people cannot
tell whether a task completed cleanly or merely sounded confident. Aragora adds
truthful stage transitions, explicit blockers, and publish/merge gates so teams
can operationalize AI without pretending uncertainty does not exist.

**What the operator cares about:**

- Clear ownership and low-friction handoffs
- Repeatable workflow behavior across Slack, GitHub, inbox, and APIs
- Faster throughput on bounded recurring work
- Honest terminal states instead of false success

**Proof points to emphasize:**

- Receipt-before-action workflow design
- Queue, supervisor, lease, and merge-policy patterns for bounded execution
- Operator-facing summaries for consensus, blockers, and next actions
- Exportable artifacts for reporting and postmortems

**Operator CTA:**
Pick one bounded operational workflow with a clear trigger, owner, and success
condition, then make Aragora the review and receipt layer for that path.

### Security Reviewer Variant

**One-line framing:**
Aragora is the governance layer that makes AI-assisted execution reviewable, constrainable, and auditable.

**Core narrative:**
Security teams should be skeptical of any agent platform that claims autonomy
without showing its control surfaces. Aragora's value is that it does not ask
you to trust a model. It gives you explicit review stages, provenance,
cryptographic receipts, bounded delegation, and truthful stopping behavior when
the evidence is weak or the state is ambiguous.

The system is strongest when presented as a control plane above worker runtimes,
not as an unbounded autonomous actor. It preserves who said what, what evidence
was used, how consensus or dissent formed, and why a workflow advanced or
stopped. That aligns with how security and compliance teams actually evaluate
risk: not "was the model smart?" but "what constrained the action, and what
artifact exists for review afterward?"

**What the security reviewer cares about:**

- Clear trust boundaries and bounded execution
- Explicit approval and merge gates
- Tamper-evident audit trails and provenance
- Deployment options that fit regulated or isolated environments

**Proof points to emphasize:**

- SHA-256 decision receipts and exportable compliance artifacts
- Truthful blocker handling rather than hidden retries or false positives
- Enterprise controls: SSO, RBAC, encryption, multi-tenancy, offline/self-hosted
- EU AI Act, SOC 2, HIPAA, and governance-aligned artifact generation

**What not to say:**

- Do not lead with "43 agent types" or generic orchestration breadth
- Do not imply Aragora removes human accountability
- Do not position it as open-ended autonomy without policy and receipt gates

**Security CTA:**
Start with a review-heavy workflow where auditability, bounded action, and
evidence retention matter more than raw task volume.

### Technical Buyer Variant

**One-line framing:**
Aragora gives technical teams the control plane they do not get from worker runtimes alone.

**Core narrative:**
Technical buyers already know they can get raw execution from Codex, Claude
Code, OpenCode, Pi, or a homegrown agent harness. The question is what they add
when the work becomes consequential. Aragora is the layer that governs that
execution: multi-model challenge, structured review, provenance, calibration,
and receipts that make the output usable inside real engineering systems.

This is why Aragora should not be pitched as "another coding agent." It is the
product you buy when you want AI-assisted execution to survive code review,
security review, and operational scrutiny. It integrates with existing
substrates instead of forcing a rip-and-replace, which lowers adoption friction
for engineering organizations that already have strong opinions about their
worker tools.

**What the technical buyer cares about:**

- Whether Aragora replaces or complements existing agent tools
- Whether it can plug into current review and delivery workflows
- Whether the evidence quality is high enough for consequential engineering work
- Whether the architecture supports future governance and calibration needs

**Proof points to emphasize:**

- Aragora sits above execution substrates rather than competing with them
- Adversarial debate and dissent trails are core primitives, not add-ons
- Receipts, review outcomes, and blocker visibility are first-class outputs
- API, SDK, and channel surfaces exist to embed Aragora into current systems

**Technical buyer CTA:**
Evaluate Aragora on one consequential review path where a fast answer is not
enough and the team needs evidence for why a change should ship.

### Talk Tracks By Moment

| Moment | Best stakeholder lead |
|---|---|
| Fundraising or board-pressure conversation | Founder variant |
| Workflow design, support burden, or throughput discussion | Operator variant |
| Security architecture or compliance review | Security reviewer variant |
| Tooling evaluation against Codex, Claude Code, or LangGraph | Technical buyer variant |

### The Message Stack

If the prospect starts with agent frameworks:

**Aragora is the review and governance layer above execution frameworks.**

If the prospect starts with PR review tools:

**Aragora is for merge decisions that need evidence, dissent, and explicit stop
conditions, not just another stream of comments.**

If the prospect starts with workflow platforms:

**Aragora governs the judgment-heavy gates inside the workflow; it is not trying
to win on generic scheduling or retries.**

If the prospect starts with internal human process:

**Aragora makes human review tighter and more inspectable; it does not remove
human accountability.**

### Message Discipline

If a conversation drifts, return to the same category claim:

**Aragora governs AI-assisted execution with receipts, review, provenance, and truthful stopping behavior.**

---

## Part 8: Founder Story Variants

Use these as spoken founder narratives, not as homepage copy. They are written
to stay inside claims already supported by the repo's current positioning and
product surfaces.

### Claims Discipline

- Lead with the problem: important AI-assisted decisions are hard to trust,
  explain, and review after the fact.
- Frame Aragora as a control plane for multi-agent review, receipts, and
  bounded execution, not as a magical autonomous intelligence.
- Prefer concrete mechanisms over marketecture: debate, dissent, receipts,
  provenance, review gates, truthful stopping behavior.
- Do not claim that Aragora eliminates risk, guarantees correctness, or replaces
  human judgment.
- Do not claim category dominance, inevitability, or customer outcomes that are
  not evidenced here.

### 10-Second Version

I started Aragora because teams are using AI for real decisions, but most of
those decisions are still coming from one model and a weak audit trail.
Aragora adds adversarial multi-agent review and decision receipts so you can see
where models agree, where they disagree, and why a workflow moved forward.

### 30-Second Version

I started Aragora after seeing the same pattern over and over: teams were using
AI to write code, review plans, and triage work, but when something looked
wrong there was no reliable answer to "why did the system do that?" A single
model can be useful, but it is a weak foundation for consequential decisions.

Aragora is our answer to that. We run structured review across multiple agents,
capture the dissent and provenance, and produce a decision receipt before the
work moves on. The point is not more agent theater. The point is to make
AI-assisted execution more reviewable, more governable, and more honest about
uncertainty.

### 2-Minute Version

I came to Aragora from a pretty simple frustration: AI systems were getting good
enough to be involved in real work, but not good enough to be trusted on their
own. Teams were starting to use models for code changes, design reviews,
analysis, and operational workflows, and the standard pattern was still
"ask one model, get one answer, maybe save the chat log." That breaks down fast
when the work matters.

What I wanted was not a better chatbot. I wanted infrastructure that treats
model unreliability as a design constraint. If a decision matters, I want more
than a fluent answer. I want multiple perspectives, explicit challenge, a clear
record of what evidence was used, and a truthful stop when the system does not
have enough confidence to continue cleanly.

That is what Aragora is built to do. It orchestrates multi-agent review,
surfaces disagreement instead of hiding it, and produces decision receipts with
the reasoning trail, provenance, and review outcome. We are also building it so
bounded execution can happen under explicit gates rather than vague autonomy.
The product is not "trust the swarm." The product is a control plane that makes
AI-assisted work easier to inspect, challenge, and govern.

The reason I think this matters now is that teams are already delegating more
work to AI systems, especially in engineering and adjacent knowledge work. The
real bottleneck is no longer generating output. It is deciding what deserves to
move forward, what needs a human, and how to preserve an honest record of that
decision. Aragora is aimed at that layer.

### 5-Minute Version

I started Aragora because I think there is a gap between how people talk about
AI agents and how serious teams actually need to operate. The industry has been
very good at making models look capable in isolated interactions. It has been
much worse at making AI-assisted decisions legible after the fact.

If you look at how teams use AI today, the pattern is often the same. A model
helps draft code, evaluate an option, summarize research, or suggest an action.
That can be genuinely useful. But when the stakes go up, the weaknesses also
become obvious. One model is still one witness. It can be wrong, sycophantic,
incomplete, or confidently inconsistent. And once the output is pasted into a
workflow, the reasoning trail usually disappears.

That creates two operational problems. First, teams do not have a good way to
challenge AI output before it gets embedded in real decisions. Second, when
something goes wrong, they do not have a good way to reconstruct why the system
advanced, what alternatives were considered, or where the uncertainty actually
was.

Aragora comes from taking that problem seriously. Instead of treating a model as
an oracle, we treat it more like an unreliable witness. The system is designed
to bring in multiple agents, let them critique each other, surface dissent, and
record what happened in a form that a human can actually review. If the work is
going to move forward, there should be an explicit receipt. If the evidence is
weak or the disagreement is unresolved, the system should stop truthfully and
say so.

That sounds simple, but it changes the layer we are trying to build. We are not
trying to be the best single worker model or the broadest orchestration
framework. We are trying to build the control plane above AI-assisted work:
review, provenance, receipts, gates, and bounded execution with honest
terminal states.

Practically, that means a few things. We care a lot about disagreement because
it is often the most useful signal in the system. We care about receipts because
chat logs are not enough when a workflow needs to be inspected later. We care
about explicit review gates because "the agent seemed confident" is not a
serious operating model. And we care about truthful stopping behavior because a
system that cannot cleanly admit uncertainty is hard to trust even when it is
sometimes right.

The founder story is not that AI will run everything on its own. The founder
story is that teams are already using AI in consequential workflows, and the
governance layer around those workflows is still too thin. Aragora is our
attempt to build that missing layer in a way that is practical for engineering
teams now and extensible to more regulated or high-accountability environments
over time.

So when I describe Aragora, I usually do not say "we built a swarm." I say we
built a system for making AI-assisted work more reviewable. Multiple agents are
part of that, but they are not the whole point. The point is that before a
decision ships, you should be able to inspect the challenge process, understand
the provenance, see the dissent, and know whether the system advanced or stopped
for a defensible reason.

### Optional Closing Line

If you want the short version: Aragora is the layer that helps teams use AI for
real work without pretending a single fluent answer is the same thing as a
well-governed decision.

---

## Part 9: Founder Proof Discipline

Founder messaging should lead with the smallest set of claims that can be
repeated on current `main` with durable artifacts.

Lead with these three claims:

- Aragora can run a live decision review and produce a stored receipt
- Aragora can show why the system advanced or stopped
- Aragora can gate bounded actions on persisted receipts and explicit policy

Support those claims with concrete proof packets, not generic category language:

- live run plus receipt ID or share link
- exported or stored receipt showing consensus, dissent, provenance, and outcome
- explicit gate or approval surface for any action claim

Do not lead with:

- "43 agent types"
- provider breadth
- connector counts
- generic orchestration claims
- autonomy claims that depend on a benchmark or a not-yet-live-proven path

The detailed claim boundary and proof requirements live in
`docs/strategy/PROOF_AND_EVIDENCE.md`.

---

## Simple Strategic Test

If the answer to "why Aragora instead of adjacent tools?" is:

- "more models"
- "more agents"
- "more workflows"
- "more connectors"

the framing is weak.

If the answer is:

**"because this work needs adversarial review, durable receipts, provenance, and
truthful gates before it advances"**

the framing is on target.

Each stakeholder should hear a different reason to care, but the same reason to
believe:

**Aragora makes consequential AI-assisted work governable by producing receipts,
preserving provenance, surfacing disagreement, and stopping truthfully when
confidence is not earned.**
