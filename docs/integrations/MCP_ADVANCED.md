# MCP Advanced Integration Guide

This guide covers advanced usage of Aragora's Model Context Protocol (MCP) server for integration with Claude and other MCP-compatible clients.

## Overview

The Aragora MCP server exposes debate functionality as tools and resources that can be accessed by Claude and other AI assistants.

## Quick Start

### Starting the Server

```bash
# Start MCP server
python -m aragora.mcp.server

# Or use the MCP development tool
mcp dev aragora/mcp/server.py
```

### Connecting with Claude Code

Add to your MCP configuration:

```json
{
  "mcpServers": {
    "aragora": {
      "command": "python",
      "args": ["-m", "aragora.mcp.server"],
      "env": {
        "ANTHROPIC_API_KEY": "your-key",
        "OPENAI_API_KEY": "your-key"
      }
    }
  }
}
```

## Available Tools

### Core Tools

#### run_debate

Run a multi-agent AI debate on any topic.

```json
{
  "name": "run_debate",
  "arguments": {
    "question": "Should AI systems be required to explain their decisions?",
    "agents": "anthropic-api,openai-api",
    "rounds": 3,
    "consensus": "majority"
  }
}
```

**Parameters:**
- `question` (required): The topic to debate
- `agents`: Comma-separated agent names (default: "anthropic-api,openai-api")
- `rounds`: Number of debate rounds, 1-10 (default: 3)
- `consensus`: Consensus method - "majority", "unanimous", "judge", "none"

**Returns:**
```json
{
  "debate_id": "debate-abc123",
  "consensus_reached": true,
  "confidence": 0.85,
  "final_answer": "The consensus is...",
  "rounds_used": 3,
  "agents": ["anthropic-api", "openai-api"]
}
```

#### run_gauntlet

Stress-test content through adversarial analysis.

```json
{
  "name": "run_gauntlet",
  "arguments": {
    "content": "API specification to analyze...",
    "content_type": "spec",
    "profile": "security"
  }
}
```

**Profiles:**
- `quick` - Fast basic analysis
- `thorough` - Comprehensive review
- `security` - Security-focused analysis
- `performance` - Performance implications

#### list_agents

Get available debate agents with their capabilities.

```json
{
  "name": "list_agents",
  "arguments": {}
}
```

**Returns:**
```json
{
  "agents": [
    {"name": "anthropic-api", "available": true, "model": "claude-opus-4-5-20251101"},
    {"name": "openai-api", "available": true, "model": "gpt-5.3"},
    {"name": "mistral-api", "available": true, "model": "mistral-large-2512"}
  ]
}
```

### Search & Discovery Tools

#### search_debates

Search debates by topic, date, or participating agents.

```json
{
  "name": "search_debates",
  "arguments": {
    "query": "AI regulation",
    "agent": "anthropic-api",
    "consensus_only": true,
    "limit": 10
  }
}
```

**Parameters:**
- `query`: Text search in topic
- `agent`: Filter by agent name
- `start_date`, `end_date`: Date range (YYYY-MM-DD)
- `consensus_only`: Only return debates that reached consensus
- `limit`: Max results (1-100, default: 20)

#### get_agent_history

Get an agent's debate history and performance stats.

```json
{
  "name": "get_agent_history",
  "arguments": {
    "agent_name": "anthropic-api",
    "include_debates": true,
    "limit": 10
  }
}
```

**Returns:**
```json
{
  "agent_name": "anthropic-api",
  "elo_rating": 1650,
  "elo_deviation": 35,
  "total_debates": 156,
  "consensus_rate": 0.72,
  "win_rate": 0.65,
  "avg_confidence": 0.78,
  "recent_debates": [...]
}
```

#### get_consensus_proofs

Retrieve formal verification proofs from debates.

```json
{
  "name": "get_consensus_proofs",
  "arguments": {
    "debate_id": "debate-abc123",
    "proof_type": "z3",
    "limit": 5
  }
}
```

**Proof Types:**
- `z3` - Z3 SMT solver proofs
- `lean` - Lean 4 proofs
- `all` - All proof types

#### list_trending_topics

Get trending topics from Pulse for potential debates.

```json
{
  "name": "list_trending_topics",
  "arguments": {
    "platform": "hackernews",
    "category": "ai",
    "min_score": 0.6,
    "limit": 10
  }
}
```

**Returns:**
```json
{
  "topics": [
    {
      "topic": "New breakthrough in AI reasoning",
      "platform": "hackernews",
      "category": "ai",
      "score": 0.85,
      "volume": 320,
      "debate_potential": "high"
    }
  ]
}
```

## Resource Templates

### Debate Results

Access debate results by ID:

```
debate://abc123
```

Example usage with Claude:
> "Please read the debate at debate://abc123 and summarize the key arguments."

