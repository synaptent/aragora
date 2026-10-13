"""
Stream Chaining for Agent-to-Agent Communication.

Adapted from claude-flow (MIT License)
Pattern: Agent-to-agent streaming without file I/O intermediary
Original: https://github.com/ruvnet/claude-flow

Aragora adaptations:
- AsyncIO-based stream buffers
- Integration with agent streaming infrastructure
- Topology-aware chain routing
- Progress tracking via hooks

This module enables streaming output from one agent directly into
another agent's input, reducing latency and enabling real-time
progressive refinement.

Usage:
    chain = StreamChain()

    # Chain agent outputs
    chain.subscribe("critic", "proposer")  # critic receives proposer's output

    # Stream through chain
    async for chunk in chain.stream_through(
        source_agent, target_agent, prompt, context
    ):
        print(chunk, end="", flush=True)
"""

from __future__ import annotations

__all__ = [
    "StreamChain",
    "StreamBuffer",
    "StreamMessage",
    "ChainedDebate",
    "create_chain_from_topology",
]

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any
from collections.abc import AsyncIterator, Sequence

from aragora.config import MAX_CONCURRENT_STREAMING

if TYPE_CHECKING:
    from aragora.core import Agent, Message
    from aragora.debate.hooks import HookManager

logger = logging.getLogger(__name__)


class StreamState(str, Enum):
    """State of a stream."""

    IDLE = "idle"
    STREAMING = "streaming"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class StreamMessage:
    """A message in the stream chain."""

    source: str  # Agent name
    content: str
    chunk_index: int
    is_final: bool = False
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class StreamBuffer:
    """
    Async buffer for streaming agent output.

    Allows one agent to produce output while another consumes it,
    without waiting for complete generation.
    """

    max_size: int = 1000
    _buffer: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=1000))
    _complete: asyncio.Event = field(default_factory=asyncio.Event)
    _error: Exception | None = field(default=None)
    _chunks_written: int = field(default=0)
    _chunks_read: int = field(default=0)

    async def write(self, chunk: str, is_final: bool = False) -> None:
        """Write a chunk to the buffer."""
        self._chunks_written += 1
        await self._buffer.put((chunk, is_final))

        if is_final:
            self._complete.set()

    async def write_error(self, error: Exception) -> None:
        """Signal an error occurred during writing."""
        self._error = error
        self._complete.set()

    async def read(self) -> str | None:
        """Read the next chunk from the buffer."""
        if self._buffer.empty() and self._complete.is_set():
            return None

        try:
            chunk, is_final = await asyncio.wait_for(self._buffer.get(), timeout=30.0)
            self._chunks_read += 1
            return chunk
        except asyncio.TimeoutError:
            return None

    async def read_all(self) -> str:
        """Read all chunks and return accumulated content."""
        content = []
        while True:
            chunk = await self.read()
            if chunk is None:
                break
            content.append(chunk)
        return "".join(content)

    async def read_stream(self) -> AsyncIterator[str]:
        """Async iterator for reading chunks."""
        while True:
            if self._error is not None:
                raise self._error

            if self._buffer.empty() and self._complete.is_set():
                break

            try:
                chunk, is_final = await asyncio.wait_for(
                    self._buffer.get(),
                    timeout=1.0,
                )
                self._chunks_read += 1
                yield chunk

                if is_final:
                    break
            except asyncio.TimeoutError:
                # Check if we should exit
                if self._complete.is_set() and self._buffer.empty():
                    break
                continue

    def reset(self) -> None:
        """Reset buffer for reuse."""
        self._buffer = asyncio.Queue(maxsize=self.max_size)
        self._complete = asyncio.Event()
        self._error = None
        self._chunks_written = 0
        self._chunks_read = 0

    @property
    def is_complete(self) -> bool:
        """Check if writing is complete."""
        return self._complete.is_set()

    @property
    def stats(self) -> dict[str, int]:
        """Get buffer statistics."""
        return {
            "written": self._chunks_written,
            "read": self._chunks_read,
            "pending": self._buffer.qsize(),
        }


