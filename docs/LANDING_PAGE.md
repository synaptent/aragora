# Aragora Landing Page Content

> This document contains the copy, structure, and content blocks for the Aragora marketing landing page.
> Designers: use this as the canonical source of truth for all landing page text.

---

## Hero Section

### Headline

**Stop trusting AI blindly. Start vetting decisions.**

### Subheadline

Aragora orchestrates 43 AI agents to adversarially challenge every important decision -- then delivers a cryptographic receipt proving it was rigorously examined.

### CTA

[Get started in 5 minutes](guides/GETTING_STARTED.md) | [View on GitHub](https://github.com/an0mium/aragora)

### Hero code snippet

```python
from aragora_debate import Debate, create_agent

debate = Debate("Should we migrate to microservices?")
debate.add_agent(create_agent("anthropic", name="analyst"))
debate.add_agent(create_agent("openai", name="challenger"))
result = await debate.run()
print(result.receipt.to_markdown())
```

```bash
pip install aragora-debate
```

---

## The Problem

Individual LLMs are unreliable. Stanford researchers documented systematic reasoning failures in frontier models -- broken formal logic, unfaithful chain-of-thought, and fragile robustness under minor prompt variations ([Song et al., 2026](https://arxiv.org/abs/2602.06176)). Confidence scores do not correlate with accuracy. A single model's opinion is not enough when the decision matters.

---

## Three Value Propositions

### [Shield icon] Adversarial Vetting

Multiple AI models with different training data and failure modes debate your question through structured rounds of proposals, critiques, and votes. When heterogeneous models converge after genuinely challenging each other, that convergence is meaningful. When they disagree, the dissent trail tells you exactly where human judgment is needed.

**Key stat:** Multi-agent debate achieves +13.8 percentage points accuracy over single-model baselines ([Harrasse et al., 2024](https://arxiv.org/abs/2410.04663)).

### [Document icon] Decision Receipts

Every debate produces a cryptographic decision receipt -- an auditable artifact that captures the consensus, the dissenting views, the confidence level, and a tamper-proof signature. Export as Markdown, JSON, HTML, PDF, or SARIF. Receipts satisfy EU AI Act Articles 12-14, SOC 2 CC6.1, and HIPAA audit controls out of the box.

**Key stat:** Decision receipts map to 5 regulatory frameworks with zero additional configuration.

### [Network icon] Multi-Agent Consensus

Not just agreement -- calibrated trust. Aragora tracks each agent's ELO rating and Brier calibration score per domain. It detects hollow consensus (models agreeing without evidence) and automatically injects adversarial challenges. The result is not "what the AI said" -- it is "what survived structured adversarial scrutiny from multiple independent models."

**Key stat:** 43 agent types across 6 LLM providers (Anthropic, OpenAI, Google, xAI, Mistral, OpenRouter).

---

## How It Works

### Step 1: Ask a question

Pose any consequential decision -- an architecture choice, a compliance review, a hiring rubric, an investment thesis.

```python
debate = Debate("Should we adopt Kubernetes for our 8-person startup?")
```

### Step 2: Agents debate adversarially

Multiple AI models independently propose answers, critique each other's reasoning across multiple rounds, and vote on the strongest position. Hollow consensus detection ensures agreement is backed by evidence, not just pattern matching.

```
Round 1: PROPOSE -> CRITIQUE -> VOTE
Round 2: PROPOSE -> CRITIQUE -> VOTE  (address prior critiques)
Round 3: PROPOSE -> CRITIQUE -> VOTE  (final positions)
```

### Step 3: Get a decision receipt

A structured, auditable record of the decision: who agreed, who dissented, the conditions, the confidence level, and a cryptographic signature for tamper detection.

```
Decision Receipt DR-20260212-a3f8c2
Verdict: Approved With Conditions
Confidence: 78%
Consensus: Reached (supermajority)

Conditions:
- Wait until team exceeds 15 engineers
- Start with managed Kubernetes (EKS/GKE), not self-hosted

Dissenting view (challenger):
  "Operational complexity exceeds benefit at current team size."
```

---

## Use Cases

### Architecture Decisions

"Should we migrate from REST to GraphQL?" -- Three models debate the tradeoffs for your specific team size, traffic patterns, and existing infrastructure. The receipt documents the reasoning for future engineers.

### Investment Analysis

"Should we invest in this Series B?" -- Models stress-test the thesis from different angles: market size, competitive moat, unit economics, regulatory risk. Dissenting views surface risks that consensus-seeking obscures.

### Hiring and People Decisions

"Should we hire a senior architect or two mid-level engineers?" -- Adversarial debate forces explicit reasoning about tradeoffs instead of relying on gut instinct. The receipt creates an auditable record of the decision rationale.

### Compliance Reviews

"Does this privacy policy comply with GDPR?" -- The Gauntlet mode stress-tests policies and specifications with adversarial agents that actively try to find violations. Findings come with severity ratings and specific mitigations.

### Security Reviews

"Is this authentication model sound?" -- Multiple models independently analyze the design, cross-reference known vulnerability patterns, and surface disagreements that a single reviewer would miss.

### Clinical Decision Support

"Is this treatment protocol appropriate for this patient profile?" -- Adversarial vetting with HIPAA-compliant field-level encryption, audit trails, and vertical weight profiles tuned for healthcare.

---

## Built for Developers

### Lightweight standalone package

```bash
pip install aragora-debate
```

Zero required dependencies. The debate engine runs anywhere Python runs -- your laptop, a CI pipeline, a serverless function.

### Full platform when you need it

```bash
pip install aragora
```

3,000+ API operations. SDKs in Python (184 namespaces) and TypeScript (183 namespaces). Slack, Teams, Discord, and Telegram connectors. WebSocket streaming with 190+ event types. Workflow engine with 50+ pre-built templates.

### CLI for every workflow

```bash
# AI code review with multi-model consensus
git diff main | aragora review

# Stress-test specifications
aragora gauntlet spec.md --profile thorough

# Quick debate from the terminal
aragora ask "Should we use Kafka?" --agents anthropic-api,openai-api
```

---

## Enterprise Ready

| Capability | What you get |
|------------|-------------|
| **Authentication** | OIDC/SAML SSO, MFA (TOTP/HOTP), API keys, SCIM 2.0 provisioning |
| **Authorization** | RBAC v2 with 390+ permissions, 7 default roles, role hierarchy |
| **Multi-Tenancy** | Tenant isolation, resource quotas, usage metering |
| **Encryption** | AES-256-GCM at rest, field-level encryption for PHI (HIPAA) |
| **Compliance** | SOC 2 controls, GDPR (deletion/export/consent), EU AI Act artifact generation |
| **Deployment** | Self-hosted, Docker Compose, Kubernetes with Helm, offline/air-gapped |
| **Observability** | Prometheus metrics, Grafana dashboards, OpenTelemetry tracing, SLO alerting |
| **Disaster Recovery** | Incremental backups, retention policies, DR drill framework |

---

## Social Proof

> [Placeholder: Customer testimonials and logos go here]

> [Placeholder: "Trusted by X teams at Y companies"]

> [Placeholder: GitHub stars badge, PyPI download count]

### Research Validation

Multi-agent debate is not a marketing claim -- it is a research-validated approach:

- **+13.8 pp accuracy** over single-model baselines ([Harrasse et al., 2024](https://arxiv.org/abs/2410.04663))
- **Significantly reduces hallucinations** ([Du et al., 2023](https://arxiv.org/abs/2305.14325))
- **Mitsubishi Electric** adopted adversarial multi-agent debate for manufacturing decision-making (January 2026)
- **Stanford** documented systematic LLM reasoning failures that debate mitigates ([Song et al., 2026](https://arxiv.org/abs/2602.06176))

---

## Open Source, No Lock-In

Aragora is MIT-licensed. The full debate engine, all 43 agents, the CLI, the SDKs, and the API are open source. You bring your own API keys from any supported provider -- Aragora never marks up LLM costs.

Commercial tiers add managed infrastructure, enterprise security, and compliance tooling for teams that need it.

---

## CTA Section

### Primary

**Get started in 5 minutes.**

```bash
pip install aragora-debate
```

[Read the Getting Started guide](guides/GETTING_STARTED.md)

### Secondary

[View pricing](PRICING_PAGE.md) | [Read the docs](SDK_GUIDE.md) | [GitHub](https://github.com/an0mium/aragora)

---

## Footer

- [Getting Started](guides/GETTING_STARTED.md)
- [Documentation](SDK_GUIDE.md)
- [API Reference](api/API_REFERENCE.md)
- [Pricing](PRICING_PAGE.md)
- [GitHub](https://github.com/an0mium/aragora)
- [Sales: sales@aragora.ai](mailto:sales@aragora.ai)
- [Support: support@aragora.ai](mailto:support@aragora.ai)