### Agent Statistics

Access agent performance data:

```
agent://anthropic-api/stats
```

Returns ELO rating, debate history, and performance metrics.

### Trending Topics

Access current trending topics:

```
trending://topics
```

Returns scored topics from Pulse suitable for debates.

## Integration Patterns

### Pattern 1: Research Assistant

Use Aragora to validate decisions:

```
User: "Should we use microservices for our new project?"

Claude: [calls run_debate with the question]
        [returns debate summary with pros/cons and confidence]

Response: "Based on a debate between AI agents (85% confidence):
The consensus supports microservices for your use case because..."
```

### Pattern 2: Code Review

Stress-test specifications:

```
User: "Review this API spec for security issues"

Claude: [calls run_gauntlet with content_type="spec", profile="security"]
        [returns vulnerability analysis]

Response: "The gauntlet analysis identified 3 potential security concerns:
1. Missing rate limiting on /api/users endpoint...
2. ..."
```

### Pattern 3: Topic Discovery

Find interesting debate topics:

```
User: "What AI topics are trending that would make good debates?"

Claude: [calls list_trending_topics with category="ai", min_score=0.7]

Response: "Here are 5 high-potential debate topics from recent news:
1. 'Should AI models be required to have kill switches?' (score: 0.92)
2. ..."
```

### Pattern 4: Agent Performance Analysis

Analyze agent effectiveness:

```
User: "How has the Anthropic agent been performing?"

Claude: [calls get_agent_history with agent_name="anthropic-api"]

Response: "The Anthropic agent has an ELO rating of 1650 with:
- 156 total debates
- 72% consensus rate
- 65% win rate in adversarial debates
Recent debates show improved performance in technical topics..."
```

## Error Handling

### Common Errors

| Error | Cause | Solution |
|-------|-------|----------|
| "No valid agents available" | API keys not configured | Set ANTHROPIC_API_KEY, OPENAI_API_KEY |
| "Debate timeout" | Agents took too long | Reduce rounds or use faster agents |
| "Rate limited" | Too many requests | Wait and retry with backoff |
| "Debate not found" | Invalid debate_id | Use search_debates to find valid IDs |

### Retry Pattern

```python
import asyncio
from aragora.mcp.tools import run_debate_tool

async def run_with_retry(question: str, max_retries: int = 3):
    for attempt in range(max_retries):
        try:
            result = await run_debate_tool(question)
            if "error" not in result:
                return result
        except Exception as e:
            if attempt == max_retries - 1:
                raise
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

## Best Practices

### 1. Choose Appropriate Agents

```python
# For technical debates
agents = "anthropic-api,openai-api"

# For creative/broad topics
agents = "anthropic-api,openai-api,mistral-api"

# For quick validation
agents = "anthropic-api,openai-api"
rounds = 2
```

### 2. Use Appropriate Round Counts

| Debate Type | Recommended Rounds |
|-------------|-------------------|
| Quick validation | 2 |
| Standard debate | 3 |
| Deep analysis | 5 |
| Exhaustive | 7-10 |

### 3. Leverage Caching

Debate results are cached. Use `get_debate` to retrieve previous results:

```json
{
  "name": "get_debate",
  "arguments": {"debate_id": "debate-abc123"}
}
```

### 4. Monitor Agent Performance

Regularly check agent stats to ensure quality:

```json
{
  "name": "get_agent_history",
  "arguments": {"agent_name": "openai-api"}
}
```

### 5. Use Consensus Proofs for Verification

For critical decisions, retrieve formal proofs:

```json
{
  "name": "get_consensus_proofs",
  "arguments": {"debate_id": "debate-abc123", "proof_type": "z3"}
}
```

## Configuration

### Environment Variables

```bash
# Required (at least one)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Recommended for fallback
OPENROUTER_API_KEY=sk-or-...

# Optional additional providers
MISTRAL_API_KEY=...
XAI_API_KEY=...

# MCP server settings
MCP_SERVER_PORT=5000
MCP_LOG_LEVEL=INFO
```

### Server Options

```bash
# Start with custom port
python -m aragora.mcp.server --port 5001

# Enable debug logging
MCP_LOG_LEVEL=DEBUG python -m aragora.mcp.server
```

## Troubleshooting

### Server won't start

1. Check Python version (3.10+)
2. Verify MCP package installed: `pip install mcp`
3. Check API keys are set

### Tools not appearing

1. Restart Claude Code
2. Check MCP server logs for errors
3. Verify configuration JSON syntax

### Debates failing

1. Check agent API keys
2. Review quota limits
3. Try with fewer/different agents

### Slow responses

1. Reduce round count
2. Use faster agents (e.g., mistral-api)
3. Check network connectivity to API providers
