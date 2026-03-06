# External Agent Verification Guide

Use Aragora as a **verification and governance layer** for any AI agent framework. Run adversarial stress-tests on agent outputs, generate cryptographic decision receipts, and export findings as SARIF for CI/CD integration.

## Quick Start

### Install the SDK

```bash
pip install aragora-sdk
```

### Verify Any Agent Output (3 Lines)

```python
from aragora_sdk import AragoraClient

client = AragoraClient(base_url="https://api.aragora.ai", api_key="your-key")

# Run adversarial validation on any content
result = client.gauntlet.run(task="Review this architecture: microservices with shared DB")
print(result["verdict"])  # PASS, FAIL, or INCONCLUSIVE
print(result["findings"])  # List of identified vulnerabilities
```

### Get a Cryptographic Receipt

```python
# After a gauntlet run, get a tamper-proof receipt
receipt = client.gauntlet.get_receipt(result["gauntlet_id"])
print(receipt["hash"])         # SHA-256 content hash
print(receipt["timestamp"])    # ISO timestamp
print(receipt["agent_votes"])  # Individual agent assessments

# Export for compliance
client.gauntlet.export_receipt(result["gauntlet_id"], format="sarif")  # For GitHub Security tab
client.gauntlet.export_receipt(result["gauntlet_id"], format="html")   # Human-readable report
```

---

## Integration Patterns

### Pattern 1: Post-Execution Verification

Verify agent output after your framework completes. Works with any framework.

```python
from aragora_sdk import AragoraClient

client = AragoraClient(base_url="https://api.aragora.ai", api_key="your-key")

def verify_agent_output(output: str, context: str = "") -> dict:
    """Verify any agent's output through adversarial testing."""
    result = client.gauntlet.run(
        task=f"Verify this agent output:\n\n{output}\n\nContext: {context}",
        attack_rounds=3,
    )

    if result["verdict"] == "FAIL":
        findings = client.gauntlet.get_findings(result["gauntlet_id"])
        return {"safe": False, "findings": findings}

    receipt = client.gauntlet.get_receipt(result["gauntlet_id"])
    return {"safe": True, "receipt_hash": receipt["hash"]}
```

### Pattern 2: Multi-Agent Debate

Use Aragora's debate engine to get multiple AI agents to adversarially vet a decision.

```python
# Run a full debate with multiple agents
debate = client.debates.create(
    task="Should we migrate from PostgreSQL to MongoDB for our user service?",
    agents=["claude", "gpt", "gemini"],
    rounds=3,
    consensus_threshold=0.8,
)

# Check consensus
if debate["consensus_reached"]:
    print(f"Decision: {debate['decision']}")
    print(f"Confidence: {debate['confidence']}")

    # Verify the consensus formally
    proof = client.verification.verify_consensus(debate["debate_id"])
    print(f"Consensus valid: {proof['valid']}")
```

### Pattern 3: Formal Verification

Generate mathematical proofs of decision properties using Z3 or Lean backends.

```python
# Generate a formal proof
proof = client.verification.generate_proof(
    debate_id=debate["debate_id"],
    backend="z3",  # or "lean"
)

print(f"Proof status: {proof['status']}")  # verified, failed, timeout
print(f"Properties checked: {proof['properties']}")
```

---

## Framework-Specific Integration

### CrewAI

```python
from crewai import Agent, Crew, Task
from aragora_sdk import AragoraClient

# 1. Run your CrewAI workflow
crew = Crew(
    agents=[
        Agent(role="Researcher", goal="Find relevant data", ...),
        Agent(role="Analyst", goal="Analyze findings", ...),
    ],
    tasks=[Task(description="Analyze Q4 revenue trends", ...)],
)
result = crew.kickoff()

# 2. Verify with Aragora
client = AragoraClient(base_url="https://api.aragora.ai", api_key="your-key")
verification = client.gauntlet.run(
    task=f"Verify this analysis for accuracy and bias:\n\n{result}",
    attack_rounds=3,
)

# 3. Act on verdict
if verification["verdict"] == "PASS":
    receipt = client.gauntlet.get_receipt(verification["gauntlet_id"])
    print(f"Analysis verified. Receipt: {receipt['hash']}")
else:
    findings = client.gauntlet.get_findings(verification["gauntlet_id"])
    print(f"Issues found: {[f['title'] for f in findings]}")
```

