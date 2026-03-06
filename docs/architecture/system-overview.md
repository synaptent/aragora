# System Overview

Top-level architecture of the Aragora platform -- a control plane for multi-agent
robust decision-making across organizational knowledge and channels.

## High-Level Architecture

```mermaid
flowchart TB
    subgraph Clients["Clients"]
        WebUI["Web UI"]
        CLI["CLI"]
        SDK["TypeScript / Python SDK"]
    end

    subgraph Server["Server Layer"]
        HTTP["HTTP API (3,000+ operations)"]
        WS["WebSocket Streams (22 modules)"]
        Handlers["640+ HTTP Handlers"]
        TTS["TTS / Voice Stream"]
    end

    subgraph Auth["RBAC and Auth"]
        OIDC["OIDC / SAML SSO"]
        MFA["MFA (TOTP / HOTP)"]
        RBAC["RBAC v2 (360+ permissions)"]
        Middleware["Auth Middleware"]
    end

    subgraph DebateEngine["Debate Engine"]
        Arena["Arena (orchestrator)"]
        Phases["Phase Pipeline"]
        Consensus["Consensus Detection"]
        Convergence["Convergence Analysis"]
        TeamSelector["Team Selector (ELO)"]
        PromptBuilder["Prompt Builder"]
    end

    subgraph Agents["Agents Layer (43 Agent Types)"]
        direction LR
        APIAgents["API Agents"]
        CLIAgents["CLI Agents"]
        Fallback["OpenRouter Fallback"]
        Airlock["Airlock Proxy"]
        CircuitBreaker["Circuit Breaker"]
    end

    subgraph AgentProviders["Providers"]
        direction LR
        Claude["Claude"]
        GPT["GPT"]
        Gemini["Gemini"]
        Grok["Grok"]
        Mistral["Mistral"]
        DeepSeek["DeepSeek"]
        Qwen["Qwen"]
    end

    subgraph Memory["Memory System"]
        Fast["Fast (1 min TTL)"]
        Medium["Medium (1 hr TTL)"]
        Slow["Slow (1 day TTL)"]
        Glacial["Glacial (1 week TTL)"]
        MemCoord["Memory Coordinator"]
    end

    subgraph Knowledge["Knowledge Mound"]
        Bridges["KnowledgeBridgeHub"]
        Adapters["41 Adapters"]
        Sync["Sync and Revalidation"]
        Federation["Federation"]
        SemanticSearch["Semantic Search"]
    end

    subgraph ControlPlane["Control Plane"]
        Registry["Agent Registry"]
        Scheduler["Task Scheduler"]
        Health["Health Monitor"]
        Policy["Policy Governance"]
        Leader["Leader Election"]
    end

    subgraph Connectors["Connectors"]
        direction LR
        Slack["Slack"]
        Teams["Teams"]
        Telegram["Telegram"]
        Discord["Discord"]
        WhatsApp["WhatsApp"]
        GitHub["GitHub"]
        Kafka["Kafka"]
        RabbitMQ["RabbitMQ"]
    end

    subgraph Persistence["Persistence"]
        Supabase["Supabase / Postgres"]
        Redis["Redis Cache"]
    end

    Clients --> Server
    Server --> Auth
    Auth --> DebateEngine
    DebateEngine --> Agents
    Agents --> AgentProviders
    Agents --> CircuitBreaker
    CircuitBreaker --> Fallback
    DebateEngine --> Memory
    DebateEngine --> Knowledge
    ControlPlane --> DebateEngine
    ControlPlane --> Agents
    Connectors --> Server
    Knowledge --> Persistence
    Memory --> Persistence
    ControlPlane --> Persistence
```

## Component Responsibilities

| Layer | Key Modules | Purpose |
|-------|-------------|---------|
| Server | `unified_server.py`, `handlers/`, `stream/` | HTTP/WS API surface, TTS, voice |
| Auth | `rbac/`, `auth/` | OIDC/SAML SSO, MFA, fine-grained RBAC |
| Debate Engine | `debate/orchestrator.py`, `consensus.py` | Multi-round structured debates |
| Agents | `agents/api_agents/`, `cli_agents.py` | 43 agent types across 6+ LLM providers with fallback |
| Memory | `memory/continuum/core.py`, `coordinator.py` | Four-tier memory with atomic writes |
| Knowledge | `knowledge/mound/`, `bridges.py` | 45 registered adapters, semantic search, federation |
| Control Plane | `control_plane/` | Registry, scheduling, health, policy |
| Connectors | `connectors/` | Chat platforms, enterprise event streams |
| Persistence | External | Supabase/Postgres, Redis |

## Data Flow Summary

1. Requests enter via HTTP/WebSocket or connector webhooks.
2. Auth middleware validates identity and RBAC permissions.
3. The Debate Engine orchestrates agents through structured rounds.
4. Agents call external LLM providers; failures trigger circuit breaker and fallback.
5. Memory tiers cache context at varying lifetimes.
6. Knowledge Mound persists and federates organizational knowledge.
7. Control Plane governs scheduling, health, and policy across the system.
8. Results route back to the originating channel (web, Slack, Telegram, etc.).
