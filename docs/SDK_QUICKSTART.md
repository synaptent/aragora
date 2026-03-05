# SDK Quickstart

Install to first debate in under 2 minutes. No server, no API keys.

## Install

```bash
pip install aragora-debate
```

To connect to Claude, GPT, Mistral, or Gemini for real debates:

```bash
pip install aragora-debate[anthropic]    # Claude
pip install aragora-debate[openai]       # GPT
pip install aragora-debate[all]          # All providers
```

For the full Aragora platform (server, CLI, knowledge management, 43 agent types):

```bash
pip install aragora[all]
```

## Your First Debate (5 lines)

```python
import asyncio
from aragora_debate import Debate, create_agent

async def main():
    debate = Debate("Should we use microservices or a monolith?")
    debate.add_agent(create_agent("mock", name="analyst"))
    debate.add_agent(create_agent("mock", name="critic"))
    result = await debate.run()
    print(result.receipt.to_markdown())

asyncio.run(main())
```

That is a complete, runnable script. It uses built-in mock agents so you need
zero API keys and zero network access. Run it:

```bash
python my_first_debate.py
```

Or try the interactive CLI demo (also zero dependencies):

```bash
python -m aragora_debate
python -m aragora_debate --topic "Kafka vs RabbitMQ?" --rounds 3
python -m aragora_debate --topic "Should we adopt Kubernetes?" --trickster --convergence
```

## With Real Agents (10 lines)

Connect Claude and GPT for actual multi-model deliberation:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

```python
import asyncio
from aragora_debate import Debate, create_agent

async def main():
    debate = Debate(
        "Should we migrate from REST to GraphQL?",
        rounds=3,
        consensus="supermajority",
    )
    debate.add_agent(create_agent("anthropic", name="analyst"))
    debate.add_agent(create_agent("openai", name="challenger"))
    debate.add_agent(create_agent("anthropic", name="moderator"))

    result = await debate.run()

    print(f"Consensus: {result.consensus_reached} ({result.confidence:.0%})")
    print(f"Verdict: {result.verdict.value}")
    print(result.receipt.to_markdown())

asyncio.run(main())
```

Every agent independently proposes, critiques every other agent's reasoning,
and votes. This is not a chat -- it is a structured adversarial process with
propose/critique/vote phases each round.

## Decision Receipt

Every debate automatically produces a `DecisionReceipt` -- a cryptographic
audit artifact that records who agreed, who dissented and why, the confidence
level, and a content hash for tamper detection.

```python
from aragora_debate import ReceiptBuilder

# After running a debate:
receipt = result.receipt

# Print as Markdown
print(receipt.to_markdown())

# Export as JSON
print(ReceiptBuilder.to_json(receipt))

# Export as standalone HTML page
with open("receipt.html", "w") as f:
    f.write(ReceiptBuilder.to_html(receipt))

# Sign with HMAC-SHA256 for audit compliance
ReceiptBuilder.sign_hmac(receipt, key="your-signing-key")

# Verify signature integrity
assert ReceiptBuilder.verify_hmac(receipt, key="your-signing-key")
```

Example receipt output:

```
# Decision Receipt DR-20260213-a3f8c2

**Question:** Should we migrate from REST to GraphQL?
**Verdict:** Approved With Conditions
**Confidence:** 78%
**Consensus:** Reached (supermajority, 75% agreement)
**Agents:** analyst, challenger, moderator
**Rounds:** 2

## Dissenting Views

**challenger:**
- Caching complexity underestimated for existing CDN infrastructure
  > REST+BFF achieves 80% of benefits with 20% of migration risk
```

Receipts help satisfy EU AI Act Art. 12 (record-keeping), Art. 13
(transparency), SOC 2 CC6.1 (audit logging), and HIPAA 164.312(b) (audit
controls).

## Hollow Consensus Detection

Not all agreement is meaningful. Enable the Trickster to detect when agents
converge without substantive evidence:

```python
debate = Debate(
    "Should we adopt this vendor?",
    enable_trickster=True,       # Challenge hollow consensus
    enable_convergence=True,     # Track proposal similarity
    trickster_sensitivity=0.7,   # Higher = more interventions
)
```

When agents agree too quickly without evidence, the Trickster injects challenge
prompts to force deeper analysis.

## Connect to Slack

Post debate results to Slack with 3 lines:

```python
from aragora.integrations.slack import SlackIntegration, SlackConfig

slack = SlackIntegration(SlackConfig(
    webhook_url="https://hooks.slack.com/services/T.../B.../xxx",
    channel="#decisions",
))
await slack.post_debate_summary(result)
```

