"""
Debate Service - High-level API for running debates.

Provides a simplified interface for common debate operations while
maintaining full flexibility through optional configuration.

Usage:
    from aragora.debate.service import DebateService, get_debate_service

    # Quick debate with defaults
    service = get_debate_service()
    result = await service.run("What is the best testing strategy?")

    # With custom agents and options
    result = await service.run(
        task="Design a rate limiter",
        agents=["claude", "gemini"],
        rounds=9,
        consensus="supermajority",
    )

    # Full configuration
    result = await service.run(
        task="Security audit",
        agents=custom_agents,
        protocol=custom_protocol,
        memory=memory_system,
        timeout=300,
    )
"""

from __future__ import annotations

import asyncio
import os
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast
from collections.abc import Callable, Sequence

from aragora.agents.base import AgentType
from aragora.config.settings import get_settings
from aragora.core import Agent, DebateResult, Environment
from aragora.debate.protocol_resolver import resolve_default_protocol
from aragora.protocols.debate import DebateProtocol

# Type alias for consensus modes (must match DebateProtocol.consensus)
ConsensusMode = Literal[
    "majority",
    "unanimous",
    "judge",
    "none",
    "weighted",
    "supermajority",
    "any",
    "byzantine",
]

if TYPE_CHECKING:
    from aragora.memory.continuum import ContinuumMemory

logger = logging.getLogger(__name__)


@dataclass
class DebateOptions:
    """Configuration options for a debate.

    All fields are optional with sensible defaults.
    """

    # Protocol options
    rounds: int | None = None
    consensus: (
        Literal[
            "majority",
            "unanimous",
            "judge",
            "none",
            "weighted",
            "supermajority",
            "any",
            "byzantine",
        ]
        | None
    ) = None
    topology: Literal["all-to-all", "sparse", "round-robin", "ring", "star", "random-graph"] = (
        "all-to-all"
    )
    enable_graph: bool = False

    # Execution options
    timeout: float = 300.0  # 5 minutes default
    enable_streaming: bool = False
    enable_checkpointing: bool = True  # Enable by default for debate resume support

    # Memory options
    enable_memory: bool = True
    enable_knowledge_retrieval: bool = True

    # ML options (stable - enabled by default)
    enable_ml_delegation: bool = True
    enable_quality_gates: bool = True
    enable_consensus_estimation: bool = True

    # Telemetry
    org_id: str = ""
    user_id: str = ""
    correlation_id: str = ""

    # Event hooks
    on_round_start: Callable[[int], None] | None = None
    on_agent_message: Callable[[str, str], None] | None = None
    on_consensus: Callable[[str, float], None] | None = None

    def __post_init__(self) -> None:
        settings = get_settings()
        if self.rounds is None:
            self.rounds = settings.debate.default_rounds
        if self.consensus is None:
            # Cast from settings string to literal type (validated at config load)
            consensus_value = settings.debate.default_consensus
            if consensus_value in (
                "majority",
                "unanimous",
                "judge",
                "none",
                "weighted",
                "supermajority",
                "any",
                "byzantine",
            ):
                self.consensus = cast(
                    Literal[
                        "majority",
                        "unanimous",
                        "judge",
                        "none",
                        "weighted",
                        "supermajority",
                        "any",
                        "byzantine",
                    ],
                    consensus_value,
                )

        profile = os.environ.get("ARAGORA_DEBATE_PROFILE", "").lower()
        if profile in {"full", "nomic", "structured"}:
            try:
                from aragora.nomic.debate_profile import NomicDebateProfile

                nomic_profile = NomicDebateProfile.from_env()
                self.rounds = nomic_profile.rounds
                self.consensus = cast(
                    Literal[
                        "majority",
                        "unanimous",
                        "judge",
                        "none",
                        "weighted",
                        "supermajority",
                        "any",
                        "byzantine",
                    ],
                    nomic_profile.consensus_mode,
                )
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.warning("Failed to apply debate profile '%s': %s", profile, exc)

    def to_protocol(self) -> DebateProtocol:
        """Convert options to a DebateProtocol."""
        # Use "judge" as default if consensus not set (matches DebateProtocol default)
        consensus_value: ConsensusMode = self.consensus if self.consensus is not None else "judge"
        protocol = resolve_default_protocol()
        protocol.rounds = self.rounds or protocol.rounds
        protocol.consensus = consensus_value
        protocol.topology = self.topology
        return protocol


