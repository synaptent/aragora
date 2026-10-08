"""Configuration for the Swarm Commander system."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import Enum
from typing import Any


class UserProfile(str, Enum):
    """User profile determines system prompt style and report detail level."""

    CEO = "ceo"  # Non-technical decision maker
    CTO = "cto"  # Technical leader
    DEVELOPER = "developer"  # Hands-on developer
    POWER_USER = "power_user"  # Founder / power user


class AutonomyLevel(str, Enum):
    """How much autonomy the self-improvement loop has."""

    FULL_AUTO = "full_auto"  # Execute without asking
    PROPOSE_APPROVE = "propose"  # Propose, wait for approval
    HUMAN_GUIDED = "guided"  # Human drives each step
    METRICS_DRIVEN = "metrics"  # Auto-execute if metrics improve


# Profile-specific system prompts for the interrogator
USER_PROFILE_PROMPTS: dict[UserProfile, str] = {
    UserProfile.CEO: (
        "You are a CTO having a conversation with your CEO. They're telling you "
        "what they want, and your job is to understand their vision well enough "
        "to make it happen.\n\n"
        "Rules:\n"
        "1. Ask ONE question at a time\n"
        "2. After each answer, briefly paraphrase what you heard to confirm "
        "understanding before asking the next question\n"
        "3. Explain any technical concepts in plain language. Example: "
        "'We'd need to change the login page -- that's the screen you see "
        "when you first open the app.'\n"
        "4. Be proactive: suggest what COULD be done, not just ask\n"
        "5. Focus on: WHAT (outcome), WHY (problem), SCOPE (which parts), "
        "ACCEPTANCE (how to know it worked), CONSTRAINTS (budget, don't-touch)\n"
        "6. When you have enough info (usually 3-5 questions), give a "
        "plain-language summary of everything you plan to do, then respond "
        "with exactly: SPEC_READY\n"
        "7. Never use jargon without immediately explaining it\n"
        "8. Never ask about implementation details -- your engineering team "
        "handles those\n\n"
        "The project is Aragora, a multi-agent decision platform."
    ),
    UserProfile.CTO: (
        "You are a senior architect discussing requirements with a CTO peer. "
        "They understand technology but need help scoping and decomposing the work.\n\n"
        "Rules:\n"
        "1. Ask ONE question at a time\n"
        "2. You can use technical terms but keep them accessible\n"
        "3. Focus on: architecture impact, risk areas, dependencies, test strategy\n"
        "4. Suggest technical approaches when relevant\n"
        "5. When you have enough info, summarize the technical plan then: SPEC_READY\n"
        "6. Include file paths and module names when discussing scope\n\n"
        "The project is Aragora, a multi-agent decision platform."
    ),
    UserProfile.DEVELOPER: (
        "You are a tech lead pair-programming with a developer. "
        "They know the codebase and want to get specific.\n\n"
        "Rules:\n"
        "1. Ask ONE question at a time\n"
        "2. Be precise: ask about specific files, functions, test coverage\n"
        "3. Focus on: implementation approach, edge cases, backwards compatibility\n"
        "4. Suggest code-level approaches and testing strategies\n"
        "5. When you have enough info, list the exact changes then: SPEC_READY\n"
        "6. Include file paths, class names, and function signatures\n\n"
        "The project is Aragora, a multi-agent decision platform."
    ),
    UserProfile.POWER_USER: (
        "You are a CTO talking with a technically-savvy founder. "
        "They understand technology at a high level but don't want to get into "
        "implementation details unless necessary.\n\n"
        "Rules:\n"
        "1. Ask ONE question at a time\n"
        "2. Explain technical concepts briefly but don't over-simplify\n"
        "3. Be proactive: suggest improvements and adjacent opportunities\n"
        "4. Focus on: business impact, user experience, scalability, cost\n"
        "5. When you have enough info, summarize the plan then: SPEC_READY\n"
        "6. Balance technical accuracy with accessibility\n\n"
        "The project is Aragora, a multi-agent decision platform."
    ),
}


def _coerce_user_profile(value: UserProfile | str) -> UserProfile:
    """Normalize user profile values provided as enum members or raw strings."""

    return value if isinstance(value, UserProfile) else UserProfile(value)


def _coerce_autonomy_level(value: AutonomyLevel | str) -> AutonomyLevel:
    """Normalize autonomy values provided as enum members or raw strings."""

    return value if isinstance(value, AutonomyLevel) else AutonomyLevel(value)


@dataclass
class InterrogatorConfig:
    """Configuration for the SwarmInterrogator."""

    max_turns: int = 8
    model: str = "claude-opus-5"
    system_prompt: str = ""
    fallback_to_fixed_questions: bool = True
    user_profile: UserProfile = UserProfile.CEO

    def __post_init__(self) -> None:
        self.user_profile = _coerce_user_profile(self.user_profile)
        if not self.system_prompt:
            self.system_prompt = USER_PROFILE_PROMPTS[self.user_profile]

    def merge(self, overrides: dict[str, Any]) -> InterrogatorConfig:
        """Return a new config with *overrides* applied on top of this one."""
        merged = {f.name: getattr(self, f.name) for f in fields(self)}
        merged.update(overrides)
        return InterrogatorConfig(**merged)

    def with_overrides(self, **kwargs: Any) -> InterrogatorConfig:
        """Keyword convenience wrapper around :meth:`merge`."""
        return self.merge(kwargs)


@dataclass
class SwarmCommanderConfig:
    """Configuration for the SwarmCommander."""

    interrogator: InterrogatorConfig = field(default_factory=InterrogatorConfig)
    budget_limit_usd: float | None = 50.0
    require_approval: bool = False
    use_worktree_isolation: bool = True
    enable_meta_planning: bool = True
    enable_gauntlet_validation: bool = True
    enable_mode_enforcement: bool = True
    generate_receipts: bool = True
    spectate_stream: bool = True
    max_parallel_tasks: int = 20
    max_cycles: int = 5
    max_subtasks: int = 15
    max_parallel_branches: int = 16
    iterative_mode: bool = True
    user_profile: UserProfile = UserProfile.CEO

    # Phase 3: Research pipeline
    enable_research_pipeline: bool = True

    # Phase 4: Obsidian sync
    obsidian_vault_path: str | None = None
    obsidian_write_receipts: bool = True

    # Phase 5: Truth-seeking
    enable_epistemic_scoring: bool = True
    enable_calibration: bool = True
    enable_hollow_consensus_detection: bool = True

    # Phase 6: Self-improvement
    autonomy_level: AutonomyLevel = AutonomyLevel.PROPOSE_APPROVE
    enable_cross_cycle_learning: bool = True

    def __post_init__(self) -> None:
        self.user_profile = _coerce_user_profile(self.user_profile)
        self.autonomy_level = _coerce_autonomy_level(self.autonomy_level)

        # Sync user_profile to interrogator if not explicitly set
        if self.interrogator.user_profile != self.user_profile:
            has_custom_prompt = bool(self.interrogator.system_prompt)
            self.interrogator.user_profile = self.user_profile
            if not has_custom_prompt:
                # Re-trigger prompt selection for the synchronized profile.
                self.interrogator.system_prompt = ""
                self.interrogator.__post_init__()

    def merge(self, overrides: dict[str, Any]) -> SwarmCommanderConfig:
        """Return a new config with *overrides* applied on top of this one.

        Nested ``interrogator`` overrides may be supplied as a dict and will be
        merged recursively into the existing :class:`InterrogatorConfig`.
        """
        merged: dict[str, Any] = {f.name: getattr(self, f.name) for f in fields(self)}
        interrogator_overrides = overrides.pop("interrogator", None)
        merged.update(overrides)
        if isinstance(interrogator_overrides, dict):
            merged["interrogator"] = self.interrogator.merge(interrogator_overrides)
        elif interrogator_overrides is not None:
            merged["interrogator"] = interrogator_overrides
        return SwarmCommanderConfig(**merged)

    def with_overrides(self, **kwargs: Any) -> SwarmCommanderConfig:
        """Keyword convenience wrapper around :meth:`merge`."""
        return self.merge(kwargs)


def merge_configs(
    base: SwarmCommanderConfig,
    *layers: dict[str, Any],
) -> SwarmCommanderConfig:
    """Merge one or more override layers onto *base*, left to right."""
    result = base
    for layer in layers:
        result = result.merge(dict(layer))
    return result
