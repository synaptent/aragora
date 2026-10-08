"""
Unified Agent Specification for Aragora.

This module provides a single AgentSpec class that separates four distinct concepts:

- provider: API/service type (e.g., 'anthropic-api', 'qwen', 'deepseek')
- model: Specific model identifier (e.g., 'claude-opus-5')
- persona: Behavioral archetype (e.g., 'philosopher', 'security_engineer')
- role: Debate function (proposer, critic, synthesizer, judge)

RECOMMENDED: Use explicit field creation for clarity and type safety:

    # Single agent
    spec = AgentSpec(provider="anthropic-api", persona="philosopher", role="proposer")

    # Team of agents
    team = AgentSpec.create_team([
        {"provider": "anthropic-api", "persona": "philosopher", "role": "proposer"},
        {"provider": "openai-api", "persona": "skeptic", "role": "critic"},
        {"provider": "gemini", "role": "synthesizer"},
    ])

DEPRECATED: String parsing is maintained for backward compatibility but discouraged:
    AgentSpec.parse("anthropic-api|claude-opus|philosopher|proposer")  # Deprecated
    AgentSpec.parse_list("anthropic-api,openai-api")  # Deprecated
"""

from __future__ import annotations

import warnings
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal
from collections.abc import Sequence

if TYPE_CHECKING:
    from typing import TypedDict

    from aragora.nomic.agent_roles import AgentRole as GastownRole

    class AgentSpecDict(TypedDict, total=False):
        provider: str
        model: str | None
        persona: str | None
        role: str | None  # None = assign automatically
        name: str | None
        hierarchy_role: str | None  # Gastown role: mayor, witness, polecat, crew


# Import ALLOWED_AGENT_TYPES for validation
from aragora.config.settings import ALLOWED_AGENT_TYPES

# Valid debate roles (from core.py)
AgentRole = Literal[
    "proposer", "critic", "synthesizer", "judge", "analyst", "implementer", "planner"
]
VALID_ROLES: frozenset[str] = frozenset(
    {"proposer", "critic", "synthesizer", "judge", "analyst", "implementer", "planner"}
)


def _find_similar(
    value: str, options: frozenset[str] | set[str], threshold: float = 0.6
) -> str | None:
    """Find the most similar option to a value using simple character matching.

    Args:
        value: The value to match
        options: Set of valid options
        threshold: Minimum similarity ratio (0.0 to 1.0) to return a suggestion

    Returns:
        Most similar option if above threshold, else None
    """
    if not value or not options:
        return None

    value_lower = value.lower()
    best_match = None
    best_score = 0.0

    for option in options:
        option_lower = option.lower()

        # Quick check: exact prefix match
        if option_lower.startswith(value_lower) or value_lower.startswith(option_lower):
            return option

        # Simple similarity: count matching characters
        shorter, longer = (
            (value_lower, option_lower)
            if len(value_lower) <= len(option_lower)
            else (option_lower, value_lower)
        )
        matches = sum(1 for c in shorter if c in longer)
        score = matches / len(longer) if longer else 0.0

        if score > best_score and score >= threshold:
            best_score = score
            best_match = option

    return best_match


