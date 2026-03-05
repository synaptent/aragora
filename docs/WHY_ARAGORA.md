# Why Aragora

**LLMs are unreliable. Multi-agent adversarial debate makes decisions you can audit and trust.**

---

## The Problem

Every consequential AI decision today rests on a single model's output. This is structurally unsound.

**Single-model failures are not edge cases -- they are the default operating mode:**

- **Correlated failures.** GPT-4, Claude, and Gemini share training data, RLHF patterns, and architectural assumptions. When one model is wrong about a topic, others are often wrong in the same way. Running the same prompt through the same model twice does not reduce risk.
- **Sycophantic agreement.** Models converge on whatever the user appears to want. Confidence scores do not correlate with accuracy. A model that says "I'm 95% confident" is not 95% accurate.
- **No audit trail.** When an AI-informed decision goes wrong, there is no record of what reasoning was considered, what alternatives were rejected, or where the uncertainty actually was. Regulators, boards, and legal teams cannot work with "the AI said so."
- **Persona instability.** The same model gives different answers depending on prompt phrasing, context order, and system prompt framing. [Stanford's taxonomy of LLM reasoning failures](https://arxiv.org/abs/2602.06176) documents systematic breakdowns in formal logic, unfaithful chain-of-thought, and robustness failures under minor prompt variations -- even in frontier models.

For clinical triage, financial risk assessment, legal review, architecture decisions, and compliance auditing, "probably right" is not an acceptable standard. You need infrastructure that treats model unreliability as a design constraint, not a bug to be patched.

---

## The Solution: Adversarial Multi-Agent Debate

Aragora treats each AI model as an **unreliable witness** and uses structured debate protocols to extract signal from their disagreements.

### How It Works

```
1. PROPOSE   -- Multiple models from different providers generate independent responses
2. CRITIQUE  -- Models challenge each other's reasoning with severity scores
3. REVISE    -- Proposers incorporate valid critiques
4. VOTE      -- Models vote with calibrated weights
5. SYNTHESIZE -- Judge combines best elements into a final answer
```

When Claude, GPT, Gemini, Grok, Mistral, and DeepSeek independently converge on an answer after challenging each other, that convergence is meaningful. When they disagree, the dissent trail tells you exactly where human judgment is needed.

This is not a theoretical approach. Multi-agent deliberation research (including benchmark studies on debate-based reasoning) demonstrates **27-45% accuracy improvements** over single-model baselines on complex reasoning tasks. Mitsubishi Electric announced adversarial multi-agent debate for manufacturing quality assurance in January 2026, validating the concept at industrial scale.

### What You Get

| Capability | How It Works |
|---|---|
| **Adversarial validation** | Models with different training data and blind spots challenge each other's reasoning |
| **Decision receipts** | Cryptographic audit trails with evidence chains, dissent tracking, and confidence calibration |
| **Calibrated trust** | ELO rankings and Brier scores track which models are actually reliable on which domains |
| **Hollow consensus detection** | The Trickster catches cases where models agree without genuine reasoning |
| **Institutional memory** | Decisions persist across sessions with 4-tier memory and Knowledge Mound (41 adapters) |
| **Channel delivery** | Results route to Slack, Teams, Discord, Telegram, WhatsApp, email, or voice |

---

## Key Differentiators

### 1. Multi-Model Consensus with Heterogeneous Providers

Aragora runs 43 agent types across 6+ LLM providers (Anthropic, OpenAI, Google, xAI, Mistral, and OpenRouter giving access to DeepSeek, Qwen, Llama, and more). Each model brings different training data, different failure modes, and different strengths. When models with genuinely different knowledge bases converge after adversarial challenge, the result is more trustworthy than any single model's output.

The system automatically falls back to OpenRouter when primary providers hit rate limits, ensuring debates complete even under load.

### 2. Cryptographic Decision Receipts

Every debate produces a tamper-evident **Decision Receipt** containing:

- The question asked and full debate transcript
- Each model's position, critiques, and revisions
- Consensus proof with voting breakdown
- Confidence calibration scores
- SHA-256 content-addressable hash chain
- Multi-backend signing (HMAC-SHA256, RSA-SHA256, Ed25519)

Export to Markdown, HTML, PDF, SARIF, or CSV. This is not a log file. It is an audit-ready document that proves a decision was rigorously examined.

### 3. Calibrated Trust (ELO + Brier Scores)

Not all models are equally good at everything. Aragora tracks:

- **ELO ratings** per agent per domain -- a model that excels at legal reasoning might be weak on code review
- **Brier scores** measuring prediction calibration -- does the model's confidence match its actual accuracy?
- **Multi-factor vote weighting** combining reputation, reliability, consistency, calibration, and verbosity normalization
- **Performance feedback loops** that adjust agent selection based on historical outcomes

Over time, the system learns which models to trust for which kinds of decisions. This is calibrated trust, not blind trust.

### 4. Self-Improving Nomic Loop

Aragora includes an autonomous self-improvement system where agents debate improvements to the platform itself, design solutions, implement code, and verify changes. Safety rails include automatic backups, protected file checksums, rollback on failure, and human approval gates. The system cannot modify its own safety constraints.

The MetaPlanner uses multiple codebase signal sources for self-directed goal generation, and now automatically extracts improvement goals from debate outcome patterns -- when debates consistently show low consensus or recurring failure modes, the system self-directs toward fixing those weaknesses.

This is how the platform grew from a debate engine to 3,200+ modules with 208,000+ tests. No competitor has anything equivalent -- it is a structural advantage that compounds over time.

---

## How Aragora Compares

### vs. LangChain / LangGraph ($260M raised)

LangChain is plumbing -- an excellent framework for connecting LLM calls into chains and graphs. It helps you build AI applications. It does not adversarially vet decisions, produce audit trails, or track model calibration. LangGraph coordinates agents that cooperate; Aragora coordinates agents that challenge each other.

**Use LangGraph to build your agent pipeline. Route the output through Aragora to vet the decision before it ships.**

### vs. CrewAI ($25M raised)

CrewAI builds cooperative agent teams with role-based task delegation. This is effective for automation: a researcher agent feeds data to an analyst agent that produces a report. But cooperative agents do not challenge each other's conclusions. When CrewAI agents disagree, it is treated as a bug. When Aragora agents disagree, it is treated as a signal.

**Use CrewAI for task automation. Use Aragora when disagreement is the feature, not the bug.**

### vs. OpenAI Agents SDK

Single-provider lock-in. All agents run on OpenAI models, which share the same training data, the same RLHF biases, and the same failure modes. This is adversarial debate with correlated witnesses -- the debate structure adds overhead without adding diversity. Aragora's heterogeneous multi-provider approach ensures genuine independence across debaters.

### vs. Credo AI / Holistic AI

These tools govern AI systems from the outside -- monitoring bias, generating compliance reports, auditing model behavior after deployment. They do not improve the decisions themselves. Aragora generates compliance-ready audit trails as a byproduct of adversarially improving the decision. The audit trail is not documentation of what happened -- it is proof that the decision was rigorously examined.

### Where Competitors Are Stronger (Honest Assessment)

- **Community and ecosystem.** LangChain has massive adoption, a mature plugin ecosystem, and extensive tutorials. Aragora is young.
- **Funding.** LangChain ($260M), CrewAI ($25M), Microsoft and OpenAI (infinite budgets). Aragora is bootstrapped.
- **Simplicity for automation.** For straightforward task pipelines, CrewAI's decorator-based API is simpler than running a full debate.
- **Documentation breadth.** LangGraph and CrewAI have video walkthroughs and large community example libraries.

Aragora's advantage is depth in a specific domain: adversarial decision vetting with calibrated trust and cryptographic audit trails. If you need cooperative task automation, use LangGraph. If you need decisions you can defend in an audit, use Aragora.

---

## EU AI Act Alignment

The EU AI Act (enforcement for high-risk AI systems begins **August 2, 2026** -- six months from now) mandates:

| Requirement | EU AI Act Article | How Aragora Addresses It |
|---|---|---|
| Risk management | Article 9 | Adversarial debate surfaces risks before deployment; Gauntlet mode stress-tests specifications |
| Transparency | Article 13 | Decision Receipts provide complete reasoning traces with each model's position and dissent |
| Human oversight | Article 14 | Debate transcripts and confidence scores enable informed human review; split opinions flag uncertainty |
| Record keeping | Article 12 | Cryptographic receipts with SHA-256 hash chains provide tamper-evident audit trails |
| Accuracy & robustness | Article 15 | Multi-model consensus reduces single-point-of-failure; calibrated trust tracks reliability over time |

Organizations deploying AI in healthcare, finance, legal, and hiring will need to demonstrate that decisions were rigorously vetted. Aragora generates compliance artifacts as a **byproduct** of its normal operation -- not as a separate auditing step bolted on after the fact.

Tools that add auditing after deployment are architecturally inferior: they observe the decision but do not improve it.

---

## The Category: Decision Integrity

**Decision Integrity** is the practice of using adversarial multi-agent AI to vet, challenge, and audit important decisions before they ship -- producing cryptographic proof that the decision was rigorously examined.

This is distinct from:

| Category | What it does | What it does not do |
|---|---|---|
| **AI Observability** | Monitors model behavior after deployment | Does not improve decision quality before shipping |
| **AI Governance** | Generates compliance paperwork | Does not adversarially test the decision itself |
| **Agent Orchestration** | Coordinates agents on cooperative tasks | Does not challenge or vet agent outputs |
| **Decision Integrity** | Adversarially vets decisions and produces audit trails | **This is what Aragora does** |

No well-funded competitor builds adversarial decision vetting. They build cooperative orchestration. The category is new -- and the regulatory environment is about to make it mandatory.

---

## Get Started

```bash
# Install
pip install aragora

# Review code with multi-agent consensus (no API keys needed in demo mode)
git diff main | aragora review --demo

# Stress-test a specification
aragora gauntlet spec.md --profile thorough --output receipt.html

# Run a multi-agent debate
export ANTHROPIC_API_KEY=your-key
aragora ask "Should we adopt microservices?" --agents anthropic-api,openai-api,gemini --rounds 3

# Start the API server
aragora serve
```

Full documentation: [Getting Started Guide](guides/GETTING_STARTED.md) | [Developer Quickstart](QUICKSTART_DEVELOPER.md) | [API Reference](./api/API_REFERENCE.md)

---

*See [COMMERCIAL_OVERVIEW.md](COMMERCIAL_OVERVIEW.md) for pricing and deployment options. See [ENTERPRISE_FEATURES.md](ENTERPRISE_FEATURES.md) for the full enterprise capabilities reference.*
