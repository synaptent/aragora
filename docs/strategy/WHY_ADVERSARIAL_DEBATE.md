# Why Adversarial Debate?

> **One model's opinion isn't enough when the decision matters.**

---

## The Problem: LLMs Are Unreliable Decision-Makers

Large language models fail at reasoning in ways that matter for high-stakes decisions:

**Compositional reasoning breaks down.** Even two-hop reasoning — combining just two
facts — shows systematic failures. Performance degrades further with increased
compositional depth and distractors. Minor wording changes cause dramatic performance
swings in tasks trivial for human children.
([Song, Han & Goodman, 2026](https://arxiv.org/abs/2602.06176))

**The Reversal Curse.** Models trained on "A is B" cannot infer "B is A" — a
logically trivial operation that reveals fundamental architectural limitations, not
superficial prompting issues.
([Song et al., 2026](https://arxiv.org/abs/2602.06176))

**Overconfidence is systematic.** LLMs express high confidence even when wrong.
Current calibration methods are "not trustworthy enough" for high-stakes domains
like biomedical NLP, where a confidently wrong answer can be worse than no answer.
([PMC, 2025](https://pmc.ncbi.nlm.nih.gov/articles/PMC12249208/))

**The cost is real.** Poor decisions governing everyday operations cost organizations
3% of profits or more — a company with $5B revenue sacrifices upward of 3% of
earnings through flawed decision-making across thousands of material business
decisions annually.
([Gartner, 2018](https://www.gartner.com/en/newsroom/press-releases/2018-12-20-gartner-says-bad-financial-decisions-by-managers-cost-firms-more-than-3-percent-of-profits))

If you're using AI to assist with consequential decisions — architecture choices,
compliance reviews, hiring, strategy — you need more than one model's opinion.

---

## The Solution: Structured Adversarial Debate

Instead of asking one model and trusting the answer, Aragora orchestrates a
structured adversarial process across multiple models:

```
1. PROPOSE  → Multiple agents generate independent proposals
2. CRITIQUE → Agents challenge each other's reasoning
3. REVISE   → Proposals are strengthened in response to critiques
4. VOTE     → Consensus detection with dissent tracking
5. RECEIPT  → Cryptographic audit trail of the entire process
```

This isn't chat. It's adversarial vetting — the same principle behind peer review,
red teams, and the adversarial legal system.

### Why It Works: The Evidence

**+13.8 percentage points accuracy.** The D3 (Debate, Deliberate, Decide) framework
achieved 86.3% accuracy versus 72.5% baseline on MT-Bench, with similar gains across
AlignBench (+14.3 points) and AUTO-J (+13.6 points). Inter-rater reliability
improved by 33-36% (Cohen's Kappa). 58% of debates converged by round 2, reducing
token consumption by 40%.
([Harrasse, Bandi & Bandi, 2024](https://arxiv.org/abs/2410.04663))

**Reduced hallucinations.** Multi-agent debate "significantly enhances mathematical
reasoning and reduces factual hallucinations." Agents critiquing each other's
responses are "more incentivized to avoid outputting random information and
prioritize factual accuracy." Performance improves with both more agents and
more rounds of debate.
([Du et al., 2023](https://arxiv.org/abs/2305.14325);
[MIT News](https://news.mit.edu/2023/multi-ai-collaboration-helps-reasoning-factual-accuracy-language-models-0918))

**Industrial validation.** Mitsubishi Electric (January 2026) deployed the first
multi-agent AI in manufacturing using an argumentation framework for adversarial
debates among expert agents — enabling "rapid expert-level decision-making with
transparent reasoning" for security analysis, production planning, and risk
assessment.
([Mitsubishi Electric, 2026](https://www.mitsubishielectric.com/en/pr/2026/0120/))

---

## Why Not Just Use Multiple Models?

You could ask three models the same question and compare outputs. But this misses
the critical insight: **agreement between models doesn't mean correctness.**

### The Problem with Naive Consensus

When multiple models agree, it might mean:
- They're all correct (good)
- They share the same training bias (bad)
- The question is ambiguous and they're all interpreting it the same wrong way (bad)
- They're pattern-matching to the most common answer rather than reasoning (bad)

LMSYS Chatbot Arena data shows that top models have overlapping confidence intervals
and weekly ranking fluctuations — different evaluation approaches lead to disagreement
about relative model performance.
([LMSYS, 2026](https://lmsys.org/blog/2023-05-03-arena/))

### What Adversarial Debate Adds

1. **Structured critique forces reasoning.** Models must defend their positions
   against specific challenges, not just state conclusions. This surfaces the
   reasoning chain, making failures visible.

2. **Heterogeneous models surface genuine uncertainty.** Using Claude, GPT, Gemini,
   and local models together means different training data, different architectures,
   different failure modes. When they disagree, that disagreement is informative.

3. **Dissent tracking preserves minority views.** A 3-1 vote isn't the same as
   unanimous agreement. Aragora's decision receipts explicitly record who dissented
   and why — because the dissenting model might be right.

4. **Calibrated confidence over time.** ELO rankings and Brier scores track which
   agents are reliable on which domains. After 100 debates, you know that Agent X
   is 85% accurate on security reviews but only 60% on financial analysis.

---

## What Aragora Does Differently

### vs. CrewAI, LangGraph, AutoGen

These frameworks orchestrate **collaborative** multi-agent workflows. Agents work
together toward a shared goal. This is powerful for task execution, but it doesn't
validate decisions.

Aragora orchestrates **adversarial** multi-agent debates. Agents actively challenge
each other's reasoning. This is designed for **decision integrity** — ensuring the
decision is sound before acting on it.

| | CrewAI / LangGraph | Aragora |
|-|-------------------|---------|
| Agent relationship | Collaborative | Adversarial |
| Primary output | Task completion | Validated decision + receipt |
| When to use | Execute a plan | Vet a decision |
| Audit trail | Logs | Cryptographic receipts with dissent |
| Confidence | Model self-assessment | Calibrated via historical accuracy |

### vs. Fiddler, OneTrust, Azure AI

These tools monitor **deployed** AI systems for bias, drift, and compliance.
They're post-deployment governance.

Aragora is **pre-deployment decision vetting**. Before you act on an AI
recommendation, Aragora stress-tests it with adversarial agents and produces
an audit trail.

| | Governance Tools | Aragora |
|-|-----------------|---------|
| When | After deployment | Before decision |
| What | Monitor model behavior | Vet specific decisions |
| How | Statistical analysis | Adversarial debate |
| Output | Dashboards | Decision receipts |
| Cost | $100K+/year SaaS | Free, self-hosted |

---

## The Decision Receipt

Every Aragora debate produces a **decision receipt** — a cryptographic audit artifact:

```
Decision Receipt #DR-2026-0211-001
===================================
Question:     "Should we migrate from REST to GraphQL?"
Protocol:     Adversarial debate (3 rounds, supermajority)
Agents:       Claude-3.5, GPT-4o, Gemini-1.5, Mistral-Large

CONSENSUS:    PARTIAL (3/4 agents agree)
  Agreed:     GraphQL improves developer experience, reduces over-fetching
  Dissent:    Mistral-Large: "Caching complexity underestimated for
              existing CDN infrastructure. REST+BFF achieves 80% of
              benefits with 20% of migration risk."

Confidence:   0.78 (calibrated, Brier score 0.15)
Evidence:     12 claims evaluated, 3 challenged, 1 unresolved

Signature:    HMAC-SHA256:a3f8c2d1e5b7...
```

This receipt satisfies:
- **EU AI Act Art. 12** (automatic record-keeping)
- **EU AI Act Art. 13** (transparent, interpretable output)
- **EU AI Act Art. 14** (human oversight — humans review before acting)
- **SOC 2 CC6.1** (logical access controls and audit logging)
- **HIPAA 164.312(b)** (audit controls for electronic health information)

---

## Regulatory Context: The EU AI Act

The EU AI Act (Regulation 2024/1689) enforces requirements for high-risk AI systems
starting **August 2, 2026**. Organizations face penalties of up to 35M EUR or 7%
of global turnover for non-compliance.

Key requirements that adversarial debate addresses:

- **Art. 9 (Risk Management)**: Identify and evaluate foreseeable risks →
  Gauntlet red-team testing
- **Art. 12 (Record-Keeping)**: Automatic event logging over system lifetime →
  Decision receipts with cryptographic signing
- **Art. 13 (Transparency)**: Interpretable output with known limitations →
  Dissent tracking, calibrated confidence
- **Art. 14 (Human Oversight)**: Effective human control and intervention →
  Approval gates, advisory-only output
- **Art. 15 (Robustness)**: Resilience to errors and adversarial manipulation →
  Heterogeneous model consensus, hollow consensus detection

See [EU_AI_ACT_COMPLIANCE.md](../EU_AI_ACT_COMPLIANCE.md) for the full mapping.

---

## When to Use Adversarial Debate

### Good fit
- Architecture decisions ("Should we use Kafka or RabbitMQ?")
- Compliance reviews ("Does this system meet SOC 2 controls?")
- Risk assessments ("What are the risks of this vendor?")
- Strategy decisions ("Should we enter market X?")
- Hiring decisions ("Does this candidate meet the bar?")
- Security reviews ("Is this authentication model sound?")

### Not a good fit
- Simple lookups ("What's the capital of France?")
- Creative generation ("Write me a poem")
- Real-time responses (debate takes seconds to minutes)
- Tasks with objective answers easily verifiable by code

### Rule of thumb
> If the decision is worth a meeting, it's worth a debate.

---

## Getting Started

```python
from aragora import Arena, Environment, DebateProtocol

# Define the decision to vet
env = Environment(task="Should we migrate our authentication from sessions to JWT?")

# Configure the debate
protocol = DebateProtocol(
    rounds=3,
    consensus="supermajority",
    enable_dissent_tracking=True,
)

# Run adversarial debate across multiple models
result = await Arena(env, agents, protocol).run()

# Get the decision receipt
receipt = result.to_receipt()
receipt.export("decision-receipt.md", format="markdown")
```

---

## References

1. Song, P., Han, P., & Goodman, N. (2026). "Large Language Model Reasoning Failures."
   [arXiv:2602.06176](https://arxiv.org/abs/2602.06176)

2. Harrasse, A., Bandi, C., & Bandi, H. (2024). "D3: A Cost-Aware Adversarial Framework
   for Reliable and Interpretable LLM Evaluation."
   [arXiv:2410.04663](https://arxiv.org/abs/2410.04663)

3. Du, Y., et al. (2023). "Improving Factuality and Reasoning in Language Models through
   Multiagent Debate." [arXiv:2305.14325](https://arxiv.org/abs/2305.14325)

4. Mitsubishi Electric (2026). "Multi-Agent AI Technology with Argumentation Framework."
   [Press Release](https://www.mitsubishielectric.com/en/pr/2026/0120/)

5. Gartner (2018). "Bad Financial Decisions by Managers Cost Firms More Than 3% of Profits."
   [Report](https://www.gartner.com/en/newsroom/press-releases/2018-12-20-gartner-says-bad-financial-decisions-by-managers-cost-firms-more-than-3-percent-of-profits)

6. EU AI Act, Regulation (EU) 2024/1689, Articles 9, 11-15.
   [Full Text](https://artificialintelligenceact.eu/ai-act-explorer/)