@dataclass
class AgentSpec:
    """
    Unified specification for creating a debate agent.

    Separates four distinct concepts:
    - provider: Agent type from ALLOWED_AGENT_TYPES (e.g., 'anthropic-api', 'qwen')
    - model: Specific model identifier (optional, uses registry default)
    - persona: Behavioral persona for prompting (optional)
    - role: Debate role - one of 'proposer', 'critic', 'synthesizer', 'judge'

    RECOMMENDED - Explicit field creation:
        # Single agent with explicit fields
        spec = AgentSpec(provider="anthropic-api", persona="philosopher", role="proposer")

        # Team creation with dicts
        team = AgentSpec.create_team([
            {"provider": "anthropic-api", "persona": "philosopher", "role": "proposer"},
            {"provider": "openai-api", "role": "critic"},
        ])

    DEPRECATED - String parsing (for backward compatibility only):
        AgentSpec.parse("anthropic-api|claude-opus|philosopher|proposer")
        AgentSpec.parse_list("anthropic-api,openai-api")
    """

    provider: str
    model: str | None = None
    persona: str | None = None
    role: str | None = None  # None = assign automatically based on position
    name: str | None = None  # Optional display name
    hierarchy_role: str | None = None  # Gastown hierarchy: mayor, witness, polecat, crew

    # Valid Gastown hierarchy roles
    VALID_HIERARCHY_ROLES: frozenset[str] = frozenset({"mayor", "witness", "polecat", "crew"})

    def __post_init__(self) -> None:
        """Validate the spec after initialization."""
        # Normalize provider to lowercase
        self.provider = self.provider.lower()

        # Validate provider with helpful suggestions
        if self.provider not in ALLOWED_AGENT_TYPES:
            suggestion = _find_similar(self.provider, ALLOWED_AGENT_TYPES)
            msg = f"Invalid agent provider: '{self.provider}'. "
            if suggestion:
                msg += f"Did you mean '{suggestion}'? "
            msg += f"Allowed: {', '.join(sorted(ALLOWED_AGENT_TYPES))}"
            raise ValueError(msg)

        # Validate role (None is allowed to indicate "assign automatically")
        if self.role is not None and self.role not in VALID_ROLES:
            suggestion = _find_similar(self.role, VALID_ROLES)
            msg = f"Invalid agent role: '{self.role}'. "
            if suggestion:
                msg += f"Did you mean '{suggestion}'? "
            msg += f"Allowed: {', '.join(sorted(VALID_ROLES))}"
            raise ValueError(msg)

        # Validate hierarchy_role (Gastown role: mayor, witness, polecat, crew)
        if self.hierarchy_role is not None:
            self.hierarchy_role = self.hierarchy_role.lower()
            if self.hierarchy_role not in self.VALID_HIERARCHY_ROLES:
                suggestion = _find_similar(self.hierarchy_role, self.VALID_HIERARCHY_ROLES)
                msg = f"Invalid hierarchy role: '{self.hierarchy_role}'. "
                if suggestion:
                    msg += f"Did you mean '{suggestion}'? "
                msg += f"Allowed: {', '.join(sorted(self.VALID_HIERARCHY_ROLES))}"
                raise ValueError(msg)

        # Generate default name if not provided
        if self.name is None:
            parts = [self.provider]
            if self.persona:
                parts.append(self.persona)
            if self.role:
                parts.append(self.role)
            self.name = "_".join(parts)

    @property
    def agent_type(self) -> str:
        """Alias for provider for backward compatibility with legacy code."""
        return self.provider

    @property
    def gastown_role(self) -> GastownRole | None:
        """Get the Gastown AgentRole enum value if hierarchy_role is set.

        Returns:
            AgentRole enum (MAYOR, WITNESS, POLECAT, CREW) or None
        """
        if self.hierarchy_role is None:
            return None
        try:
            from aragora.nomic.agent_roles import AgentRole

            return AgentRole(self.hierarchy_role)
        except (ImportError, ValueError):
            return None

    def has_gastown_capability(self, capability: str) -> bool:
        """Check if this agent has a specific Gastown capability.

        Args:
            capability: Capability name (e.g., 'create_convoy', 'execute_task')

        Returns:
            True if the agent's hierarchy role grants this capability
        """
        gastown = self.gastown_role
        if gastown is None:
            return False
        try:
            from aragora.nomic.agent_roles import ROLE_CAPABILITIES, RoleCapability

            try:
                cap = RoleCapability(capability)
            except ValueError:
                return False
            return cap in ROLE_CAPABILITIES.get(gastown, set())
        except ImportError:
            return False

    def is_coordinator(self) -> bool:
        """Check if this agent has coordinator capabilities (Mayor role)."""
        return self.hierarchy_role == "mayor"

    def is_monitor(self) -> bool:
        """Check if this agent has monitoring capabilities (Witness role)."""
        return self.hierarchy_role == "witness"

    def is_worker(self) -> bool:
        """Check if this agent is a worker (Polecat or Crew role)."""
        return self.hierarchy_role in ("polecat", "crew")

    def is_ephemeral(self) -> bool:
        """Check if this agent is ephemeral (Polecat role)."""
        return self.hierarchy_role == "polecat"

    @classmethod
    def create_team(
        cls,
        specs: Sequence[AgentSpecDict | AgentSpec],
        default_role_rotation: bool = True,
    ) -> list[AgentSpec]:
        """
        Create a team of agents from explicit field specifications.

        This is the RECOMMENDED way to create multiple agents for a debate.

        Args:
            specs: List of AgentSpec instances or dicts with spec fields.
                   Required field: 'provider'
                   Optional fields: 'model', 'persona', 'role', 'name'
            default_role_rotation: If True, assigns roles in rotation
                                   (proposer, critic, synthesizer, judge)
                                   for specs without explicit role.

        Returns:
            List of AgentSpec instances

        Example:
            team = AgentSpec.create_team([
                {"provider": "anthropic-api", "persona": "philosopher"},
                {"provider": "openai-api", "persona": "skeptic"},
                {"provider": "gemini"},
            ])
            # Results in: proposer (anthropic), critic (openai), synthesizer (gemini)
        """
        role_rotation = ["proposer", "critic", "synthesizer", "judge"]
        result = []

        for i, spec in enumerate(specs):
            if isinstance(spec, AgentSpec):
                result.append(spec)
            else:
                # Dict-based creation
                provider = spec.get("provider")
                if not provider:
                    raise ValueError(f"Agent spec at index {i} missing required 'provider' field")

                role = spec.get("role")
                if role is None and default_role_rotation:
                    role = role_rotation[i % len(role_rotation)]
                elif role is None:
                    role = "proposer"

                result.append(
                    cls(
                        provider=provider,
                        model=spec.get("model"),
                        persona=spec.get("persona"),
                        role=role,
                        name=spec.get("name"),
                    )
                )

        return result

    @classmethod
    def parse(cls, spec_str: str, _warn: bool = True) -> AgentSpec:
        """
        Parse a spec string in either pipe format or legacy colon format.

        DEPRECATED: Prefer explicit field creation instead:
            AgentSpec(provider="anthropic-api", persona="philosopher", role="critic")

        Args:
            spec_str: Agent specification string
            _warn: Internal flag to suppress warning (for parse_list)

        Returns:
            Parsed AgentSpec instance

        Raises:
            ValueError: If the spec is invalid
        """
        if _warn:
            warnings.warn(
                "AgentSpec.parse() is deprecated. Use explicit field creation: "
                "AgentSpec(provider='...', persona='...', role='...')",
                DeprecationWarning,
                stacklevel=2,
            )
        spec_str = spec_str.strip()

        if not spec_str:
            raise ValueError("Empty agent spec string")

        if "|" in spec_str:
            # New pipe-delimited format: provider|model|persona|role
            return cls._parse_pipe_format(spec_str)
        else:
            # Legacy colon format: provider:persona or just provider
            return cls._parse_legacy_format(spec_str)

    @classmethod
    def _parse_pipe_format(cls, spec_str: str) -> AgentSpec:
        """Parse new pipe-delimited format: provider|model|persona|role.

        Empty or missing role returns None to allow automatic role assignment.
        """
        parts = spec_str.split("|")

        provider = parts[0] if parts else ""
        model = parts[1] if len(parts) > 1 and parts[1] else None
        persona = parts[2] if len(parts) > 2 and parts[2] else None
        # Empty or missing role = None (assign automatically)
        role = parts[3] if len(parts) > 3 and parts[3] else None

        return cls(provider=provider, model=model, persona=persona, role=role)

    @classmethod
    def _parse_legacy_format(cls, spec_str: str) -> AgentSpec:
        """
        Parse legacy colon format: provider:role or provider:persona or just provider.

        The second part is interpreted as:
        - ROLE if it matches a valid role (proposer, critic, synthesizer, judge)
        - PERSONA otherwise (for behavioral archetypes like philosopher, skeptic)

        This allows both:
        - agent_selection.py style: "anthropic-api:critic" -> role=critic
        - persona style: "anthropic-api:philosopher" -> persona=philosopher

        Note: When role is not explicitly specified, it returns None to allow
        callers to assign roles based on position (first=proposer, last=synth, etc).
        """
        if ":" in spec_str:
            # Split only on first colon to handle edge cases
            parts = spec_str.split(":", 1)
            provider = parts[0]
            second_part = parts[1] if len(parts) > 1 else None

            # Check if second part is a valid role
            if second_part and second_part.lower() in VALID_ROLES:
                # Treat as role (e.g., "anthropic-api:critic") - explicitly specified
                return cls(provider=provider, persona=None, role=second_part.lower())
            else:
                # Treat as persona (e.g., "anthropic-api:philosopher")
                # Role not explicitly set - return None to allow smart assignment
                return cls(provider=provider, persona=second_part, role=None)
        else:
            # Just provider name - role not explicitly set
            provider = spec_str
            return cls(provider=provider, persona=None, role=None)

    @classmethod
    def parse_list(cls, specs_str: str, _warn: bool = True) -> list[AgentSpec]:
        """
        Parse a comma-separated string of agent specs.

        DEPRECATED: Prefer AgentSpec.create_team() with explicit fields:
            AgentSpec.create_team([
                {"provider": "anthropic-api", "persona": "philosopher"},
                {"provider": "qwen", "role": "critic"},
            ])

        Args:
            specs_str: Comma-separated agent specs
            _warn: Internal flag to suppress warning

        Returns:
            List of AgentSpec instances
        """
        if _warn:
            warnings.warn(
                "AgentSpec.parse_list() is deprecated. Use AgentSpec.create_team() "
                "with explicit field dicts instead.",
                DeprecationWarning,
                stacklevel=2,
            )
        if not specs_str:
            return []

        specs = []
        for spec in specs_str.split(","):
            spec = spec.strip()
            if spec:
                specs.append(cls.parse(spec, _warn=False))

        return specs

    @classmethod
    def _from_dict(cls, spec: dict[str, Any], index: int | None = None) -> AgentSpec:
        provider = (
            spec.get("provider") or spec.get("agent_type") or spec.get("type") or spec.get("agent")
        )
        if not provider:
            location = f" at index {index}" if index is not None else ""
            raise ValueError(f"Agent spec{location} missing required 'provider' field")
        return cls(
            provider=str(provider),
            model=spec.get("model"),
            persona=spec.get("persona"),
            role=spec.get("role"),
            name=spec.get("name"),
            hierarchy_role=spec.get("hierarchy_role"),
        )

    @classmethod
    def coerce_list(cls, specs: Any, *, warn: bool = True) -> list[AgentSpec]:
        """Coerce flexible agent spec inputs into AgentSpec list.

        Accepts:
        - string (comma-separated or pipe format; JSON list/dict)
        - list of strings
        - list of dicts (explicit fields)
        - list of AgentSpec
        - single dict
        """
        if specs is None:
            return []

        if isinstance(specs, AgentSpec):
            return [specs]

        if isinstance(specs, dict):
            return [cls._from_dict(specs)]

        if isinstance(specs, list):
            result: list[AgentSpec] = []
            saw_string = False
            for i, item in enumerate(specs):
                if isinstance(item, AgentSpec):
                    result.append(item)
                elif isinstance(item, dict):
                    result.append(cls._from_dict(item, index=i))
                elif isinstance(item, str):
                    saw_string = True
                    result.append(cls.parse(item, _warn=False))
                else:
                    raise ValueError(
                        f"Unsupported agent spec type at index {i}: {type(item).__name__}"
                    )
            if warn and saw_string:
                warnings.warn(
                    "AgentSpec.parse_list() is deprecated. Use AgentSpec.create_team() "
                    "with explicit field dicts instead.",
                    DeprecationWarning,
                    stacklevel=2,
                )
            return result

        if isinstance(specs, str):
            spec_str = specs.strip()
            if not spec_str:
                return []
            if spec_str.startswith("[") or spec_str.startswith("{"):
                try:
                    payload = json.loads(spec_str)
                except json.JSONDecodeError:
                    payload = None
                if payload is not None:
                    return cls.coerce_list(payload, warn=False)
            return cls.parse_list(spec_str, _warn=warn)

        raise ValueError(f"Unsupported agent spec type: {type(specs).__name__}")

    def to_string(self) -> str:
        """
        Serialize to new pipe-delimited format.

        Returns:
            Pipe-delimited spec string
        """
        return f"{self.provider}|{self.model or ''}|{self.persona or ''}|{self.role}"

    def to_legacy_string(self) -> str:
        """
        Serialize to legacy colon format (for backward compatibility).

        Returns:
            Colon-delimited spec string (provider:persona or just provider)
        """
        if self.persona:
            return f"{self.provider}:{self.persona}"
        return self.provider

    def with_role(self, role: str) -> AgentSpec:
        """
        Create a new AgentSpec with a different role.

        Args:
            role: New role to assign

        Returns:
            New AgentSpec with the specified role
        """
        return AgentSpec(
            provider=self.provider,
            model=self.model,
            persona=self.persona,
            role=role,
            name=None,  # Regenerate name
        )

    def with_persona(self, persona: str) -> AgentSpec:
        """
        Create a new AgentSpec with a different persona.

        Args:
            persona: New persona to assign

        Returns:
            New AgentSpec with the specified persona
        """
        return AgentSpec(
            provider=self.provider,
            model=self.model,
            persona=persona,
            role=self.role,
            name=None,  # Regenerate name
        )

    def __repr__(self) -> str:
        """Readable representation."""
        parts = [f"provider={self.provider!r}"]
        if self.model:
            parts.append(f"model={self.model!r}")
        if self.persona:
            parts.append(f"persona={self.persona!r}")
        parts.append(f"role={self.role!r}")
        return f"AgentSpec({', '.join(parts)})"


def parse_agents(agents_str: str) -> list[AgentSpec]:
    """
    Convenience function to parse agent specs.

    This function is provided for backward compatibility with existing code
    that imports a parse_agents function.

    Args:
        agents_str: Comma-separated agent specs

    Returns:
        List of AgentSpec instances
    """
    return AgentSpec.coerce_list(agents_str, warn=True)


__all__ = [
    "AgentSpec",
    "AgentRole",
    "VALID_ROLES",
    "parse_agents",
]
