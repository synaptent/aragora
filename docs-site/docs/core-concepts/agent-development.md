---
title: Agent Development Guide
description: Agent Development Guide
---

# Agent Development Guide

Build custom AI agents for the Aragora debate framework.

## Overview

Aragora agents are autonomous participants in multi-agent debates. Each agent:
- Responds to prompts with positions and arguments
- Critiques other agents' responses
- Votes on proposals and consensus
- Learns from debate outcomes via ELO ratings

## Quick Start

### Minimal Agent

```python
from aragora.core import Agent, Critique, Message

class MyAgent(Agent):
    """A simple custom agent."""

    def __init__(self, name: str = "my-agent", model: str = "custom", role: str = "proposer"):
        super().__init__(name=name, model=model, role=role)

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        # Your logic here
        return "My response to the prompt"

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        return Critique(
            agent=self.name,
            target_agent="proposal",
            target_content=proposal[:200],
            issues=["Missing edge case analysis"],
            suggestions=["Address failure modes explicitly"],
            severity=0.4,
            reasoning=f"Quick critique for task: \{task\}",
        )
```

### Register and Use

```python
from aragora import Arena, Environment, DebateProtocol
from aragora.agents.base import create_agent
from aragora.agents.registry import AgentRegistry

# Register your agent for use with create_agent()
AgentRegistry.register(
    "my-agent",
    default_model="custom",
    agent_type="Custom",
)(MyAgent)

# Use in a debate
env = Environment(task="Discuss the best sorting algorithm")
protocol = DebateProtocol(rounds=3)
agents = [
    create_agent("anthropic-api"),
    create_agent("openai-api"),
    create_agent("my-agent"),
]
arena = Arena(env, agents, protocol)

result = await arena.run()
```

## Agent Architecture

### Base Agent Interface

```python
from aragora.core import Agent, Critique, Message, Vote

class Agent(ABC):
    """Abstract base class for all agents."""

    def __init__(self, name: str, model: str, role: str = "proposer"):
        self.name = name
        self.model = model
        self.role = role
        self.system_prompt = ""
        self.agent_type = "unknown"
        self.stance = "neutral"

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        """Generate a response to the prompt."""
        pass

    @abstractmethod
    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        """Critique another agent's proposal."""
        pass

    async def vote(self, proposals: dict[str, str], task: str) -> Vote:
        """Vote on proposals (default implementation uses generate())."""
        ...
```

### Core Models

```python
@dataclass
class Message:
    role: str
    agent: str
    content: str
    timestamp: datetime = field(default_factory=datetime.now)
    round: int = 0

@dataclass
class Critique:
    agent: str
    target_agent: str
    target_content: str
    issues: list[str]
    suggestions: list[str]
    severity: float
    reasoning: str

@dataclass
class Vote:
    agent: str
    choice: str
    reasoning: str
    confidence: float = 1.0
    continue_debate: bool = True
```

## Building API Agents

### OpenAI-Compatible Agent

```python
import httpx
from aragora.agents.api_agents.base import APIAgent
from aragora.core import Critique, Message

class OpenAICompatibleAgent(APIAgent):
    """Agent for any OpenAI-compatible API."""

    def __init__(
        self,
        name: str,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        model: str = "gpt-5.3",
        role: str = "proposer",
        timeout: int = 120,
    ):
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key,
            base_url=base_url,
        )
        self.agent_type = "openai-compatible"
        self.client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer \{api_key\}"}
        )

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        full_prompt = self._build_context_prompt(context) + prompt if context else prompt
        messages = [{"role": "user", "content": full_prompt}]

        response = await self.client.post(
            "/chat/completions",
            json={
                "model": self.model,
                "messages": messages,
            }
        )
        response.raise_for_status()
        data = response.json()

        return data["choices"][0]["message"]["content"]

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique_prompt = f"""Critically analyze this proposal:

Task: \{task\}
Proposal: \{proposal\}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, "proposal", proposal)
```

### Anthropic Agent

```python
import anthropic
from aragora.agents.api_agents.base import APIAgent
from aragora.core import Critique, Message

class AnthropicAgent(APIAgent):
    """Agent using Anthropic's Claude models."""

    def __init__(
        self,
        name: str = "anthropic-api",
        model: str = "claude-opus-4-5-20251101",
        api_key: str | None = None,
        role: str = "proposer",
        timeout: int = 120,
    ):
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=api_key,
            base_url="https://api.anthropic.com/v1",
        )
        self.agent_type = "anthropic"
        self.client = anthropic.AsyncAnthropic(api_key=api_key)

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        full_prompt = self._build_context_prompt(context) + prompt if context else prompt
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            system=self.system_prompt or "You are a helpful assistant participating in a debate.",
            messages=[{"role": "user", "content": full_prompt}]
        )
        return response.content[0].text

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique_prompt = f"""Critically analyze this proposal:

Task: \{task\}
Proposal: \{proposal\}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, "proposal", proposal)
```

