# Show HN: Aragora -- Adversarial AI debate engine with decision receipts

## HN Title (80 chars max)
```
Show HN: Aragora -- Pit LLMs against each other, get auditable decision receipts
```

## HN Post Body

I built an adversarial multi-model debate engine. Instead of asking one LLM and trusting the answer, Aragora makes multiple models propose solutions, critique each other's reasoning, vote, and produce a cryptographic decision receipt.

**The problem:** Single-model answers are unreliable. Stanford's recent taxonomy of LLM reasoning failures [1] shows systematic breakdowns even in frontier models. Models are overconfident when wrong. They agree with whatever you seem to want. And there's no audit trail.

**The approach:** Treat each model as an unreliable witness. Run structured debate (Propose / Critique / Vote / Synthesize) across models with different training data and failure modes. When heterogeneous models converge after adversarial challenge, that convergence is meaningful. When they disagree, the dissent trail tells you exactly where human judgment is needed.

**Try it now (no API keys needed):**

```
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

asyncio.run(demo())
"
```

**With real models (bring your own API keys):**

```python
from aragora_debate import Arena, DebateConfig, create_agent

agents = [
    create_agent("anthropic", name="analyst"),
    create_agent("openai", name="challenger"),
    create_agent("anthropic", name="devil-advocate", model="claude-haiku-4-5-20251001"),
]
result = await Arena(question="Your question", agents=agents).run()
```

**What you get:**
- Decision receipt with consensus proof, dissent tracking, and SHA-256 signature
- Hollow consensus detection (catches when models agree without evidence)
- Works with Anthropic, OpenAI, Mistral, Google, or any custom LLM
- Zero required dependencies for the core engine
- EU AI Act compliance artifacts as a byproduct

**Good for:** Architecture decisions, security reviews, compliance assessments, vendor evaluations, risk analysis -- anything worth a meeting.

**Not good for:** Simple lookups, creative generation, real-time responses.

Multi-agent debate achieves +13.8pp accuracy over single-model baselines [2] and significantly reduces hallucinations [3].

PyPI: https://pypi.org/project/aragora-debate/
GitHub: https://github.com/synaptent/aragora
Full platform (web UI, 46 agent types, SDKs): https://aragora.ai

[1] https://arxiv.org/abs/2602.06176
[2] https://arxiv.org/abs/2410.04663
[3] https://arxiv.org/abs/2305.14325

---

## Reddit r/MachineLearning Title
```
[P] Aragora: Open-source adversarial debate engine that pits LLMs against each other and produces auditable decision receipts
```

## Reddit r/LocalLLaMA Title
```
Aragora: Pit multiple LLMs against each other in structured debates -- get consensus, dissent trails, and cryptographic decision receipts (pip install aragora-debate)
```

## Twitter/X Thread

**Tweet 1:**
Just shipped aragora-debate: an adversarial multi-model debate engine.

Instead of trusting one LLM, make multiple models propose, critique each other, vote, and produce a cryptographic decision receipt.

Try it now (no API keys):
pip install aragora-debate

Thread below.

**Tweet 2:**
The problem: single-model answers are unreliable.

Models are overconfident when wrong. They agree with whatever you seem to want. And there's zero audit trail.

Stanford's recent work shows systematic reasoning failures even in frontier models.

**Tweet 3:**
The fix: treat each model as an unreliable witness.

Structured debate across heterogeneous models:
1. Propose -- independent responses
2. Critique -- challenge each other
3. Vote -- weighted consensus
4. Receipt -- cryptographic audit trail

When different models converge after adversarial challenge, it means something.

**Tweet 4:**
Every debate produces a Decision Receipt:
- Verdict + confidence score
- Who agreed, who dissented and why
- Evidence quality scores
- SHA-256 signature for tamper detection

Satisfies EU AI Act Art. 12-14, SOC 2, HIPAA audit requirements.

**Tweet 5:**
Works with Claude, GPT, Mistral, Gemini, or any custom LLM.

Zero required dependencies for the core engine. Built-in hollow consensus detection catches when models agree without evidence.

https://pypi.org/project/aragora-debate/
https://github.com/synaptent/aragora
