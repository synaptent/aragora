"""
Vertical Registry - Factory pattern for vertical specialist creation.

Follows the same pattern as AgentRegistry for consistency.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.core_types import AgentRole
from aragora.verticals.config import VerticalConfig

if TYPE_CHECKING:
    from aragora.verticals.base import VerticalSpecialistAgent


@dataclass(frozen=True)
class VerticalSpec:
    """Specification for a registered vertical."""

    vertical_id: str
    specialist_class: type[VerticalSpecialistAgent]
    config: VerticalConfig
    description: str


class VerticalRegistry:
    """
    Factory registry for vertical specialist creation.

    Usage:
        # Registration (done in specialist modules)
        @VerticalRegistry.register("software", config=SoftwareConfig())
        class SoftwareSpecialist(VerticalSpecialistAgent):
            ...

        # Creation
        agent = VerticalRegistry.create_specialist(
            "software",
            name="reviewer-1",
            model="claude-opus-5",
        )

        # Listing
        available = VerticalRegistry.list_all()
    """

    _registry: dict[str, VerticalSpec] = {}

    @classmethod
    def register(
        cls,
        vertical_id: str,
        *,
        config: VerticalConfig,
        description: str = "",
    ) -> Callable[[type[VerticalSpecialistAgent]], type[VerticalSpecialistAgent]]:
        """
        Decorator to register a vertical specialist class.

        Args:
            vertical_id: Unique identifier for the vertical
            config: Vertical configuration
            description: Human-readable description

        Returns:
            Decorator function
        """

        def decorator(
            specialist_cls: type[VerticalSpecialistAgent],
        ) -> type[VerticalSpecialistAgent]:
            spec = VerticalSpec(
                vertical_id=vertical_id,
                specialist_class=specialist_cls,
                config=config,
                description=description or config.description,
            )
            cls._registry[vertical_id] = spec
            return specialist_cls

        return decorator

    @classmethod
    def create_specialist(
        cls,
        vertical_id: str,
        name: str,
        model: str | None = None,
        role: AgentRole = "analyst",
        api_key: str | None = None,
        **kwargs: Any,
    ) -> VerticalSpecialistAgent:
        """
        Create a vertical specialist instance.

        Args:
            vertical_id: Registered vertical type
            name: Agent instance name
            model: Model to use (overrides config default)
            role: Agent role
            api_key: API key for the model provider
            **kwargs: Additional arguments passed to specialist constructor

        Returns:
            Vertical specialist instance

        Raises:
            ValueError: If vertical_id is not registered
        """
        if vertical_id not in cls._registry:
            valid_types = ", ".join(sorted(cls._registry.keys()))
            raise ValueError(f"Unknown vertical: {vertical_id}. Valid verticals: {valid_types}")

        spec = cls._registry[vertical_id]
        config = spec.config

        # Use specified model or default from config
        resolved_model = model or config.model_config.primary_model

        return spec.specialist_class(
            name=name,
            model=resolved_model,
            role=role,
            api_key=api_key,
            config=config,
            **kwargs,
        )

    @classmethod
    def get(cls, vertical_id: str) -> VerticalSpec | None:
        """Get a vertical specification by ID."""
        return cls._registry.get(vertical_id)

    @classmethod
    def is_registered(cls, vertical_id: str) -> bool:
        """Check if a vertical is registered."""
        return vertical_id in cls._registry

    @classmethod
    def get_config(cls, vertical_id: str) -> VerticalConfig | None:
        """Get configuration for a vertical."""
        spec = cls._registry.get(vertical_id)
        return spec.config if spec else None

    @classmethod
    def list_all(cls) -> dict[str, dict[str, Any]]:
        """
        List all registered verticals with their metadata.

        Returns:
            Dict mapping vertical IDs to their specifications.
        """
        return {
            vid: {
                "display_name": spec.config.display_name,
                "description": spec.description,
                "expertise_areas": spec.config.expertise_areas,
                "tools": [t.name for t in spec.config.get_enabled_tools()],
                "compliance_frameworks": [c.framework for c in spec.config.compliance_frameworks],
                "default_model": spec.config.model_config.primary_model,
            }
            for vid, spec in cls._registry.items()
        }

    @classmethod
    def get_registered_ids(cls) -> list[str]:
        """Get list of all registered vertical IDs."""
        return list(cls._registry.keys())

    @classmethod
    def get_by_keyword(cls, keyword: str) -> list[str]:
        """
        Find verticals matching a keyword.

        Searches domain_keywords and expertise_areas.
        """
        keyword_lower = keyword.lower()
        matches = []

        for vid, spec in cls._registry.items():
            # Check domain keywords
            if any(keyword_lower in kw.lower() for kw in spec.config.domain_keywords):
                matches.append(vid)
                continue

            # Check expertise areas
            if any(keyword_lower in area.lower() for area in spec.config.expertise_areas):
                matches.append(vid)

        return matches

    @classmethod
    def get_for_task(cls, task_description: str) -> str | None:
        """
        Infer the best vertical for a task description.

        Returns the vertical ID with the most keyword matches.
        """
        task_lower = task_description.lower()
        best_match = None
        best_score = 0

        for vid, spec in cls._registry.items():
            score = 0

            # Score based on keyword presence
            for kw in spec.config.domain_keywords:
                if kw.lower() in task_lower:
                    score += 2

            for area in spec.config.expertise_areas:
                if area.lower() in task_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = vid

        return best_match

    @classmethod
    def clear(cls) -> None:
        """Clear all registrations (for testing)."""
        cls._registry.clear()