## Connect to Microsoft Teams

```python
from aragora.integrations.teams import TeamsIntegration, TeamsConfig

teams = TeamsIntegration(TeamsConfig(
    webhook_url="https://xxx.webhook.office.com/webhookb2/...",
))
await teams.post_debate_summary(result)
```

## What Is Happening Under the Hood

Each debate round has three phases:

```
Round 1              Round 2              Round 3
+------------+      +------------+      +------------+
| PROPOSE    |      | PROPOSE    |      | PROPOSE    |
| All agents |      | Address    |      | Final      |
| respond    |      | critiques  |      | positions  |
+------------+      +------------+      +------------+
| CRITIQUE   |      | CRITIQUE   |      | CRITIQUE   |
| Challenge  |      | Deeper     |      | Last       |
| each other |      | analysis   |      | challenges |
+------------+      +------------+      +------------+
| VOTE       |      | VOTE       |      | VOTE       |
| Weighted   |      | May stop   |      | Final      |
| votes      |      | if agreed  |      | tally      |
+------------+      +------------+      +------------+
                                              |
                                        +-----v------+
                                        |  RECEIPT   |
                                        | Consensus, |
                                        | dissent,   |
                                        | signature  |
                                        +------------+
```

Early stopping kicks in when consensus is reached before all rounds complete.

## Consensus Methods

| Method | Threshold | Use when |
|--------|-----------|----------|
| `majority` | >50% | General decisions |
| `supermajority` | >66.7% | Important decisions |
| `unanimous` | 100% | Safety-critical decisions |
| `weighted` | Configurable | When agent reliability varies |
| `judge` | N/A | One agent decides after hearing debate |

```python
debate = Debate(
    "Is this architecture production-ready?",
    consensus="unanimous",  # All agents must agree
    rounds=5,
    early_stopping=True,
)
```

## Full Platform Features

The standalone `aragora-debate` package gives you the debate engine. Install
the full platform for:

- **43 agent types** with ELO rankings and calibration tracking
- **Knowledge Mound** -- semantic search, contradiction detection, cross-debate learning
- **Gauntlet** -- adversarial stress-testing with attack/defend cycles
- **Workflow engine** -- DAG-based automation with 50+ templates
- **Enterprise auth** -- OIDC/SAML SSO, RBAC, multi-tenancy
- **Compliance** -- SOC 2, GDPR, EU AI Act artifact generation
- **REST API** -- 3,000+ operations across 2,900+ paths

```bash
pip install aragora[all]

# Start the server (SQLite, no external dependencies)
aragora serve --offline

# Run a debate from the CLI
aragora decide "Should we migrate to Kubernetes?" --rounds 3

# Interactive REPL
aragora repl
```

## Real-World Examples

| Example | What it does | File |
|---------|-------------|------|
| Basic debate + receipt | Run a debate, get signed receipt | [`examples/quickstart/basic_debate.py`](../examples/quickstart/basic_debate.py) |
| Batch claim verification | Verify multiple claims concurrently | [`examples/batch_verify_claims.py`](../examples/batch_verify_claims.py) |
| Slack bot | `/debate` command with streaming | [`examples/nodejs-slack-bot/`](../examples/nodejs-slack-bot/) |
| Healthcare review | Clinical decision vetting | [`examples/quickstart/healthcare_review.py`](../examples/quickstart/healthcare_review.py) |
| Gauntlet demo | Adversarial stress-testing | [`examples/gauntlet_demo.py`](../examples/gauntlet_demo.py) |
| TypeScript SDK | Basic debate in TypeScript | [`examples/typescript/01-basic-debate.ts`](../examples/typescript/01-basic-debate.ts) |

All examples work offline with mock agents (no API keys needed).

## Next Steps

| Goal | Guide |
|------|-------|
| Full SDK reference | [SDK Guide](SDK_GUIDE.md) |
| REST API docs | [API Reference](api/API_REFERENCE.md) |
| Gauntlet (adversarial validation) | [Gauntlet Guide](./debate/GAUNTLET.md) |
| Streaming events (WebSocket) | [WebSocket Events](./streaming/WEBSOCKET_EVENTS.md) |
| Self-host with Docker | [`deploy/README.md`](../deploy/README.md) |
| EU AI Act compliance | [EU AI Act Guide](compliance/EU_AI_ACT_GUIDE.md) |