@dataclass
class StreamChain:
    """
    Chains agent outputs directly to other agent inputs.

    Implements a publish-subscribe pattern where agents can subscribe
    to receive streaming output from other agents.
    """

    # Agent name -> set of subscriber agent names
    _subscriptions: dict[str, set[str]] = field(default_factory=lambda: {})
    # Agent name -> StreamBuffer for their output
    _buffers: dict[str, StreamBuffer] = field(default_factory=dict)
    # Agent name -> StreamState
    _states: dict[str, StreamState] = field(default_factory=dict)
    # Optional hook manager for events
    _hook_manager: HookManager | None = field(default=None)

    def register_agent(self, agent_name: str) -> None:
        """Register an agent with the chain."""
        if agent_name not in self._subscriptions:
            self._subscriptions[agent_name] = set()
        if agent_name not in self._buffers:
            self._buffers[agent_name] = StreamBuffer()
        if agent_name not in self._states:
            self._states[agent_name] = StreamState.IDLE

    def subscribe(self, subscriber: str, source: str) -> None:
        """
        Subscribe an agent to receive output from another agent.

        Args:
            subscriber: Agent that will receive the output
            source: Agent whose output will be forwarded
        """
        self.register_agent(source)
        self.register_agent(subscriber)
        self._subscriptions[source].add(subscriber)
        logger.debug("StreamChain: %s subscribed to %s", subscriber, source)

    def unsubscribe(self, subscriber: str, source: str) -> None:
        """Unsubscribe an agent from a source."""
        if source in self._subscriptions:
            self._subscriptions[source].discard(subscriber)

    def get_subscribers(self, source: str) -> set[str]:
        """Get all subscribers for a source agent."""
        return self._subscriptions.get(source, set())

    def get_buffer(self, agent_name: str) -> StreamBuffer:
        """Get or create buffer for an agent."""
        if agent_name not in self._buffers:
            self.register_agent(agent_name)
        return self._buffers[agent_name]

    async def publish(self, source: str, chunk: str, is_final: bool = False) -> None:
        """
        Publish a chunk from a source agent.

        Args:
            source: Agent publishing the chunk
            chunk: Content chunk
            is_final: Whether this is the last chunk
        """
        buffer = self.get_buffer(source)
        await buffer.write(chunk, is_final)

        if is_final:
            self._states[source] = StreamState.COMPLETE
        else:
            self._states[source] = StreamState.STREAMING

    async def consume(self, agent_name: str) -> AsyncIterator[str]:
        """
        Consume streaming output from an agent.

        Args:
            agent_name: Agent to consume from

        Yields:
            Content chunks
        """
        buffer = self.get_buffer(agent_name)
        async for chunk in buffer.read_stream():
            yield chunk

    async def stream_through(
        self,
        source_agent: Agent,
        target_agent: Agent,
        prompt: str,
        context: list[Message] | None = None,
        chain_prompt: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Stream from source agent through to target agent.

        This is the primary interface for chained streaming:
        1. Source agent generates response streaming
        2. Target agent receives accumulated output and generates response
        3. Both streams are yielded progressively

        Args:
            source_agent: Agent to generate initial response
            target_agent: Agent to process source output
            prompt: Initial prompt for source agent
            context: Optional conversation context
            chain_prompt: Optional custom prompt for target (uses default if None)

        Yields:
            Content chunks from both agents (source first, then target)
        """
        self.register_agent(source_agent.name)
        self.register_agent(target_agent.name)
        self.subscribe(target_agent.name, source_agent.name)

        start_time = time.time()
        accumulated = []

        # Phase 1: Stream from source
        logger.debug("StreamChain: Starting source stream from %s", source_agent.name)

        if hasattr(source_agent, "generate_stream"):
            async for chunk in source_agent.generate_stream(prompt, context):
                accumulated.append(chunk)
                yield f"[{source_agent.name}] {chunk}"
        else:
            # Fallback to non-streaming
            response = await source_agent.generate(prompt, context)
            accumulated.append(response)
            yield f"[{source_agent.name}] {response}"

        source_output = "".join(accumulated)
        logger.debug(
            "StreamChain: Source complete (%s chars) in %.2fs",
            len(source_output),
            time.time() - start_time,
        )

        # Phase 2: Stream from target using source output
        target_prompt = chain_prompt or (
            f"Based on the following analysis:\n\n{source_output}\n\n"
            "Provide your assessment and any additional insights."
        )

        logger.debug("StreamChain: Starting target stream from %s", target_agent.name)
        target_start = time.time()

        if hasattr(target_agent, "generate_stream"):
            async for chunk in target_agent.generate_stream(target_prompt, context):
                yield f"[{target_agent.name}] {chunk}"
        else:
            response = await target_agent.generate(target_prompt, context)
            yield f"[{target_agent.name}] {response}"

        total_time = time.time() - start_time
        logger.debug(
            "StreamChain: Complete in %.2fs (source: %.2fs, target: %.2fs)",
            total_time,
            target_start - start_time,
            time.time() - target_start,
        )

    def reset_agent(self, agent_name: str) -> None:
        """Reset an agent's buffer and state."""
        if agent_name in self._buffers:
            self._buffers[agent_name].reset()
        self._states[agent_name] = StreamState.IDLE

    def reset_all(self) -> None:
        """Reset all buffers and states."""
        for name in self._buffers:
            self.reset_agent(name)

    @property
    def stats(self) -> dict[str, Any]:
        """Get chain statistics."""
        return {
            "agents": list(self._buffers.keys()),
            "subscriptions": {k: list(v) for k, v in self._subscriptions.items() if v},
            "states": {k: v.value for k, v in self._states.items()},
            "buffers": {k: v.stats for k, v in self._buffers.items()},
        }


@dataclass
class ChainedDebate:
    """
    Debate with stream chaining between agents.

    Implements ring, all-to-all, and star topologies with streaming.
    """

    agents: Sequence[Agent]
    chain: StreamChain = field(default_factory=StreamChain)
    topology: str = "ring"  # "ring", "all-to-all", "star"

    def __post_init__(self) -> None:
        """Setup chain based on topology."""
        self._setup_topology()

    def _setup_topology(self) -> None:
        """Configure subscriptions based on topology."""
        if not self.agents:
            return

        for agent in self.agents:
            self.chain.register_agent(agent.name)

        if self.topology == "ring":
            # Each agent subscribes to the previous agent
            n = len(self.agents)
            for i, agent in enumerate(self.agents):
                prev_agent = self.agents[(i - 1) % n]
                self.chain.subscribe(agent.name, prev_agent.name)

        elif self.topology == "all-to-all":
            # Each agent subscribes to all other agents
            for agent in self.agents:
                for other in self.agents:
                    if agent.name != other.name:
                        self.chain.subscribe(agent.name, other.name)

        elif self.topology == "star":
            # First agent is hub, all others connect to it
            if len(self.agents) > 1:
                hub = self.agents[0]
                for agent in self.agents[1:]:
                    # Spoke agents subscribe to hub
                    self.chain.subscribe(agent.name, hub.name)
                    # Hub subscribes to spoke agents
                    self.chain.subscribe(hub.name, agent.name)

        logger.info("ChainedDebate: %s topology with %s agents", self.topology, len(self.agents))

    async def run_round(
        self,
        prompt: str,
        context: list[Message] | None = None,
    ) -> dict[str, str]:
        """
        Run a debate round with streaming between agents.

        Args:
            prompt: Round prompt
            context: Conversation context

        Returns:
            Dict of agent_name -> response
        """
        responses: dict[str, str] = {}

        if self.topology == "ring":
            # Sequential streaming through the ring
            current_prompt = prompt
            for agent in self.agents:
                accumulated = []

                if hasattr(agent, "generate_stream"):
                    async for chunk in agent.generate_stream(current_prompt, context):
                        accumulated.append(chunk)
                        await self.chain.publish(agent.name, chunk)
                    await self.chain.publish(agent.name, "", is_final=True)
                else:
                    response = await agent.generate(current_prompt, context)
                    accumulated.append(response)
                    await self.chain.publish(agent.name, response, is_final=True)

                response = "".join(accumulated)
                responses[agent.name] = response

                # Next agent receives this agent's output
                current_prompt = (
                    f"Previous agent ({agent.name}) said:\n{response}\n\n"
                    f"Original task: {prompt}\n\n"
                    "Provide your perspective:"
                )

        else:
            # Parallel execution for other topologies with bounded concurrency
            streaming_semaphore = asyncio.Semaphore(MAX_CONCURRENT_STREAMING)

            async def generate(agent: Agent) -> tuple[str, str]:
                async with streaming_semaphore:
                    if hasattr(agent, "generate_stream"):
                        chunks = []
                        async for chunk in agent.generate_stream(prompt, context):
                            chunks.append(chunk)
                            await self.chain.publish(agent.name, chunk)
                        await self.chain.publish(agent.name, "", is_final=True)
                        return agent.name, "".join(chunks)
                    else:
                        response = await agent.generate(prompt, context)
                        await self.chain.publish(agent.name, response, is_final=True)
                        return agent.name, response

            results = await asyncio.gather(*[generate(a) for a in self.agents])
            responses = dict(results)

        self.chain.reset_all()
        return responses


def create_chain_from_topology(
    topology: str,
    agents: Sequence[Agent],
) -> ChainedDebate:
    """
    Create a ChainedDebate with the specified topology.

    Args:
        topology: Topology type ("ring", "all-to-all", "star")
        agents: Agents to include

    Returns:
        Configured ChainedDebate instance
    """
    return ChainedDebate(agents=agents, topology=topology)