## Building Local Agents

### Ollama Agent

```python
import httpx
from aragora.agents.api_agents.base import APIAgent
from aragora.core import Critique, Message

class OllamaAgent(APIAgent):
    """Agent for local Ollama models."""

    def __init__(
        self,
        name: str = "ollama",
        model: str = "llama3.2",
        base_url: str = "http://localhost:11434",
        role: str = "proposer",
        timeout: int = 120,
    ):
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key=None,
            base_url=base_url,
        )
        self.agent_type = "ollama"

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        full_prompt = self._build_context_prompt(context) + prompt if context else prompt
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": full_prompt,
                    "options": {
                        "temperature": self.temperature or 0.7,
                        "num_predict": 4096
                    },
                    "stream": False
                },
                timeout=120.0
            )
            response.raise_for_status()
            data = response.json()

        return data["response"]

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique_prompt = f"""Critically analyze this proposal:

Task: \{task\}
Proposal: \{proposal\}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, "proposal", proposal)
```

### vLLM Agent

```python
from aragora.agents.api_agents.base import APIAgent
from aragora.core import Critique, Message
from openai import AsyncOpenAI

class VLLMAgent(APIAgent):
    """Agent for vLLM server."""

    def __init__(
        self,
        name: str = "vllm",
        model: str = "meta-llama/Llama-3.1-8B-Instruct",
        base_url: str = "http://localhost:8000/v1",
        role: str = "proposer",
        timeout: int = 120,
    ):
        super().__init__(
            name=name,
            model=model,
            role=role,
            timeout=timeout,
            api_key="not-needed",
            base_url=base_url,
        )
        self.agent_type = "vllm"
        self.client = AsyncOpenAI(
            base_url=base_url,
            api_key="not-needed"  # vLLM doesn't require auth by default
        )

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        full_prompt = self._build_context_prompt(context) + prompt if context else prompt
        messages = [{"role": "user", "content": full_prompt}]

        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature or 0.7,
            max_tokens=4096
        )

        return response.choices[0].message.content

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique_prompt = f"""Critically analyze this proposal:

Task: \{task\}
Proposal: \{proposal\}

Format your response as:
ISSUES:
- issue 1
- issue 2

SUGGESTIONS:
- suggestion 1
- suggestion 2

SEVERITY: X.X
REASONING: explanation"""

        response = await self.generate(critique_prompt, context)
        return self._parse_critique(response, "proposal", proposal)
```

## Specialized Agents

### Expert Agent

An agent with domain expertise:

```python
class ExpertAgent(Agent):
    """Agent with specialized domain knowledge."""

    def __init__(
        self,
        name: str,
        domain: str,
        expertise_prompt: str,
        base_agent: Agent,
        role: str = "proposer",
    ):
        super().__init__(name=name, model=base_agent.model, role=role)
        self.domain = domain
        self.expertise_prompt = expertise_prompt
        self.base_agent = base_agent

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        enhanced_prompt = f"""You are an expert in {self.domain}.

{self.expertise_prompt}

Task prompt:
\{prompt\}"""

        return await self.base_agent.generate(enhanced_prompt, context)

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique = await self.base_agent.critique(proposal, task, context)
        critique.agent = self.name
        return critique

# Usage
security_expert = ExpertAgent(
    name="security-expert",
    domain="cybersecurity",
    expertise_prompt="""You have deep expertise in:
- Application security (OWASP Top 10)
- Network security and penetration testing
- Cryptography and secure protocols
- Security architecture and threat modeling

Always consider security implications in your responses.""",
    base_agent=AnthropicAgent()
)
```

### Devil's Advocate Agent

An agent that challenges consensus:

```python
class DevilsAdvocateAgent(Agent):
    """Agent that deliberately challenges the majority position."""

    def __init__(self, base_agent: Agent, name: str = "devils-advocate", role: str = "critic"):
        super().__init__(name=name, model=base_agent.model, role=role)
        self.base_agent = base_agent

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        contrarian_prompt = """You are a devil's advocate. Your role is to:
1. Identify the most commonly held position
2. Argue against it with compelling counterarguments
3. Find weaknesses and edge cases
4. Challenge assumptions

Be intellectually rigorous, not contrarian for its own sake.

Task prompt:
"""

        return await self.base_agent.generate(contrarian_prompt + prompt, context)

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique = await self.base_agent.critique(proposal, task, context)
        critique.agent = self.name
        return critique
```

### Ensemble Agent

