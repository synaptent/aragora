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

> Part of the [Aragora Decision Integrity Platform](https://github.com/synaptent/aragora).
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

All package-specific `ARAGORA_*` environment variables are optional:

| Variable | Default | Meaning |
|----------|---------|---------|
| `ARAGORA_LOG_FORMAT` | `text` | `json` selects JSON lines; any other value selects text |
| `ARAGORA_LOG_LEVEL` | `WARNING` | Case-insensitive stdlib logging level; invalid names fall back to WARNING |

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

## Logging

Importing the package does not configure logging or import telemetry SDKs.
Logging is local only, with no PostHog/Sentry client or network exporter.
Opt in explicitly at application startup:

```python
from aragora_debate._logging import configure_logging

configure_logging()
```

This replaces root handlers with one stderr handler, including on repeated
calls. Defaults are plain `LEVEL logger: message` text at WARNING (INFO is
suppressed). Set `ARAGORA_LOG_FORMAT=json` for one JSON object per line:
`ts` (UTC ISO-8601 timestamp), `level`, `logger`, and `msg`; optional fields are
`exception`, `stack`, and structured extras.

Both formatters use `redact()` to mask values as `***`. Redaction is name-based
and takes linear time. A value is masked when it follows a name containing a
secret word, `(?i)(api[_-]?key|token|secret|password|authorization)`, anywhere
in the name: as a key in nested mappings and sequences, or in a message as a
`key=value` or `key: value` assignment (quoted keys and values as in JSON or
Python reprs, keys with dots, spaces or colons such as
`http.request.header.authorization`, and Bearer/Basic values), as a header
tuple, a name/value list inside a list or tuple, a two-argument exception, an
`OrderedDict` repr, or a HAR entry or `header` object with the name first
(`('Authorization', '…')`, `[["X-Api-Key", "…"]]`,
`{"name": "Authorization", "value": "…"}`, `{"header": "X-Api-Key", "value": "…"}`,
also with spaces, tabs or JSON indentation in between, written as is or inside up
to three levels of repr or JSON strings that escape its line breaks and tabs as
`\n`, `\r` or `\t`, such as `repr(json.dumps(pairs, indent=2))` or an exception
holding that text), or after Authorization
phrasing (`Authorization header: …`,
`Authorization value = …`, or an Authorization word followed on its line by a
scheme such as `Bearer …`, with no `=` or `:` in between). An unquoted value
ends at whitespace, or at a `,` `;` `}` `]` that is followed by whitespace, a
quote, another of them, the end, or another secret name and its separator
(`token=a,b` masks `a,b`; `token=a,secret=b` masks `a` and `b` separately); a
list, tuple or object value that closes within one bracket level is masked inside
its brackets (`[***]`).

An `Authorization` or `Proxy-Authorization` value is masked whole without being
parsed, whatever the scheme: the scheme, the credential, every parameter and the
rest of the line, including continuation lines that start with a space or tab.
That holds inside a JSON or Python-repr string too, so the rest of the line after
the header name is masked, past the string's closing quote; only a quoted key
with a quoted value that closes its container (`{"Authorization": "…", "n": 1}`)
masks just that string. Where a value's end is uncertain, the rest of its line
is masked: after a backslash-escaped key quote (a JSON string inside another, or
`%r` of a string holding both quote kinds), a header tuple or HAR name/value
pair (inside a repr or JSON string, past its escaped line breaks and closing
quote), a bracket that does not close within one level, a quoted or bracketed
value that runs on into more text (`'x'y`, `(x)y`), a value that opens with an
escaped quote (a repr inside a JSON string), an unquoted value that ends in
another secret name and its separator, or a value that runs into an
`Authorization` name. A secret value that starts before that line end and
runs past it is masked to the end of its own line, and pprint string literals
that continue a quoted value are masked with it. A HAR entry written one field
per line (`json.dumps(..., indent=0)`, indented JSON or pprint) is masked from
its name to the end of the text, or up to the first line that starts with an
unindented `}` or `]` at or after the line where a `}` or `]` starts at the
name's indentation or less (outside the containers its other fields open). Its
other fields are masked with its value, and in indented JSON so are the entries
after it, up to that line. A HAR `value` field found shortly after the masked
text, with no `{` or `}` in between, is masked with it, and the mask goes on
from there. A bracket that ends its line without closing within one level
(`json.dumps(..., indent=0)` of a list whose strings hold escaped quotes) also
masks the lines after it, up to the line where its closing bracket starts at
the key's indentation, or to the end of the text.

Objects passed to `redact()`, as `%`-arguments or as extras are redacted item by
item, and a name/value pair is recognised by its shape: a two-item list or tuple whose first
item is a string naming a secret, or a mapping whose `name` or `header` field (in
any case) names one, has its second item or its `value` field masked at any depth
(`list(headers.items())` becomes `[('Accept', '*/*'), ('X-Api-Key', '***')]`, a
HAR header `{'name': 'Authorization', 'value': '***'}`). For these structured
pairs `Cookie` and `Set-Cookie` count as secret names too, and a bytes name counts
when its value is bytes (raw headers). Log objects rather than their repr: JSON
extras keep their other fields readable, while the text formatter redacts its
whole line, so the rest of a text line after a masked pair is masked as in a
message. Sets and bytes keep their type; bytes that are not UTF-8 are masked whole.

Matching fails closed, so it over-masks: labels such as `token_count: 5` are
masked, keys such as `authorization_token` or `Authorization.value` get
Authorization handling, and the rest of the line is masked after the uncertain
forms above and after an Authorization phrase with a scheme
(`Invalid Authorization header format - expected 'Bearer <token>'` loses
`Bearer <token>'`). A two-item list whose first item is a secret name is taken for
a name/value pair even when it lists names: as an object `['api_key', 'model']`
becomes `['api_key', '***']`, and in text a list inside a list or tuple,
`[['api_key', 'model']]`, becomes `[['api_key', ***`, while a list on its own in
text (`missing ['api_key', 'model']`) stays readable. A mapping whose `name` field
holds a secret word has its `value` masked (`{'name': 'token_count', 'value': '***'}`).
Mapping keys JSON cannot encode become strings with their values
masked, and a container that contains itself is logged as `<cycle>`. When the
arguments do not fit the format string or cannot be converted, the message
template is logged with an `[unformattable log arguments: …]` note instead of
the arguments. If any other part of a record cannot be formatted, either
formatter writes one JSON line with the redacted template and a `format_error`
field naming the exception type, and the handler from `configure_logging()`
reports a failed write by error type only. Interpolated messages and exceptions
are redacted without mutating the original record.

### Remaining limitations

These forms still leave a secret visible; avoid logging them:

- A raw line feed inside a quoted Digest parameter (invalid HTTP): the
  Authorization mask ends at that physical line, so the parameters after it
  stay visible.
- A name and value split across separate `%`-arguments when the name ends
  another secret's unquoted value
  (`logger.warning("%s%s", "token=x&Authorization:", " Bearer …")`): arguments
  are redacted one at a time, and the second one has no name.
- Unquoted values containing spaces for keys other than Authorization
  (`password=correct horse battery`): only the first word is masked. Quote the
  value or log the mapping.
- pprint output that wraps a value onto the next string literal
  (`'password: '` followed by `'…'` on the next line).
- HAR entries serialized with the value before the name
  (`{"value": "…", "name": "Authorization"}`); logged as an object, such an
  entry is masked.
- In text, a two-item list that is not inside another list or tuple
  (`["X-Api-Key", "…"]`): it reads as a list of names, as
  `['api_key', 'model']` does. Logged as an object, it is masked.
- In text, a pair whose outer bracket, or whose `name` or `header` field,
  starts more than 64 characters before the name, as in deeply indented JSON
  (a list of pairs seven objects deep at `indent=4`, fourteen at `indent=2`;
  with its line breaks escaped, six at `indent=4`, and fourteen, thirteen or
  twelve at `indent=2` for one, two or three levels of escaping).
- Text escaped so many times that more than seven backslashes stand before a
  quoted name or before the `n`, `r` or `t` of an escaped line break or tab,
  such as indented JSON of a list of pairs escaped four times by `repr()` or
  `json.dumps()`, or JSON text escaped four times when `json.dumps()` comes
  first: names and pairs are read through three levels of escaping.
- `Cookie` and `Set-Cookie` pairs in text (`[('Cookie', 'sid=…')]`): only
  structured pairs count those names.
- Pairs whose name holds no secret word (`('X-Session-Id', '…')`), and
  mappings that hold the header name under a key other than `name` or `header`.
- A HAR entry or `header` object whose name is bytes
  (`{'name': b'X-Api-Key', 'value': b'…'}`).
- As objects in `redact()` and JSON extras: a list or tuple of another length
  whose first item names a secret (`('X-Api-Key', '…', 'v2')`), a bytes name
  with a str value (`(b'X-Api-Key', '…')`), and a name/value mapping that holds
  the value under a key other than `value`. Text output (the text formatter and
  `%`-arguments) masks these tuples and mappings with the rest of the line.
- Secret values nested more than one container level across lines, such as
  `json.dumps(..., indent=0)` of nested lists under a secret key.
- Credentials logged with no name at all (`calling upstream with Bearer …`):
  unlabelled sensitive text is not recognized, so avoid logging credentials or
  user content.

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

See [EU_AI_ACT_COMPLIANCE.md](https://github.com/synaptent/aragora/blob/main/docs/EU_AI_ACT_COMPLIANCE.md)
for the full mapping.

## Full platform

`aragora-debate` is the standalone debate engine extracted from the
[Aragora Decision Integrity Platform](https://github.com/synaptent/aragora).
The full platform adds 42+ agent types, knowledge management, enterprise auth,
compliance frameworks, and the Nomic Loop for autonomous self-improvement.

## License

MIT -- see [LICENSE](LICENSE) for details.
