---
title: Credits and Attribution
description: Credits and Attribution
---

# Credits and Attribution

Aragora synthesizes ideas from these open-source projects.

## Foundational Inspiration

- **[Stanford Generative Agents](https://github.com/joonspk-research/generative_agents)** -- Memory + reflection architecture
- **[ChatArena](https://github.com/chatarena/chatarena)** -- Game environments for multi-agent interaction
- **[LLM Multi-Agent Debate](https://github.com/composable-models/llm_multiagent_debate)** -- ICML 2024 consensus mechanisms
- **[UniversalBackrooms](https://github.com/scottviteri/UniversalBackrooms)** -- Multi-model infinite conversations
- **[Project Sid](https://github.com/altera-al/project-sid)** -- Emergent civilization with 1000+ agents

## Borrowed Patterns (MIT/Apache Licensed)

We gratefully acknowledge these projects whose patterns we adapted:

| Project | What We Borrowed | License |
|---------|------------------|---------|
| **[ai-counsel](https://github.com/AI-Counsel/ai-counsel)** | Semantic convergence detection (3-tier fallback: SentenceTransformer > TF-IDF > Jaccard), vote option grouping, per-agent similarity tracking | MIT |
| **[DebateLLM](https://github.com/Tsinghua-MARS-Lab/DebateLLM)** | Agreement intensity modulation (0-10 scale), asymmetric debate roles (affirmative/negative/neutral stances), judge-based termination | Apache 2.0 |
| **[CAMEL-AI](https://github.com/camel-ai/camel)** | Multi-agent orchestration patterns, critic agent design | Apache 2.0 |
| **[CrewAI](https://github.com/joaomdmoura/crewAI)** | Agent role and task patterns | MIT |
| **[AIDO](https://github.com/aido-research/aido)** | Consensus variance tracking (strong/medium/weak classification), reputation-weighted voting concepts | MIT |
| **[claude-flow](https://github.com/ruvnet/claude-flow)** | Adaptive topology switching (diverging > parallel, refining > ring, converged > minimal), YAML agent configuration patterns, hooks system design | MIT |
| **[ccswarm](https://github.com/nwiizo/ccswarm)** | Delegation strategy patterns (content-based, load-balanced, hybrid), channel-based orchestration concepts | MIT |
| **[claude-code-by-agents](https://github.com/baryhuang/claude-code-by-agents)** | Cooperative cancellation tokens with linked parent-child hierarchy, abort control patterns | MIT |
| **[claude-squad](https://github.com/smtg-ai/claude-squad)** | Session lifecycle state machine concepts (pending > running > paused > completed), pause/resume patterns (implemented from scratch due to AGPL-3.0) | AGPL-3.0 (patterns only) |
| **[claude-agent-sdk-demos](https://github.com/anthropics/claude-agent-sdk-demos)** | Official Anthropic subagent patterns, parallel execution idioms | MIT |

## Implementations

See the borrowed patterns in action:

- `aragora/debate/convergence.py` -- Semantic convergence detection
- `aragora/debate/orchestrator.py` -- Orchestration patterns
- `aragora/debate/topology.py` -- Adaptive topology (claude-flow)
- `aragora/debate/session.py` -- Session lifecycle (claude-squad patterns)
- `aragora/debate/cancellation.py` -- Cancellation tokens (claude-code-by-agents)