class DebateService:
    """High-level service for running debates.

    Provides a simplified API for common debate operations while
    maintaining full flexibility through optional configuration.

    The service handles:
    - Agent resolution (names to Agent objects)
    - Protocol configuration
    - Arena construction
    - Timeout management
    - Error handling

    Example:
        service = DebateService()

        # Simple debate
        result = await service.run("What is the best approach?")

        # With options
        result = await service.run(
            task="Design a cache",
            agents=["claude", "gemini"],
            options=DebateOptions(rounds=5, consensus="supermajority"),
        )
    """

    def __init__(
        self,
        default_agents: list[Agent] | list[str] | None = None,
        default_options: DebateOptions | None = None,
        memory: ContinuumMemory | None = None,
        agent_resolver: Callable[[str], Agent] | None = None,
    ):
        """Initialize the debate service.

        Args:
            default_agents: Default agents to use if none specified
            default_options: Default options for all debates
            memory: Shared memory system for debates
            agent_resolver: Function to resolve agent names to Agent objects
        """
        self._default_agents = default_agents
        self._default_options = default_options or DebateOptions()
        self._memory = memory
        self._agent_resolver = agent_resolver

    async def run(
        self,
        task: str,
        agents: list[Agent] | list[str] | None = None,
        protocol: DebateProtocol | None = None,
        options: DebateOptions | None = None,
        memory: ContinuumMemory | None = None,
        **kwargs: Any,
    ) -> DebateResult:
        """Run a debate on the given task.

        Args:
            task: The topic or question to debate
            agents: List of Agent objects or agent names to resolve
            protocol: Custom protocol (overrides options)
            options: Debate options (merged with defaults)
            memory: Memory system (overrides service default)
            **kwargs: Additional Arena constructor arguments

        Returns:
            DebateResult with consensus, synthesis, and metadata

        Raises:
            ValueError: If no agents available
            asyncio.TimeoutError: If debate exceeds timeout
        """
        # Merge options with defaults
        opts = self._merge_options(options)
        provider_hints = kwargs.pop("provider_hints", None)
        requested_agent_count = kwargs.pop("agent_count", None)
        min_providers = kwargs.pop("min_providers", None)
        team_selector = kwargs.pop("team_selector", None)

        # Resolve agents
        resolved_agents = self._resolve_agents(agents)
        if not resolved_agents:
            raise ValueError("No agents available. Provide agents or configure default_agents.")
        resolved_agents, routing_metadata = self._route_runtime_agents(
            resolved_agents,
            provider_hints=provider_hints,
            agent_count=requested_agent_count,
            min_providers=min_providers,
            team_selector=team_selector,
        )

        # Create environment
        env = Environment(task=task)

        # Create or use provided protocol
        debate_protocol = protocol or opts.to_protocol()

        # Get memory system
        debate_memory = memory or self._memory

        # Build Arena kwargs
        arena_kwargs: dict[str, Any] = {
            "enable_checkpointing": opts.enable_checkpointing,
            "enable_knowledge_retrieval": opts.enable_knowledge_retrieval,
            "enable_ml_delegation": opts.enable_ml_delegation,
            "enable_quality_gates": opts.enable_quality_gates,
            "enable_consensus_estimation": opts.enable_consensus_estimation,
        }

        # Add telemetry if provided
        if opts.org_id:
            arena_kwargs["org_id"] = opts.org_id
        if opts.user_id:
            arena_kwargs["user_id"] = opts.user_id

        # Add event hooks if provided
        event_hooks = self._build_event_hooks(opts)
        if event_hooks:
            arena_kwargs["event_hooks"] = event_hooks

        # Merge with any additional kwargs
        arena_kwargs.update(kwargs)

        # Import Arena here to avoid circular imports
        from aragora.debate.orchestrator import Arena

        # Create Arena
        arena = Arena(
            env,
            resolved_agents,
            debate_protocol,
            memory=debate_memory,
            **arena_kwargs,
        )

        # Run with timeout
        try:
            result = await asyncio.wait_for(arena.run(), timeout=opts.timeout)
            self._annotate_provider_routing_metadata(result, routing_metadata)
            return result
        except asyncio.TimeoutError:
            logger.warning("Debate timed out after %ss: %s...", opts.timeout, task[:50])
            raise

    async def run_quick(
        self,
        task: str,
        rounds: int = 2,
        agents: list[Agent] | list[str] | None = None,
    ) -> DebateResult:
        """Run a quick debate with minimal configuration.

        Convenience method for simple debates.

        Args:
            task: The topic to debate
            rounds: Number of rounds (default 2)
            agents: Optional agents (uses defaults if not provided)

        Returns:
            DebateResult
        """
        return await self.run(
            task=task,
            agents=agents,
            options=DebateOptions(rounds=rounds),
        )

    async def run_deep(
        self,
        task: str,
        agents: list[Agent] | list[str] | None = None,
        rounds: int | None = None,
    ) -> DebateResult:
        """Run a thorough debate with more rounds and stricter consensus.

        Convenience method for important decisions.

        Args:
            task: The topic to debate
            agents: Optional agents (uses defaults if not provided)
            rounds: Number of rounds (defaults to global debate settings)

        Returns:
            DebateResult
        """
        if rounds is None:
            rounds = get_settings().debate.default_rounds

        return await self.run(
            task=task,
            agents=agents,
            options=DebateOptions(
                rounds=rounds,
                consensus="supermajority",
                enable_quality_gates=True,
            ),
        )

    def _merge_options(self, options: DebateOptions | None) -> DebateOptions:
        """Merge provided options with defaults."""
        if options is None:
            return self._default_options

        # Create new options with defaults, then override with provided values
        merged = DebateOptions(
            rounds=options.rounds or self._default_options.rounds,
            consensus=options.consensus or self._default_options.consensus,
            topology=options.topology or self._default_options.topology,
            enable_graph=options.enable_graph,
            timeout=options.timeout or self._default_options.timeout,
            enable_streaming=options.enable_streaming,
            enable_checkpointing=options.enable_checkpointing,
            enable_memory=options.enable_memory,
            enable_knowledge_retrieval=options.enable_knowledge_retrieval,
            enable_ml_delegation=options.enable_ml_delegation,
            enable_quality_gates=options.enable_quality_gates,
            enable_consensus_estimation=options.enable_consensus_estimation,
            org_id=options.org_id or self._default_options.org_id,
            user_id=options.user_id or self._default_options.user_id,
            correlation_id=options.correlation_id or self._default_options.correlation_id,
            on_round_start=options.on_round_start or self._default_options.on_round_start,
            on_agent_message=options.on_agent_message or self._default_options.on_agent_message,
            on_consensus=options.on_consensus or self._default_options.on_consensus,
        )
        return merged

    def _resolve_agents(self, agents: list[Agent] | list[str] | None) -> list[Agent]:
        """Resolve agent specifications to Agent objects."""
        if agents is None:
            # Recursively resolve default agents (which may be strings)
            if self._default_agents:
                return self._resolve_agents(self._default_agents)
            return []

        resolved: list[Agent] = []
        for agent in agents:
            if isinstance(agent, Agent):
                resolved.append(agent)
            elif isinstance(agent, str) and self._agent_resolver:
                try:
                    resolved.append(self._agent_resolver(agent))
                except (KeyError, ValueError) as e:
                    logger.warning("Failed to resolve agent '%s': %s", agent, e)
                except (RuntimeError, TypeError, AttributeError) as e:
                    logger.exception("Unexpected error resolving agent '%s': %s", agent, e)
            elif isinstance(agent, str):
                # Try to create a basic agent from the name
                try:
                    from aragora.agents import create_agent

                    resolved.append(create_agent(cast(AgentType, agent)))
                except ImportError:
                    logger.warning("Cannot resolve agent '%s' - no resolver configured", agent)

        return resolved

    def _route_runtime_agents(
        self,
        agents: list[Agent],
        *,
        provider_hints: Any = None,
        agent_count: int | None = None,
        min_providers: int | None = None,
        team_selector: Any | None = None,
    ) -> tuple[list[Agent], dict[str, Any] | None]:
        """Select the runtime roster from routed providers before Arena starts."""
        if not agents:
            return agents, None

        if isinstance(provider_hints, dict):
            return self._route_agents_from_scores(
                agents,
                provider_hints=provider_hints,
                agent_count=agent_count,
                team_selector=team_selector,
            )

        if isinstance(provider_hints, Sequence) and not isinstance(provider_hints, (str, bytes)):
            return self._route_agents_from_provider_list(
                agents,
                provider_hints=[str(item) for item in provider_hints if str(item)],
                agent_count=agent_count,
                min_providers=min_providers,
            )

        return agents, None

    def _route_agents_from_scores(
        self,
        agents: list[Agent],
        *,
        provider_hints: dict[str, float],
        agent_count: int | None,
        team_selector: Any | None,
    ) -> tuple[list[Agent], dict[str, Any] | None]:
        """Rank agents with TeamSelector when score hints are provided."""
        limit = self._normalize_agent_count(agent_count, len(agents))
        ranked_agents = list(agents)
        routing_applied = False

        selector = team_selector
        if selector is None:
            try:
                from aragora.debate.team_selector import TeamSelector

                selector = TeamSelector()
            except (ImportError, RuntimeError, ValueError, TypeError, AttributeError):
                selector = None

        if selector is not None:
            try:
                ranked_agents = list(selector.select(list(agents), provider_hints=provider_hints))
                routing_applied = True
            except (RuntimeError, ValueError, TypeError, AttributeError) as exc:
                logger.debug("Provider score routing failed, preserving original roster: %s", exc)

        selected_agents = ranked_agents[:limit]
        metadata = {
            "provider_hints": list(provider_hints.keys()),
            "provider_names": [self._provider_name_for_agent(agent) for agent in selected_agents],
            "provider_hint_scores": dict(provider_hints),
            "routed_agent_names": [agent.name for agent in selected_agents],
            "routing_applied": routing_applied,
            "routing_strategy": "provider_hint_scores",
        }
        return selected_agents, metadata

    def _route_agents_from_provider_list(
        self,
        agents: list[Agent],
        *,
        provider_hints: list[str],
        agent_count: int | None,
        min_providers: int | None,
    ) -> tuple[list[Agent], dict[str, Any] | None]:
        """Match routed provider/model choices onto a concrete debate roster."""
        limit = self._normalize_agent_count(agent_count, len(provider_hints) or len(agents))
        remaining_agents = list(agents)
        selected_agents: list[Agent] = []
        provider_matches: dict[str, str] = {}

        for provider_hint in provider_hints:
            if len(selected_agents) >= limit:
                break
            match_index = next(
                (
                    index
                    for index, agent in enumerate(remaining_agents)
                    if self._agent_matches_provider_hint(agent, provider_hint)
                ),
                None,
            )
            if match_index is None:
                continue
            matched_agent = remaining_agents.pop(match_index)
            selected_agents.append(matched_agent)
            provider_matches[matched_agent.name] = provider_hint

        if len(selected_agents) < limit:
            remaining_agents = self._prioritize_diverse_fill(
                remaining_agents,
                selected_agents,
                min_providers=min_providers,
            )
            selected_agents.extend(remaining_agents[: limit - len(selected_agents)])

        metadata = {
            "provider_hints": list(provider_hints),
            "provider_names": [self._provider_name_for_agent(agent) for agent in selected_agents],
            "provider_matches": provider_matches,
            "routed_agent_names": [agent.name for agent in selected_agents],
            "routing_applied": bool(provider_matches),
            "routing_strategy": "provider_router_selection",
        }
        return selected_agents, metadata

    @staticmethod
    def _normalize_agent_count(agent_count: int | None, fallback: int) -> int:
        if agent_count is None:
            return max(fallback, 1)
        return max(agent_count, 1)

    @staticmethod
    def _provider_name_for_agent(agent: Agent) -> str:
        model = str(getattr(agent, "model", "") or "").strip()
        if model:
            return model
        return str(getattr(agent, "name", "unknown-agent"))

    @classmethod
    def _provider_family_for_agent(cls, agent: Agent) -> str:
        from aragora.debate.provider_diversity import detect_provider

        provider_name = cls._provider_name_for_agent(agent)
        agent_name = str(getattr(agent, "name", "") or "")
        detected = detect_provider(f"{provider_name} {agent_name}")
        if detected != "unknown":
            return detected
        return provider_name

    @classmethod
    def _agent_matches_provider_hint(cls, agent: Agent, provider_hint: str) -> bool:
        hint = provider_hint.strip().lower()
        if not hint:
            return False

        agent_name = str(getattr(agent, "name", "") or "").lower()
        provider_name = cls._provider_name_for_agent(agent).lower()
        provider_family = cls._provider_family_for_agent(agent).lower()

        if hint in {agent_name, provider_name, provider_family}:
            return True
        if hint in agent_name or agent_name in hint:
            return True
        if hint in provider_name or provider_name in hint:
            return True

        from aragora.debate.provider_diversity import detect_provider

        return detect_provider(hint) == provider_family

    @classmethod
    def _prioritize_diverse_fill(
        cls,
        remaining_agents: list[Agent],
        selected_agents: list[Agent],
        *,
        min_providers: int | None,
    ) -> list[Agent]:
        if not remaining_agents or min_providers is None or min_providers <= 1:
            return remaining_agents

        selected_providers = {cls._provider_family_for_agent(agent) for agent in selected_agents}
        if len(selected_providers) >= min_providers:
            return remaining_agents

        diverse_agents: list[Agent] = []
        fallback_agents: list[Agent] = []
        introduced_providers = set(selected_providers)

        for agent in remaining_agents:
            provider = cls._provider_family_for_agent(agent)
            if provider not in introduced_providers:
                diverse_agents.append(agent)
                introduced_providers.add(provider)
            else:
                fallback_agents.append(agent)

        return diverse_agents + fallback_agents

    @staticmethod
    def _annotate_provider_routing_metadata(
        result: DebateResult,
        metadata: dict[str, Any] | None,
    ) -> None:
        if metadata is None:
            return

        existing = getattr(result, "metadata", None)
        if not isinstance(existing, dict):
            existing = {}
            setattr(result, "metadata", existing)

        provider_hints = metadata.get("provider_hints")
        if provider_hints:
            existing.setdefault("provider_hints", list(provider_hints))

        provider_names = metadata.get("provider_names")
        if provider_names:
            existing.setdefault("provider_names", list(provider_names))

        routing_summary = {
            "routing_applied": bool(metadata.get("routing_applied")),
            "routing_strategy": metadata.get("routing_strategy", "provider_router_selection"),
            "routed_agent_names": list(metadata.get("routed_agent_names", [])),
        }
        if "provider_matches" in metadata:
            routing_summary["provider_matches"] = dict(metadata["provider_matches"])
        if "provider_hint_scores" in metadata:
            routing_summary["provider_hint_scores"] = dict(metadata["provider_hint_scores"])
        existing.setdefault("provider_routing", routing_summary)

    def _build_event_hooks(self, opts: DebateOptions) -> dict[str, Any] | None:
        """Build event hooks dictionary from options."""
        hooks: dict[str, Any] = {}

        if opts.on_round_start:
            hooks["round_start"] = opts.on_round_start
        if opts.on_agent_message:
            hooks["agent_message"] = opts.on_agent_message
        if opts.on_consensus:
            hooks["consensus"] = opts.on_consensus

        return hooks if hooks else None


# Global service instance
_debate_service: DebateService | None = None


def get_debate_service(
    default_agents: list[Agent] | list[str] | None = None,
    **kwargs: Any,
) -> DebateService:
    """Get the global debate service instance.

    Creates a new instance on first call or when default_agents is provided.

    Args:
        default_agents: Default agents for the service
        **kwargs: Additional DebateService constructor arguments

    Returns:
        DebateService instance
    """
    global _debate_service

    if _debate_service is None or default_agents is not None:
        resolved_defaults = default_agents
        if resolved_defaults is None:
            settings = get_settings()
            resolved_defaults = settings.agent.default_agent_list
        _debate_service = DebateService(default_agents=resolved_defaults, **kwargs)

    return _debate_service


def reset_debate_service() -> None:
    """Reset the global debate service instance.

    Useful for testing or reconfiguration.
    """
    global _debate_service
    _debate_service = None


__all__ = [
    "DebateService",
    "DebateOptions",
    "get_debate_service",
    "reset_debate_service",
]