Combines multiple agents:

```python
class EnsembleAgent(Agent):
    """Agent that synthesizes responses from multiple sub-agents."""

    def __init__(
        self,
        name: str,
        agents: list[Agent],
        synthesizer: Agent,
        role: str = "synthesizer",
    ):
        super().__init__(name=name, model=synthesizer.model, role=role)
        self.agents = agents
        self.synthesizer = synthesizer

    async def generate(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> str:
        # Gather responses from all sub-agents
        import asyncio
        responses = await asyncio.gather(*[
            agent.generate(prompt, context)
            for agent in self.agents
        ])

        # Synthesize into a single response
        synthesis_prompt = f"""Given these responses to the prompt "\{prompt\}":

{chr(10).join(f'Agent {agent.name}: \{response\}' for agent, response in zip(self.agents, responses))}

Synthesize these into a single, coherent response that captures the best insights from each."""

        return await self.synthesizer.generate(synthesis_prompt, context)

    async def critique(
        self,
        proposal: str,
        task: str,
        context: list[Message] | None = None,
    ) -> Critique:
        critique = await self.synthesizer.critique(proposal, task, context)
        critique.agent = self.name
        return critique
```

## Agent Configuration

### From YAML

```yaml
# agents.yaml
agents:
  claude-expert:
    type: anthropic-api
    model: claude-opus-4-5-20251101
    role: proposer
    system_prompt: "You are a helpful expert assistant."

  gpt-analyst:
    type: openai-api
    model: gpt-5.3
    role: critic
    system_prompt: "You are a careful analyst who examines evidence."

  local-llama:
    type: ollama
    model: llama3.2:70b
    extra:
      base_url: http://localhost:11434
```

Load configuration:

```python
import yaml
from aragora.agents.registry import AgentRegistry, register_all_agents

register_all_agents()

with open("agents.yaml", "r", encoding="utf-8") as handle:
    config = yaml.safe_load(handle)

agents = []
for name, spec in config["agents"].items():
    extra = spec.get("extra", {})
    agent = AgentRegistry.create(
        spec["type"],
        name=name,
        role=spec.get("role", "proposer"),
        model=spec.get("model"),
        api_key=spec.get("api_key"),
        **extra,
    )
    if spec.get("system_prompt"):
        agent.system_prompt = spec["system_prompt"]
    agents.append(agent)
```

### From Environment (Server Defaults)

```bash
export ARAGORA_DEFAULT_AGENTS="anthropic-api,openai-api,gemini"
export ARAGORA_STREAMING_AGENTS="anthropic-api,openai-api"
```

## Error Handling

### Retry Logic

```python
from aragora.core import Agent, Critique, Message
from aragora.resilience import CircuitBreaker, CircuitOpenError, with_retry

class ResilientAgent(Agent):
    """Agent with built-in resilience."""

    def __init__(self, base_agent: Agent):
        super().__init__(
            name=base_agent.name,
            model=base_agent.model,
            role=base_agent.role,
        )
        self.base_agent = base_agent
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60
        )

    @with_retry(max_attempts=3, backoff_factor=2)
    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        if not self.circuit_breaker.allow_request():
            raise CircuitOpenError(f"Circuit open for {self.name}")

        try:
            response = await self.base_agent.generate(prompt, context)
            self.circuit_breaker.record_success()
            return response
        except Exception as e:
            self.circuit_breaker.record_failure()
            raise

    async def critique(self, proposal: str, task: str, context: list[Message] | None = None) -> Critique:
        critique = await self.base_agent.critique(proposal, task, context)
        critique.agent = self.name
        return critique
```

### Fallback Agents

```python
from aragora.agents.fallback import AgentFallbackChain
from aragora.agents.api_agents import AnthropicAPIAgent, OpenAIAPIAgent, OpenRouterAgent
from aragora.resilience import CircuitBreaker

# Primary: Anthropic, fallback: OpenAI, last resort: OpenRouter
chain = AgentFallbackChain(
    providers=["anthropic", "openai", "openrouter"],
    circuit_breaker=CircuitBreaker(failure_threshold=3, cooldown_seconds=60),
)
chain.register_provider("anthropic", lambda: AnthropicAPIAgent())
chain.register_provider("openai", lambda: OpenAIAPIAgent())
chain.register_provider("openrouter", lambda: OpenRouterAgent(model="anthropic/claude-sonnet-4"))

# Generate with automatic fallback
response = await chain.generate("Summarize the trade-offs", context=None)
```

## Testing Agents

### Unit Tests

```python
import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_my_agent_generate():
    agent = MyAgent()

    response = await agent.generate("What is 2+2?")

    assert isinstance(response, str)
    assert response

@pytest.mark.asyncio
async def test_my_agent_critique():
    agent = MyAgent()

    critique = await agent.critique("The answer is 5", "Math problem")

    assert critique.issues
    assert critique.reasoning
```