### LangGraph

```python
from langgraph.graph import StateGraph
from aragora_sdk import AragoraClient

client = AragoraClient(base_url="https://api.aragora.ai", api_key="your-key")

# Add a verification node to your LangGraph workflow
def verify_output(state: dict) -> dict:
    """Aragora verification node for LangGraph."""
    result = client.gauntlet.run(
        task=f"Verify: {state['output']}",
        attack_rounds=2,
    )
    state["verification"] = {
        "verdict": result["verdict"],
        "gauntlet_id": result["gauntlet_id"],
    }
    return state

# Wire into your graph
graph = StateGraph(...)
graph.add_node("verify", verify_output)
graph.add_edge("generate", "verify")  # Verify after generation
```

### AutoGen

```python
from autogen import AssistantAgent, UserProxyAgent
from aragora_sdk import AragoraClient

client = AragoraClient(base_url="https://api.aragora.ai", api_key="your-key")

# Create a verification function for AutoGen
def aragora_verify(output: str) -> str:
    """Verify agent output via Aragora adversarial testing."""
    result = client.gauntlet.run(task=f"Verify: {output}")
    if result["verdict"] == "PASS":
        return f"VERIFIED: Output passed adversarial testing (receipt: {result['gauntlet_id']})"
    findings = client.gauntlet.get_findings(result["gauntlet_id"])
    return f"ISSUES FOUND: {[f['title'] for f in findings]}"

# Register as an AutoGen function
assistant = AssistantAgent("assistant", ...)
assistant.register_function({"aragora_verify": aragora_verify})
```

### LangChain (Native Integration)

Aragora has a built-in LangChain integration:

```python
from aragora.integrations.langchain import AragoraTool, AragoraRetriever

# Use as a LangChain Tool
tool = AragoraTool(
    api_base="https://api.aragora.ai",
    api_key="your-key",
)

# In your agent's toolbox
from langchain.agents import initialize_agent
agent = initialize_agent(
    tools=[tool, ...],
    llm=llm,
    agent="zero-shot-react-description",
)

# The agent can now call Aragora for adversarial debate
result = agent.run("Should we adopt this security policy?")
```

---

## MCP Integration (Claude Desktop / Cursor)

Aragora's MCP server exposes verification tools directly to Claude Desktop and Cursor.

### Configuration

Add to your MCP client config (`claude_desktop_config.json` or Cursor settings):

```json
{
  "mcpServers": {
    "aragora": {
      "command": "python",
      "args": ["-m", "aragora.mcp.server"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key",
        "ARAGORA_API_URL": "https://api.aragora.ai"
      }
    }
  }
}
```

### Available MCP Tools

| Tool | Description |
|------|-------------|
| `run_debate` | Run a multi-agent debate on any topic |
| `run_gauntlet` | Run adversarial stress-testing |
| `verify_consensus` | Verify debate consensus formally |
| `generate_proof` | Generate Z3/Lean formal proof |
| `get_consensus_proofs` | Retrieve existing proofs |
| `search_debates` | Search past debates |
| `fork_debate` | Fork and re-run a debate with modifications |
| `query_knowledge` | Query organizational knowledge base |
| `store_knowledge` | Store knowledge for future reference |
| `search_evidence` | Find evidence for claims |
| `cite_evidence` | Create formal citations |

### MCP Resources

| URI | Description |
|-----|-------------|
| `debate://{id}` | Access debate results |
| `agent://{name}/stats` | Agent performance stats |
| `consensus://{id}` | Formal verification proofs |
| `trending://topics` | Trending decision topics |

---

## CI/CD Integration

