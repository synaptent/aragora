[![PyPI version](https://img.shields.io/pypi/v/aragora-debate)](https://pypi.org/project/aragora-debate/)
[![Python 3.10+](https://img.shields.io/pypi/pyversions/aragora-debate)](https://pypi.org/project/aragora-debate/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-235%20passing-brightgreen)]()

# aragora-debate

**Pit LLMs against each other. Get decisions you can audit.**

Single-model answers are unreliable. Models are [overconfident when wrong](https://arxiv.org/abs/2602.06176), agree with whatever you seem to want, and leave no audit trail. `aragora-debate` fixes this by running structured adversarial debates: multiple models propose, critique each other, vote, and produce a cryptographic decision receipt.

**Try it now** -- no API keys needed:

```bash
pip install aragora-debate
python -c "
import asyncio
from aragora_debate import Arena, StyledMockAgent, DebateConfig

async def demo():
    agents = [StyledMockAgent('Analyst', style='supportive'),
              StyledMockAgent('Critic', style='critical'),
              StyledMockAgent('Judge', style='balanced')]
    result = await Arena(question='Should we use Kubernetes or stay on VMs?',
                         agents=agents, config=DebateConfig(rounds=2)).run()
    print(f'Verdict: {result.verdict.value} ({result.confidence:.0%} confidence)')
    print(f'Receipt: {result.receipt.receipt_id}')
    print(f'Consensus: {result.consensus_reached} | Rounds: {result.rounds_used}')

asyncio.run(demo())
"
```

> Part of the [Aragora Decision Integrity Platform](https://github.com/an0mium/aragora).
> This standalone package gives you the debate engine with no framework lock-in.

## Why adversarial debate?

| Problem | What debate does |
|---------|-----------------|
| LLMs fail at compositional reasoning ([Song et al., 2026](https://arxiv.org/abs/2602.06176)) | Multiple models cross-check each other's reasoning |
| Models are overconfident when wrong | Structured critique surfaces hidden weaknesses |
| Agreement between models != correctness | Heterogeneous models surface genuine uncertainty |
| No audit trail for AI-assisted decisions | Cryptographic decision receipts with dissent tracking |

Multi-agent debate achieves **+13.8 percentage points** accuracy over single-model
baselines ([Harrasse et al., 2024](https://arxiv.org/abs/2410.04663)) and
**significantly reduces hallucinations** ([Du et al., 2023](https://arxiv.org/abs/2305.14325)).

## Install

```bash
pip install aragora-debate

# With provider SDKs (to use real models)
pip install aragora-debate[anthropic]    # Claude
pip install aragora-debate[openai]       # GPT
pip install aragora-debate[all]          # All providers
```

## Quick start with real models

```python
import asyncio
from aragora_debate import Arena, DebateConfig, create_agent

async def main():
    agents = [
        create_agent("anthropic", name="analyst"),     # Uses ANTHROPIC_API_KEY
        create_agent("openai", name="challenger"),      # Uses OPENAI_API_KEY
        create_agent("anthropic", name="devil-advocate", model="claude-haiku-4-5-20251001"),
    ]

    result = await Arena(
        question="Should we migrate from REST to GraphQL?",
        agents=agents,
        config=DebateConfig(rounds=3, consensus_method="supermajority"),
    ).run()

    print(result.summary())
    print(result.receipt.to_markdown())

asyncio.run(main())
```

## Custom agents

Wrap any LLM by implementing three methods:

```python
from aragora_debate import Agent, Critique, Vote, Message

class MyAgent(Agent):
    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        return await call_my_llm(self.model, prompt)

    async def critique(self, proposal: str, task: str, **kw) -> Critique:
        resp = await call_my_llm(self.model, f"Critique this:\n{proposal}")
        return Critique(agent=self.name, target_agent=kw.get("target_agent", ""),
                       target_content=proposal, issues=[resp], severity=5.0)

    async def vote(self, proposals: dict[str, str], task: str) -> Vote:
        best = await call_my_llm(self.model, f"Pick the best:\n{proposals}")
        return Vote(agent=self.name, choice=best, reasoning="Most thorough")
```

## How it works

```
Round 1          Round 2          Round 3
┌──────────┐    ┌──────────┐    ┌──────────┐
│ PROPOSE   │    │ PROPOSE   │    │ PROPOSE   │
│ All agents│    │ Address   │    │ Final     │
│ respond   │    │ critiques │    │ positions │
├──────────┤    ├──────────┤    ├──────────┤
│ CRITIQUE  │    │ CRITIQUE  │    │ CRITIQUE  │
│ Challenge │    │ Deeper    │    │ Last      │
│ each other│    │ analysis  │    │ challenges│
├──────────┤    ├──────────┤    ├──────────┤
│ VOTE      │    │ VOTE      │    │ VOTE      │
│ Weighted  │    │ May stop  │    │ Final     │
│ votes     │    │ if agreed │    │ tally     │
└──────────┘    └──────────┘    └──────────┘
                                      │
                                ┌─────▼──────┐
                                │  RECEIPT    │
                                │ Consensus,  │
                                │ dissent,    │
                                │ signature   │
                                └────────────┘
```

Each round has three phases:

1. **Propose** — Every agent generates an independent response
2. **Critique** — Each agent challenges every other agent's reasoning
3. **Vote** — Agents vote on which proposal is strongest

Early stopping kicks in when consensus is reached before all rounds complete.
The final **decision receipt** captures who agreed, who dissented and why,
the confidence level, and a cryptographic signature for audit purposes.

## Evidence quality & hollow consensus detection

Not all agreement is meaningful. `aragora-debate` detects when models agree
*without substantive evidence* — a pattern called **hollow consensus**.

```python
from aragora_debate import EvidenceQualityAnalyzer, HollowConsensusDetector

analyzer = EvidenceQualityAnalyzer()
score = analyzer.analyze("According to a 2024 Gartner report, 73% of enterprises...")
print(f"Evidence quality: {score.overall:.2f}")  # 0.0–1.0

# Detect hollow consensus across agents
detector = HollowConsensusDetector()
alert = detector.check(
    responses={"claude": "I agree, this is great", "gpt4": "I also think it's great"},
    convergence_similarity=0.95,
)
if alert.detected:
    print(f"Hollow consensus: {alert.challenge}")
```

The **Trickster** system uses this automatically during debates to inject
challenge prompts when it detects agents converging without evidence:

```python
from aragora_debate import Debate, create_agent

debate = Debate(
    "Should we adopt microservices?",
    enable_trickster=True,       # Inject challenges on hollow consensus
    enable_convergence=True,     # Track proposal similarity across rounds
    trickster_sensitivity=0.7,   # Higher = more interventions
)
debate.add_agent(create_agent("mock", name="analyst"))
debate.add_agent(create_agent("mock", name="critic"))
result = await debate.run()
print(f"Trickster interventions: {result.trickster_interventions}")
print(f"Convergence detected: {result.convergence_detected}")
```

## Events & callbacks

Monitor debates in real-time with the event system:

```python
from aragora_debate import EventEmitter, EventType

def on_event(event):
    print(f"[{event.event_type.value}] round={event.round_num} {event.data}")

debate = Debate("Should we use Kafka?", on_event=on_event)
# Events: debate_start, round_start, proposal, critique, vote,
#         consensus_check, convergence_detected, trickster_intervention,
#         round_end, debate_end
```

## Cross-proposal analysis

Analyze evidence patterns across all proposals:

```python
from aragora_debate import CrossProposalAnalyzer

analyzer = CrossProposalAnalyzer()
analysis = analyzer.analyze({
    "claude": "According to Smith (2024), Kafka handles 1M msgs/sec...",
    "gpt4": "RabbitMQ has better delivery guarantees per Jones (2023)...",
})
print(f"Shared evidence: {len(analysis.shared_evidence)}")
print(f"Contradictions: {len(analysis.contradictions)}")
print(f"Evidence gaps: {len(analysis.evidence_gaps)}")
print(f"Weakest agent: {analysis.weakest_agent}")
```

## Decision receipts

Every debate produces a `DecisionReceipt` — an auditable artifact:

```
# Decision Receipt DR-20260211-a3f8c2

**Question:** Should we migrate from REST to GraphQL?
**Verdict:** Approved With Conditions
**Confidence:** 78%
**Consensus:** Reached (supermajority, 75% agreement)
**Agents:** claude, gpt4, mistral

## Dissenting Views

**mistral:**
- Caching complexity underestimated for existing CDN infrastructure
  > REST+BFF achieves 80% of benefits with 20% of migration risk
```

Export as Markdown, JSON, or HTML. Sign with HMAC-SHA256 for tamper detection.

```python
from aragora_debate import ReceiptBuilder

# Sign for audit compliance
ReceiptBuilder.sign_hmac(result.receipt, key="your-signing-key")

# Export
print(ReceiptBuilder.to_json(result.receipt))

with open("receipt.html", "w") as f:
    f.write(ReceiptBuilder.to_html(result.receipt))
```

## Consensus methods

| Method | Threshold | Use when |
|--------|-----------|----------|
| `majority` | >50% | General decisions |
| `supermajority` | >66.7% | Important decisions |
| `unanimous` | 100% | Safety-critical decisions |
| `weighted` | Configurable | When agent reliability varies |
| `judge` | N/A | One agent decides after hearing debate |

## Configuration

```python
DebateConfig(
    rounds=3,                          # Number of debate rounds
    consensus_method="supermajority",  # How consensus is determined
    consensus_threshold=0.6,           # For weighted consensus
    early_stopping=True,               # Stop when consensus reached
    early_stop_threshold=0.85,         # Confidence to trigger early stop
    min_rounds=1,                      # Minimum rounds before early stop
    timeout_seconds=300,               # Overall timeout (0 = none)
    require_reasoning=True,            # Agents must explain votes
)
```

## When to use adversarial debate

**Good fit:**
- Architecture decisions ("Kafka vs RabbitMQ?")
- Compliance reviews ("Does this meet SOC 2?")
- Risk assessments ("What are the risks of this vendor?")
- Strategy decisions ("Should we enter market X?")
- Security reviews ("Is this auth model sound?")

**Not a good fit:**
- Simple lookups ("What's the capital of France?")
- Creative generation ("Write me a poem")
- Real-time responses (debate takes seconds to minutes)

**Rule of thumb:** If the decision is worth a meeting, it's worth a debate.

## Built-in providers

| Provider | Class | Install | Default model |
|----------|-------|---------|---------------|
| Anthropic | `ClaudeAgent` | `pip install aragora-debate[anthropic]` | `claude-sonnet-4-5-20250929` |
| OpenAI | `OpenAIAgent` | `pip install aragora-debate[openai]` | `gpt-4o` |
| Mistral | `MistralAgent` | `pip install aragora-debate[mistral]` | `mistral-large-latest` |
| Google | `GeminiAgent` | `pip install aragora-debate[gemini]` | `gemini-3.1-pro-preview` |
| Mock | `MockAgent` | *(included)* | N/A |

Use the factory for quick setup:

```python
from aragora_debate import create_agent

agents = [
    create_agent("anthropic", name="analyst"),
    create_agent("openai", name="challenger"),
    create_agent("mistral", name="devil-advocate"),
]
```

## Extending

### Custom agents

Implement `Agent.generate()`, `Agent.critique()`, and `Agent.vote()`:

```python
class ClaudeAgent(Agent):
    def __init__(self, name: str = "claude"):
        super().__init__(name, model="claude-sonnet-4-5-20250929")
        import anthropic
        self.client = anthropic.AsyncAnthropic()

    async def generate(self, prompt, context=None):
        resp = await self.client.messages.create(
            model=self.model,
            max_tokens=2048,
            system=self.system_prompt or "You are a careful analyst.",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text

    async def critique(self, proposal, task, **kw):
        prompt = f"Task: {task}\n\nProposal to critique:\n{proposal}\n\nIdentify issues and suggest improvements."
        resp = await self.generate(prompt)
        return Critique(
            agent=self.name,
            target_agent=kw.get("target_agent", "unknown"),
            target_content=proposal,
            issues=[resp],
            severity=5.0,
        )

    async def vote(self, proposals, task):
        formatted = "\n\n".join(f"**{name}:** {text}" for name, text in proposals.items())
        prompt = f"Task: {task}\n\nProposals:\n{formatted}\n\nWhich is strongest? Reply with just the agent name."
        choice = await self.generate(prompt)
        return Vote(agent=self.name, choice=choice.strip(), reasoning="Best analysis")
```

### Accessing debate history

```python
result = await arena.run()

# Full message history
for msg in result.messages:
    print(f"[Round {msg.round}] {msg.agent} ({msg.role}): {msg.content[:100]}")

# All critiques
for c in result.critiques:
    print(f"{c.agent} → {c.target_agent}: severity {c.severity}/10")

# Vote breakdown
for v in result.votes:
    print(f"{v.agent} voted for {v.choice} (confidence: {v.confidence})")
```

## Regulatory compliance

Decision receipts help satisfy:

- **EU AI Act Art. 12** — Automatic record-keeping
- **EU AI Act Art. 13** — Transparent, interpretable output
- **EU AI Act Art. 14** — Human oversight (review before acting)
- **SOC 2 CC6.1** — Audit logging
- **HIPAA 164.312(b)** — Audit controls

See [EU_AI_ACT_COMPLIANCE.md](https://github.com/an0mium/aragora/blob/main/docs/EU_AI_ACT_COMPLIANCE.md)
for the full mapping.

## Full platform

`aragora-debate` is the standalone debate engine extracted from the
[Aragora Decision Integrity Platform](https://github.com/an0mium/aragora).
The full platform adds 42+ agent types, knowledge management, enterprise auth,
compliance frameworks, and the Nomic Loop for autonomous self-improvement.

## License

MIT -- see [LICENSE](LICENSE) for details.
