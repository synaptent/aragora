---
title: Introduction to Aragora
description: Control plane for multi-agent vetted decisionmaking across org knowledge and channels
sidebar_position: 1
---

# Introduction to Aragora

Aragora is the **control plane for multi-agent vetted decisionmaking across organizational knowledge and channels**. It orchestrates 43 agent types to debate your organization's knowledge (documents, databases, APIs) and deliver defensible decisions to any channel (Slack, Teams, Discord, voice).

## Why Multi-Agent Debate?

Single AI models have inherent biases and blind spots. Multi-agent debate addresses this by:

- **Diverse perspectives**: Different models (Claude, GPT, Gemini, etc.) bring unique reasoning approaches
- **Self-correction**: Agents critique and improve each other's responses
- **Consensus building**: Final answers represent agreement across multiple AI systems
- **Transparency**: The vetted decisionmaking process is fully auditable

## Core Features

### Heterogeneous Agents

Aragora supports agents from multiple providers:

| Provider | Models | Strengths |
|----------|--------|-----------|
| Anthropic | Claude 3.5, Claude 4 | Reasoning, safety |
| OpenAI | GPT-4, GPT-4o | General knowledge |
| Google | Gemini Pro, Gemini Flash | Multimodal, speed |
| xAI | Grok | Real-time knowledge |
| Open Models | Llama, Mistral, DeepSeek | Cost efficiency |

### Structured Debates

Debates follow configurable protocols:

```typescript
const protocol = {
  rounds: 3,
  phases: ['opening', 'critique', 'revision', 'vote'],
  consensus: {
    type: 'supermajority',
    threshold: 0.75,
  },
};
```

### Memory & Learning

Aragora maintains multi-tier memory for continuous improvement:

- **Fast memory**: Immediate context (session-scoped)
- **Medium memory**: Cross-session patterns
- **Slow memory**: Long-term strategic knowledge
- **Glacial memory**: Archived historical insights

### Knowledge Mound

The Knowledge Mound is Aragora's intelligent knowledge base that:

- Stores debate outcomes and evidence
- Supports semantic search across findings
- Enables knowledge sharing between workspaces
- Federates across organizational boundaries

## Use Cases

### Security Analysis

Deploy multiple AI agents to analyze code, infrastructure, or policies for vulnerabilities. Each agent brings different security expertise.

### Research Synthesis

Have agents debate and synthesize findings from multiple sources, ensuring comprehensive coverage and accurate conclusions.

### Decision Support

Complex business decisions benefit from multi-perspective analysis and structured vetted decisionmaking.

### Content Review

Quality assurance for generated content, documentation, and technical writing.

## Getting Started

Ready to start? Follow these guides:

1. [Quickstart](/docs/getting-started/quickstart) - Run your first debate in minutes
2. [Installation](/docs/getting-started/installation) - Set up Aragora in your environment
3. [First Debate](/docs/getting-started/first-debate) - Step-by-step tutorial

## Architecture Overview

```
                    ┌─────────────────────────────┐
                    │       Aragora Server        │
                    │  ┌─────────────────────────┐│
   Clients ────────▶│  │    Debate Orchestrator  ││
                    │  └──────────┬──────────────┘│
                    │             │               │
                    │  ┌──────────▼──────────────┐│
                    │  │      Agent Pool         ││
                    │  │ ┌─────┐┌─────┐┌─────┐   ││
                    │  │ │Claude││ GPT ││Gemini│  ││
                    │  │ └─────┘└─────┘└─────┘   ││
                    │  └──────────┬──────────────┘│
                    │             │               │
                    │  ┌──────────▼──────────────┐│
                    │  │   Memory & Knowledge    ││
                    │  │   ┌────────────────┐    ││
                    │  │   │ Knowledge Mound│    ││
                    │  │   └────────────────┘    ││
                    │  └─────────────────────────┘│
                    └─────────────────────────────┘
```

## Community

- [GitHub Repository](https://github.com/aragora/aragora)
- [Discord Community](https://discord.gg/aragora)
- [Twitter/X](https://twitter.com/aragora_ai)

## License

Aragora is available under [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html) for open-source use, with commercial licenses available for enterprise deployments.