### Integration Tests

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_agent_in_debate():
    from aragora import Arena, Environment, DebateProtocol
    from aragora.agents.base import create_agent

    env = Environment(task="Simple test debate")
    protocol = DebateProtocol(rounds=1)
    agents = [
        MyAgent(),
        create_agent("anthropic-api"),
    ]
    arena = Arena(env, agents, protocol)

    result = await arena.run()

    assert result.messages
    assert any(m.agent == "my-agent" for m in result.messages)
```

### Mock Agents for Testing

```python
class MockAgent(Agent):
    """Deterministic agent for testing."""

    def __init__(self, responses: list[str], name: str = "mock", model: str = "mock"):
        super().__init__(name=name, model=model)
        self.responses = responses
        self.call_count = 0

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return response

    async def critique(self, proposal: str, task: str, context: list[Message] | None = None) -> Critique:
        return Critique(
            agent=self.name,
            target_agent="proposal",
            target_content=proposal[:200],
            issues=["mock critique"],
            suggestions=[],
            severity=0.1,
            reasoning="mock critique",
        )
```

## Best Practices

### 1. Handle Rate Limits

```python
import asyncio
from aragora.utils.rate_limit import RateLimiter

class RateLimitedAgent(Agent):
    def __init__(self, base_agent: Agent, requests_per_minute: int = 60):
        super().__init__(name=base_agent.name, model=base_agent.model, role=base_agent.role)
        self.base_agent = base_agent
        self.limiter = RateLimiter(requests_per_minute)

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        await self.limiter.acquire()
        return await self.base_agent.generate(prompt, context)

    async def critique(self, proposal: str, task: str, context: list[Message] | None = None) -> Critique:
        critique = await self.base_agent.critique(proposal, task, context)
        critique.agent = self.name
        return critique
```

### 2. Log All Interactions

```python
import structlog

logger = structlog.get_logger()

class LoggingAgent(Agent):
    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        logger.info("agent.generate.start", agent=self.name, prompt_length=len(prompt))

        try:
            response = await self._generate_impl(prompt, context)
            logger.info("agent.generate.success",
                       agent=self.name,
                       response_length=len(response))
            return response
        except Exception as e:
            logger.error("agent.generate.error", agent=self.name, error=str(e))
            raise
```

### 3. Validate Responses

```python
from pydantic import BaseModel, validator

class ValidatedOutput(BaseModel):
    content: str
    confidence: float

    @validator("content")
    def content_not_empty(cls, v):
        if not v.strip():
            raise ValueError("Output content cannot be empty")
        return v

    @validator("confidence")
    def confidence_in_range(cls, v):
        if not 0 <= v <= 1:
            raise ValueError("Confidence must be between 0 and 1")
        return v
```

### 4. Support Streaming

```python
from typing import AsyncIterator

class StreamingAgent(Agent):
    async def generate_stream(
        self,
        prompt: str,
        **kwargs
    ) -> AsyncIterator[str]:
        """Stream response tokens."""
        async for chunk in self._stream_impl(prompt, **kwargs):
            yield chunk

    async def generate(self, prompt: str, context: list[Message] | None = None) -> str:
        """Non-streaming wrapper."""
        chunks = []
        async for chunk in self.generate_stream(prompt, **kwargs):
            chunks.append(chunk)
        return "".join(chunks)

    async def critique(self, proposal: str, task: str, context: list[Message] | None = None) -> Critique:
        critique_prompt = f"Task: \{task\}\nProposal: \{proposal\}\nProvide issues and suggestions."
        response = await self.generate(critique_prompt, context)
        return Critique(
            agent=self.name,
            target_agent="proposal",
            target_content=proposal[:200],
            issues=[response],
            suggestions=[],
            severity=0.3,
            reasoning="Streaming critique stub",
        )
```

## Agent Registry

### Register Custom Agents

```python
from aragora.agents.base import create_agent
from aragora.agents.registry import AgentRegistry

# Register
AgentRegistry.register("my-agent", default_model="custom", agent_type="Custom")(MyAgent)

# Retrieve
agent = create_agent("my-agent")
```

### List Available Agents

```python
from aragora.agents.base import list_available_agents

agents = list_available_agents()
# list(agents.keys()) -> ['anthropic-api', 'openai-api', 'gemini', 'grok', ...]
```

## Related Documentation

- [API Reference](../api/reference) - Full API documentation
- [Custom Agents](../guides/custom-agents) - More agent examples
- [Architecture](./architecture) - System architecture
- [Memory Architecture](./memory-strategy) - How agents learn