### GitHub Action

Add Aragora review to your PR workflow:

```yaml
# .github/workflows/aragora-review.yml
name: Aragora PR Review
on: [pull_request]

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: aragora/aragora-action@v1
        with:
          api_key: ${{ secrets.ARAGORA_API_KEY }}
          mode: review
          sarif_output: review-results.sarif
          gauntlet: true  # Enable adversarial stress-testing

      # Upload SARIF to GitHub Security tab
      - uses: github/codeql-action/upload-sarif@v3
        with:
          sarif_file: review-results.sarif
```

### SARIF Export

Export any gauntlet result as SARIF 2.1.0 for security tool integration:

```python
# Export as SARIF
sarif = client.gauntlet.export_receipt(gauntlet_id, format="sarif")

# Write to file for CI/CD
with open("results.sarif", "w") as f:
    f.write(sarif)
```

SARIF output integrates with:
- GitHub Security tab (Code Scanning)
- Azure DevOps
- VS Code SARIF Viewer
- Any SARIF 2.1.0 compatible tool

---

## SDK Reference

### Gauntlet API

```python
client.gauntlet.run(debate_id=None, task=None, attack_rounds=3, ...)  # Run validation
client.gauntlet.get_result(gauntlet_id)       # Get result details
client.gauntlet.list_results(verdict=None)     # List past results
client.gauntlet.get_receipt(gauntlet_id)       # Get cryptographic receipt
client.gauntlet.verify_receipt(gauntlet_id)    # Verify receipt integrity
client.gauntlet.export_receipt(gauntlet_id, format="json|html|sarif|csv|pdf|markdown")
client.gauntlet.get_findings(gauntlet_id)      # Get vulnerability findings
```

### Verification API

```python
client.verification.verify_consensus(debate_id)            # Verify consensus
client.verification.generate_proof(debate_id, backend="z3") # Generate formal proof
client.verification.verify_claim(claim, context, evidence)  # Verify a specific claim
client.verification.verify_receipt(receipt_id)              # Verify receipt integrity
client.verification.verify_batch(receipt_ids)               # Batch verification
```

### Debates API

```python
client.debates.create(task=..., agents=[...], rounds=3)  # Create debate
client.debates.get(debate_id)                             # Get debate result
client.debates.list(status=None, limit=20)                # List debates
client.debates.search(query=..., filters={})              # Search debates
```

---

## Async Support

All SDK methods have async equivalents:

```python
from aragora_sdk import AragoraAsyncClient

async def verify():
    client = AragoraAsyncClient(base_url="https://api.aragora.ai", api_key="your-key")
    result = await client.gauntlet.run(task="Verify this output...")
    receipt = await client.gauntlet.get_receipt(result["gauntlet_id"])
    return receipt
```

---

## Security Model

Aragora verification provides:

| Feature | Description |
|---------|-------------|
| **Multi-agent adversarial testing** | 43 agent types probe for weaknesses |
| **Cryptographic receipts** | SHA-256 signed, tamper-proof audit trail |
| **Formal verification** | Z3/Lean mathematical proofs of decision properties |
| **RBAC governance** | 360+ permissions, role hierarchy, tenant isolation |
| **Approval workflows** | Human-in-the-loop for high-risk decisions |
| **Sandbox isolation** | Docker/subprocess isolation for code execution |
| **Audit logging** | Immutable hash-chain audit trail with compliance export |

---

## OpenClaw Governance

Aragora provides a complete governance layer for OpenClaw autonomous agents:

- **Action filtering**: Deny-by-default policy with per-action rules
- **Approval workflows**: Human approval for destructive/sensitive actions
- **Credential vault**: AES-256-GCM encrypted credential storage
- **Sandbox execution**: Resource-limited container isolation
- **Bypass detection**: Secondary enforcement checks catch circumvention attempts
- **Audit trail**: Every action logged with cryptographic integrity

See [OpenClaw Integration Guide](./OPENCLAW_INTEGRATION.md) for details.
