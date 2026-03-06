# Golden Path 5: Knowledge-Enriched Debate

Query the Knowledge Mound for organizational data, inject it as debate context, and run a debate where agents reference real metrics and strategy documents.

## What it demonstrates

- Populating a knowledge store with organizational data (revenue, churn, strategy)
- Querying knowledge by relevance with importance-weighted scoring
- Injecting retrieved knowledge as debate context
- Agents grounding proposals in evidence from the knowledge store
- How knowledge enrichment improves decision quality vs. generic debate

## Run it

```bash
python examples/golden_paths/knowledge_query/main.py
```

No API keys or database required. Uses an in-memory mock knowledge store.

## Expected output

```
================================================================
  Aragora Golden Path: Knowledge-Enriched Debate
================================================================

Knowledge store initialized with 6 items.

Query: "What are our key business metrics and growth strategy?"

Retrieved 5 matching items (showing top 4):

  1. [finance] Q4 2025 Revenue Report (importance: 95%)
     Revenue grew 23% YoY to $4.2M in Q4 2025. SaaS ARR reached $12.8M...

  2. [leadership] Board Meeting Notes: Growth Strategy (importance: 90%)
     Board approved Q1 2026 priorities: 1) Expand enterprise sales team...

  3. [customer_success] Customer Churn Analysis (Jan 2026) (importance: 85%)
     Monthly churn rate dropped to 2.1% (from 3.4% in Q3)...

  4. [engineering] Engineering Velocity Report (importance: 80%)
     Sprint velocity increased 18% in Q4 after migrating to trunk-based...

--- Knowledge Context (injected into debate) ---
  [FINANCE] Q4 2025 Revenue Report:
  Revenue grew 23% YoY to $4.2M in Q4 2025. ...

--- Debate Result ---
Status:     consensus_reached
Consensus:  Reached
Confidence: 73%
Rounds:     1

--- Winning Recommendation ---
  Both perspectives have merit. I recommend a staged approach: ...

--- Decision Receipt: DR-20260224-... ---
  Verdict:    approved_with_conditions
  Confidence: 73%
  Agents:     growth-strategist, risk-analyst, product-lead
```

## How it maps to production

| Demo component | Production equivalent |
|---------------|----------------------|
| `MockKnowledgeStore` | `KnowledgeMound(workspace_id="...")` |
| `store.query()` | `km.query("...", limit=5)` with vector embeddings |
| `store.ingest()` | `km.ingest({"title": ..., "content": ...})` |
| Keyword matching | Semantic search via SentenceTransformer embeddings |
| In-memory storage | SQLite / PostgreSQL with 45 adapters |

## Key APIs used

| Import | Purpose |
|--------|---------|
| `aragora_debate.Arena` | Debate orchestrator with context injection |
| `aragora_debate.StyledMockAgent` | Agents with knowledge-grounded proposals |
| `Arena(context=...)` | Inject retrieved knowledge into the debate |

## Production usage

```python
from aragora.knowledge.mound.core import KnowledgeMound

km = KnowledgeMound(workspace_id="my-workspace")

# Ingest knowledge
await km.ingest({
    "title": "Q4 Revenue Report",
    "content": "Revenue grew 23% YoY...",
    "source": "finance",
    "importance": 0.9,
})

# Query with semantic search
results = await km.query("business metrics", limit=5)

# Build context for debate
context = "\n".join(
    f"- {item.title}: {item.content}"
    for item in results.items
)
```

## Next steps

- Connect to a real KnowledgeMound with `KnowledgeMound(workspace_id="...")`
- Enable cross-debate memory with `enable_cross_debate_memory=True`
- Use the unified memory gateway for fan-out queries across all memory systems
- Store debate results back into the Knowledge Mound for organizational learning
