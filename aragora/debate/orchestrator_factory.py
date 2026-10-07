"""Factory methods for Arena construction.

Extracted from orchestrator.py to reduce its size. Contains the three
classmethod factories: from_config, from_configs, and create.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.core_types import Agent
    from aragora.core import Environment
    from aragora.protocols.debate import DebateProtocol
    from aragora.debate.orchestrator import Arena


def _build_grouped_config(base_config: Any, grouped_cls: type[Any]) -> Any:
    """Project ArenaConfig fields into a grouped config dataclass."""
    grouped_kwargs: dict[str, Any] = {}
    for grouped_field in dataclass_fields(grouped_cls):
        if hasattr(base_config, grouped_field.name):
            grouped_kwargs[grouped_field.name] = getattr(base_config, grouped_field.name)
    return grouped_cls(**grouped_kwargs)


def from_config(
    cls: type[Arena],
    environment: Environment,
    agents: list[Agent],
    protocol: DebateProtocol | None = None,
    config: Any | None = None,
) -> Arena:
    """Create an Arena from an ArenaConfig for cleaner dependency injection.

    Args:
        cls: The Arena class (passed from the classmethod).
        environment: The debate environment (task, context).
        agents: List of participating agents.
        protocol: Optional debate protocol override.
        config: ArenaConfig instance.

    Returns:
        A fully initialized Arena instance.
    """
    from aragora.debate.arena_config import (
        ArenaConfig,
        EvolutionConfig,
        KnowledgeConfig,
        MLConfig,
        MemoryConfig,
    )
    from aragora.debate.feature_validator import validate_and_warn

    config = config or ArenaConfig()
    validate_and_warn(config)
    arena_kwargs = config.to_arena_kwargs()
    # Use grouped configs so ArenaConfig-based construction does not route through
    # deprecated individual kwargs for knowledge/ML/supermemory/rlm families.
    arena_kwargs.setdefault("memory_config", _build_grouped_config(config, MemoryConfig))
    arena_kwargs.setdefault("knowledge_config", _build_grouped_config(config, KnowledgeConfig))
    arena_kwargs.setdefault("ml_config", _build_grouped_config(config, MLConfig))
    arena_kwargs.setdefault("evolution_config", _build_grouped_config(config, EvolutionConfig))
    return cls(
        environment=environment,
        agents=agents,
        protocol=protocol,
        **arena_kwargs,
    )


def from_configs(
    cls: type[Arena],
    environment: Environment,
    agents: list[Agent],
    protocol: DebateProtocol | None = None,
    **kwargs: Any,
) -> Arena:
    """Create an Arena from grouped config objects.

    Accepts keyword arguments for debate_config, agent_config,
    memory_config, streaming_config, observability_config,
    knowledge_config, supermemory_config, evolution_config, ml_config.

    Args:
        cls: The Arena class (passed from the classmethod).
        environment: The debate environment (task, context).
        agents: List of participating agents.
        protocol: Optional debate protocol override.
        **kwargs: Config objects to pass through.

    Returns:
        A fully initialized Arena instance.
    """
    return cls(
        environment=environment,
        agents=agents,
        protocol=protocol,
        **kwargs,
    )


def create(
    cls: type[Arena],
    environment: Environment,
    agents: list[Agent],
    protocol: DebateProtocol | None = None,
    **kwargs: Any,
) -> Arena:
    """Create an Arena with a clean, consolidated interface.

    This is the recommended entry point for new code. It accepts at most
    10 parameters -- the three positional core args plus up to six optional
    config objects -- and delegates to ``__init__`` after unpacking.

    The ``config`` parameter (ArenaConfig) is a legacy catch-all.  When
    provided alongside the typed config objects, the typed objects win for
    any overlapping fields.

    Example::

        arena = Arena.create(
            environment=env,
            agents=agents,
            debate_config=DebateConfig(rounds=5),
            memory_config=MemoryConfig(enable_supermemory=True),
        )

    Args:
        cls: The Arena class (passed from the classmethod).
        environment: The debate environment (task, context).
        agents: List of participating agents.
        protocol: Optional debate protocol override.
        **kwargs: Accepts ``config`` (legacy ArenaConfig) plus typed config
            objects (debate_config, agent_config, memory_config,
            streaming_config, observability_config).

    Returns:
        A fully initialized Arena instance.
    """
    # Extract the legacy config param if present
    config = kwargs.pop("config", None)

    # Start from ArenaConfig kwargs (if provided) as the base layer
    base_kwargs: dict[str, Any] = {}
    if config is not None:
        from aragora.debate.arena_config import (
            EvolutionConfig,
            KnowledgeConfig,
            MLConfig,
            MemoryConfig,
        )

        base_kwargs = config.to_arena_kwargs()
        # Inject grouped config objects so deprecated individual kwargs are not
        # the only source of truth when using ArenaConfig as a base layer.
        base_kwargs.setdefault("memory_config", _build_grouped_config(config, MemoryConfig))
        base_kwargs.setdefault("knowledge_config", _build_grouped_config(config, KnowledgeConfig))
        base_kwargs.setdefault("ml_config", _build_grouped_config(config, MLConfig))
        base_kwargs.setdefault("evolution_config", _build_grouped_config(config, EvolutionConfig))

    # Typed config objects override the flat ArenaConfig values
    for key in (
        "debate_config",
        "agent_config",
        "memory_config",
        "streaming_config",
        "observability_config",
        "knowledge_config",
        "supermemory_config",
        "evolution_config",
        "ml_config",
    ):
        if key in kwargs:
            base_kwargs[key] = kwargs.pop(key)

    # Pass through any remaining kwargs
    base_kwargs.update(kwargs)

    return cls(
        environment=environment,
        agents=agents,
        protocol=protocol,
        **base_kwargs,
    )


__all__ = [
    "from_config",
    "from_configs",
    "create",
]
