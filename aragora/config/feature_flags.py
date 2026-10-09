"""
Centralized Feature Flag Registry.

Provides a single source of truth for all feature flags across the codebase,
with validation, usage tracking, and documentation. Addresses the fragmentation
of flags across ArenaConfig, TenantConfig, settings, and environment variables.

Features:
- Flag registration with type, default, and documentation
- Validation of flag access (warns on unknown flags)
- Usage tracking for audit and cleanup
- Environment variable override support
- Hierarchical flag resolution (env > tenant > default)

Usage:
    from aragora.config.feature_flags import (
        FeatureFlagRegistry,
        get_flag_registry,
        is_enabled,
        get_flag,
    )

    # Check if a flag is enabled
    if is_enabled("enable_knowledge_retrieval"):
        await retrieve_knowledge()

    # Get flag value with type safety
    max_retries = get_flag("max_agent_retries", default=3)

    # Register a new flag
    registry = get_flag_registry()
    registry.register(
        name="enable_new_feature",
        flag_type=bool,
        default=False,
        description="Enable the new experimental feature",
        category="experimental",
    )
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar, overload

logger = logging.getLogger(__name__)

T = TypeVar("T")


class FlagCategory(str, Enum):
    """Categories for organizing feature flags."""

    CORE = "core"  # Core functionality
    KNOWLEDGE = "knowledge"  # Knowledge Mound integration
    PERFORMANCE = "performance"  # Performance and optimization
    MEMORY = "memory"  # Memory subsystems
    BILLING = "billing"  # Billing and metering
    EXPERIMENTAL = "experimental"  # Experimental features
    DEPRECATED = "deprecated"  # Deprecated flags (scheduled for removal)
    DEBUG = "debug"  # Debug/development flags


class FlagStatus(str, Enum):
    """Status of a feature flag."""

    ACTIVE = "active"  # In active use
    BETA = "beta"  # Beta feature
    ALPHA = "alpha"  # Alpha/experimental
    DEPRECATED = "deprecated"  # Scheduled for removal
    REMOVED = "removed"  # Removed but kept for backwards compat


@dataclass
class FlagDefinition:
    """Definition of a feature flag."""

    name: str
    flag_type: type
    default: Any
    description: str
    category: FlagCategory = FlagCategory.CORE
    status: FlagStatus = FlagStatus.ACTIVE
    env_var: str | None = None  # Environment variable override
    deprecated_since: str | None = None  # Version when deprecated
    removed_in: str | None = None  # Version when will be removed
    replacement: str | None = None  # Replacement flag if deprecated

    def __post_init__(self) -> None:
        # Auto-generate env var name if not provided
        if self.env_var is None:
            self.env_var = f"ARAGORA_{self.name.upper()}"


@dataclass
class FlagUsage:
    """Tracks usage of a feature flag."""

    name: str
    access_count: int = 0
    last_accessed: float | None = None
    access_locations: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def record_access(self, location: str | None = None) -> None:
        """Record a flag access."""
        self.access_count += 1
        self.last_accessed = time.time()
        if location:
            self.access_locations[location] += 1


@dataclass
class RegistryStats:
    """Statistics for the flag registry."""

    total_flags: int = 0
    active_flags: int = 0
    deprecated_flags: int = 0
    flags_by_category: dict[str, int] = field(default_factory=dict)
    total_accesses: int = 0
    unknown_accesses: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "total_flags": self.total_flags,
            "active_flags": self.active_flags,
            "deprecated_flags": self.deprecated_flags,
            "flags_by_category": self.flags_by_category,
            "total_accesses": self.total_accesses,
            "unknown_accesses": self.unknown_accesses,
        }


class FeatureFlagRegistry:
    """Central registry for all feature flags.

    Provides validation, documentation, and usage tracking for
    feature flags across the codebase.
    """

    def __init__(self, warn_on_unknown: bool = True):
        """Initialize the registry.

        Args:
            warn_on_unknown: Log warnings when accessing unregistered flags
        """
        self._flags: dict[str, FlagDefinition] = {}
        self._usage: dict[str, FlagUsage] = defaultdict(lambda: FlagUsage(name=""))
        self._unknown_flags: set[str] = set()
        self._warn_on_unknown = warn_on_unknown
        self._lock = threading.RLock()

        # Register built-in flags
        self._register_builtin_flags()

    def register(
        self,
        name: str,
        flag_type: type = bool,
        default: Any = False,
        description: str = "",
        category: FlagCategory = FlagCategory.CORE,
        status: FlagStatus = FlagStatus.ACTIVE,
        env_var: str | None = None,
        deprecated_since: str | None = None,
        removed_in: str | None = None,
        replacement: str | None = None,
    ) -> FlagDefinition:
        """Register a feature flag.

        Args:
            name: Flag name (e.g., "enable_knowledge_retrieval")
            flag_type: Type of the flag value (bool, int, float, str)
            default: Default value
            description: Human-readable description
            category: Flag category for organization
            status: Current status of the flag
            env_var: Environment variable override
            deprecated_since: Version when deprecated
            removed_in: Version when will be removed
            replacement: Replacement flag if deprecated

        Returns:
            The registered FlagDefinition
        """
        flag = FlagDefinition(
            name=name,
            flag_type=flag_type,
            default=default,
            description=description,
            category=category,
            status=status,
            env_var=env_var,
            deprecated_since=deprecated_since,
            removed_in=removed_in,
            replacement=replacement,
        )

        with self._lock:
            self._flags[name] = flag
            self._usage[name] = FlagUsage(name=name)

        return flag

    def get_definition(self, name: str) -> FlagDefinition | None:
        """Get the definition of a flag."""
        return self._flags.get(name)

    def is_registered(self, name: str) -> bool:
        """Check if a flag is registered."""
        return name in self._flags

    @overload
    def get_value(self, name: str, default: T) -> T: ...

    @overload
    def get_value(self, name: str) -> Any: ...

    def get_value(self, name: str, default: Any = None) -> Any:
        """Get the current value of a flag.

        Resolution order:
        1. Environment variable (if defined)
        2. Tenant configuration (if available)
        3. Default value

        Args:
            name: Flag name
            default: Override default if not registered

        Returns:
            Current flag value
        """
        with self._lock:
            # Track access
            self._usage[name].record_access()

            flag = self._flags.get(name)

            if flag is None:
                self._unknown_flags.add(name)
                if self._warn_on_unknown:
                    logger.warning("Access to unregistered feature flag: %s", name)
                return default

            # Check for deprecation
            if flag.status == FlagStatus.DEPRECATED:
                msg = f"Feature flag '{name}' is deprecated"
                if flag.replacement:
                    msg += f", use '{flag.replacement}' instead"
                if flag.removed_in:
                    msg += f" (will be removed in {flag.removed_in})"
                logger.warning(msg)

            # Check environment variable
            if flag.env_var:
                env_value = os.environ.get(flag.env_var)
                if env_value is not None:
                    return self._parse_value(env_value, flag.flag_type)

            # Check tenant configuration
            tenant_value = self._get_tenant_value(name)
            if tenant_value is not None:
                return tenant_value

            return flag.default

    def is_enabled(self, name: str) -> bool:
        """Check if a boolean flag is enabled.

        Convenience method for boolean flags.

        Args:
            name: Flag name

        Returns:
            True if enabled, False otherwise
        """
        value = self.get_value(name, default=False)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ("true", "1", "yes", "on")
        return bool(value)

    def get_all_flags(
        self, category: FlagCategory | None = None, status: FlagStatus | None = None
    ) -> list[FlagDefinition]:
        """Get all registered flags.

        Args:
            category: Optional filter by category
            status: Optional filter by status

        Returns:
            List of flag definitions
        """
        with self._lock:
            flags = list(self._flags.values())

        if category:
            flags = [f for f in flags if f.category == category]
        if status:
            flags = [f for f in flags if f.status == status]

        return sorted(flags, key=lambda f: (f.category.value, f.name))

    def get_usage(self, name: str) -> FlagUsage | None:
        """Get usage statistics for a flag."""
        return self._usage.get(name)

    def get_unknown_flags(self) -> set[str]:
        """Get flags that were accessed but not registered."""
        return self._unknown_flags.copy()

    def get_stats(self) -> RegistryStats:
        """Get registry statistics."""
        stats = RegistryStats()

        with self._lock:
            stats.total_flags = len(self._flags)
            stats.active_flags = sum(
                1 for f in self._flags.values() if f.status == FlagStatus.ACTIVE
            )
            stats.deprecated_flags = sum(
                1 for f in self._flags.values() if f.status == FlagStatus.DEPRECATED
            )

            # By category
            for flag in self._flags.values():
                cat = flag.category.value
                stats.flags_by_category[cat] = stats.flags_by_category.get(cat, 0) + 1

            # Usage
            stats.total_accesses = sum(u.access_count for u in self._usage.values())
            stats.unknown_accesses = len(self._unknown_flags)

        return stats

    def validate_flags(self, flags: dict[str, Any]) -> list[str]:
        """Validate a dictionary of flag values.

        Args:
            flags: Dictionary of flag name -> value

        Returns:
            List of validation errors
        """
        errors: list[str] = []

        for name, value in flags.items():
            if name not in self._flags:
                errors.append(f"Unknown flag: {name}")
                continue

            flag = self._flags[name]
            if not isinstance(value, flag.flag_type):
                errors.append(
                    f"Flag '{name}' expects {flag.flag_type.__name__}, got {type(value).__name__}"
                )

        return errors

    def export_documentation(self) -> str:
        """Export flag documentation as markdown."""
        lines = ["# Feature Flags", ""]

        # Group by category
        by_category: dict[FlagCategory, list[FlagDefinition]] = defaultdict(list)
        for flag in self._flags.values():
            by_category[flag.category].append(flag)

        for category in FlagCategory:
            flags = by_category.get(category, [])
            if not flags:
                continue

            lines.append(f"## {category.value.title()}")
            lines.append("")

            for flag in sorted(flags, key=lambda f: f.name):
                status_badge = ""
                if flag.status == FlagStatus.DEPRECATED:
                    status_badge = " [DEPRECATED]"
                elif flag.status == FlagStatus.BETA:
                    status_badge = " [BETA]"
                elif flag.status == FlagStatus.ALPHA:
                    status_badge = " [ALPHA]"

                lines.append(f"### `{flag.name}`{status_badge}")
                lines.append("")
                lines.append(f"- **Type:** `{flag.flag_type.__name__}`")
                lines.append(f"- **Default:** `{flag.default}`")
                lines.append(f"- **Env:** `{flag.env_var}`")
                if flag.description:
                    lines.append(f"- **Description:** {flag.description}")
                if flag.replacement:
                    lines.append(f"- **Replacement:** `{flag.replacement}`")
                lines.append("")

        return "\n".join(lines)

    def _parse_value(self, value: str, flag_type: type) -> Any:
        """Parse a string value to the correct type."""
        if flag_type is bool:
            return value.lower() in ("true", "1", "yes", "on")
        if flag_type is int:
            return int(value)
        if flag_type is float:
            return float(value)
        return value

    def _get_tenant_value(self, name: str) -> Any | None:
        """Get flag value from tenant configuration."""
        try:
            from aragora.config.tenant_context import get_current_tenant

            tenant = get_current_tenant()
            if tenant and tenant.config:
                # Map common flags to tenant config
                config = tenant.config
                mappings = {
                    "enable_rlm": getattr(config, "enable_rlm", None),
                    "enable_extended_debates": getattr(config, "enable_extended_debates", None),
                    "enable_custom_agents": getattr(config, "enable_custom_agents", None),
                    "enable_api_access": getattr(config, "enable_api_access", None),
                    "enable_webhooks": getattr(config, "enable_webhooks", None),
                    "enable_sso": getattr(config, "enable_sso", None),
                    "enable_audit_log": getattr(config, "enable_audit_log", None),
                }
                return mappings.get(name)
        except ImportError:
            logger.debug("Tenancy module not available; skipping tenant flag lookup for %s", name)
        return None

    def _register_builtin_flags(self) -> None:
        """Register all built-in feature flags."""
        # Native mission orchestrator (set-a-goal, walk-away; see
        # docs/plans/2026-06-16-native-mission-orchestrator.md). Default OFF and
        # EXPERIMENTAL: gates the long-running engine wiring that lands in later
        # PRs. The MissionSpec/WorkItem contracts (aragora/nomic/mission.py) are
        # inert data until this is enabled.
        self.register(
            "enable_native_mission",
            bool,
            False,
            "Enable the native mission orchestrator (nomic goal-intake -> boss_loop engine)",
            FlagCategory.EXPERIMENTAL,
            FlagStatus.BETA,
            env_var="ARAGORA_ENABLE_NATIVE_MISSION",
        )
        # OpenRouter Fusion (multi-model council+judge). All default OFF: Fusion
        # is ~4-5x cost and must be an explicit opt-in. Downstream phases
        # (planning/verify/quorum tie-break) gate on their own flags so each can
        # be enabled independently.
        self.register(
            "enable_fusion",
            bool,
            False,
            "Enable the OpenRouter Fusion agent (multi-model council+judge) as a selectable participant/judge",
            FlagCategory.EXPERIMENTAL,
            FlagStatus.BETA,
            env_var="ARAGORA_ENABLE_FUSION",
        )
        self.register(
            "fusion_cost_budget_per_debate",
            float,
            50.0,
            "Per-debate Fusion budget (USD). Planning gates on this: a value <= 0 keeps "
            "Fusion out of planning debates even when enable_fusion is on. Live per-call "
            "USD enforcement is handled by the billing budget manager.",
            FlagCategory.BILLING,
        )
        self.register(
            "fusion_cost_monthly_cap",
            float,
            5000.0,
            "[scaffolding; enforcement lands in the nomic-integration PR] Monthly USD cap across all Fusion calls",
            FlagCategory.BILLING,
        )
        # Codex agent bridge (cross-agent observation + advisory steering). Default
        # OFF: reading a one-shot digest needs no flag (it touches nothing), but any
        # orchestration use -- auto-ingesting sibling Codex state or writing advisory
        # steering -- is an explicit opt-in. The steering channel is advisory and
        # monotonic-restrictive: it can only ever add caution, never grant a gate
        # bypass, so the merge-quorum gate stays the sole merge authority.
        self.register(
            "enable_codex_bridge",
            bool,
            False,
            "Enable cross-agent ingest of local Codex session/automation state and advisory steer-back",
            FlagCategory.EXPERIMENTAL,
            FlagStatus.BETA,
            env_var="ARAGORA_ENABLE_CODEX_BRIDGE",
        )
        self.register(
            "enable_fusion_quorum_tiebreak",
            bool,
            False,
            "Run an advisory, non-counting OpenRouter Fusion tie-breaker when merge-quorum reviewers split",
            FlagCategory.EXPERIMENTAL,
            FlagStatus.BETA,
            env_var="ARAGORA_ENABLE_FUSION_QUORUM_TIEBREAK",
        )
        # Knowledge Mound flags
        self.register(
            "enable_knowledge_retrieval",
            bool,
            True,
            "Query Knowledge Mound before debates for relevant context",
            FlagCategory.KNOWLEDGE,
        )
        self.register(
            "enable_knowledge_ingestion",
            bool,
            True,
            "Store consensus outcomes in Knowledge Mound after debates",
            FlagCategory.KNOWLEDGE,
        )
        self.register(
            "enable_knowledge_extraction",
            bool,
            False,
            "Extract structured claims from debate content",
            FlagCategory.KNOWLEDGE,
        )
        self.register(
            "enable_auto_revalidation",
            bool,
            False,
            "Auto-trigger revalidation for stale knowledge",
            FlagCategory.KNOWLEDGE,
        )
        self.register(
            "enable_belief_guidance",
            bool,
            True,
            "Inject historical cruxes from similar debates as context",
            FlagCategory.KNOWLEDGE,
        )
        self.register(
            "enable_cross_debate_memory",
            bool,
            True,
            "Inject institutional knowledge from past debates",
            FlagCategory.MEMORY,
        )

        # Performance flags
        self.register(
            "enable_performance_monitor",
            bool,
            True,
            "Auto-create PerformanceMonitor for timing metrics",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_performance_feedback",
            bool,
            True,
            "Adjust selection weights based on debate performance",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_performance_elo",
            bool,
            True,
            "Use performance metrics to modulate ELO K-factors",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_performance_router",
            bool,
            True,
            "Use performance metrics to inform routing",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_telemetry",
            bool,
            True,  # Changed to True for default observability
            "Enable Prometheus/Blackbox telemetry emission",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_tracing",
            bool,
            True,
            "Enable distributed tracing with correlation IDs",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_metrics",
            bool,
            True,
            "Enable Prometheus metrics collection",
            FlagCategory.PERFORMANCE,
        )
        self.register(
            "enable_structured_logging",
            bool,
            True,
            "Enable JSON structured logging with context",
            FlagCategory.PERFORMANCE,
        )

        # Core debate flags
        self.register(
            "enable_checkpointing",
            bool,
            False,
            "Auto-create CheckpointManager for pause/resume",
            FlagCategory.CORE,
        )
        self.register(
            "enable_coordinated_writes",
            bool,
            True,
            "Use MemoryCoordinator for atomic multi-system writes",
            FlagCategory.CORE,
        )
        self.register(
            "enable_hook_handlers",
            bool,
            True,
            "Register default hook handlers via HookHandlerRegistry",
            FlagCategory.CORE,
        )
        self.register(
            "enable_yaml_hooks",
            bool,
            True,
            "Auto-discover and load YAML hooks on startup",
            FlagCategory.CORE,
        )

        # ML integration flags (graduated from BETA to STABLE)
        self.register(
            "enable_ml_delegation",
            bool,
            True,
            "Use ML-based agent selection",
            FlagCategory.PERFORMANCE,
            FlagStatus.ACTIVE,
        )
        self.register(
            "enable_quality_gates",
            bool,
            True,
            "Filter low-quality responses via QualityGate",
            FlagCategory.PERFORMANCE,
            FlagStatus.ACTIVE,
        )
        self.register(
            "enable_consensus_estimation",
            bool,
            True,
            "Use ConsensusEstimator for early termination",
            FlagCategory.PERFORMANCE,
            FlagStatus.ACTIVE,
        )
        self.register(
            "enable_prompt_evolution",
            bool,
            False,
            "Auto-create PromptEvolver for adaptive prompts",
            FlagCategory.EXPERIMENTAL,
            FlagStatus.ALPHA,
        )
        self.register(
            "truthful_default_loop_v1",
            bool,
            False,
            "Enable the promotion gate for truthful default debate loop readiness checks",
            FlagCategory.EXPERIMENTAL,
            FlagStatus.ALPHA,
        )

        # Billing flags
        self.register(
            "enable_receipt_generation",
            bool,
            False,
            "Auto-generate decision receipts after debates",
            FlagCategory.BILLING,
        )
        self.register(
            "enable_provenance",
            bool,
            False,
            "Enable evidence provenance tracking",
            FlagCategory.BILLING,
        )
        self.register(
            "enable_bead_tracking",
            bool,
            False,
            "Create Bead for each debate decision",
            FlagCategory.BILLING,
        )

        # Decision integrity rollout flags
        self.register(
            "receipt_enforcement_openclaw",
            bool,
            False,
            "Require approved execution receipts for OpenClaw action execution paths",
            FlagCategory.CORE,
            FlagStatus.ALPHA,
        )
        self.register(
            "receipt_enforcement_canvas",
            bool,
            False,
            "Require approved execution receipts for canvas action execution paths",
            FlagCategory.CORE,
            FlagStatus.ALPHA,
        )
        self.register(
            "receipt_enforcement_computer_use",
            bool,
            False,
            "Require approved execution receipts for computer-use orchestration paths",
            FlagCategory.CORE,
            FlagStatus.ALPHA,
        )
        self.register(
            "receipt_enforcement_inbox",
            bool,
            False,
            "Require approved execution receipts for inbox mutation paths",
            FlagCategory.CORE,
            FlagStatus.ALPHA,
        )
        self.register(
            "receipt_enforcement_shared_inbox",
            bool,
            False,
            "Require approved execution receipts for shared inbox mutation paths",
            FlagCategory.CORE,
            FlagStatus.ALPHA,
        )

        # Oracle streaming
        self.register(
            "enable_oracle_streaming",
            bool,
            True,
            "Enable real-time WebSocket streaming for the Shoggoth Oracle with live TTS",
            FlagCategory.CORE,
        )
        self.register(
            "enable_oracle_voice",
            bool,
            False,
            "Enable TTS voice synthesis for Oracle debate events (agent_message, critique)",
            FlagCategory.EXPERIMENTAL,
            env_var="ENABLE_ORACLE_VOICE",
        )

        # Debug flags
        self.register(
            "enable_n1_detection",
            bool,
            False,
            "Enable N+1 query detection during debate phases",
            FlagCategory.DEBUG,
        )

        # Tenant-level flags
        self.register(
            "enable_rlm",
            bool,
            False,
            "Enable Recursive Language Models for tenant",
            FlagCategory.CORE,
        )
        self.register(
            "enable_extended_debates",
            bool,
            False,
            "Enable extended debate sessions",
            FlagCategory.CORE,
        )
        self.register(
            "enable_custom_agents",
            bool,
            False,
            "Allow tenant to use custom agents",
            FlagCategory.CORE,
        )
        self.register(
            "enable_api_access",
            bool,
            True,
            "Enable API access for tenant",
            FlagCategory.CORE,
        )
        self.register(
            "enable_webhooks",
            bool,
            False,
            "Enable webhook delivery for tenant",
            FlagCategory.CORE,
        )
        self.register(
            "enable_sso",
            bool,
            False,
            "Enable SSO for tenant",
            FlagCategory.CORE,
        )
        self.register(
            "enable_audit_log",
            bool,
            False,
            "Enable audit logging for tenant",
            FlagCategory.CORE,
        )


# ---------------------------------------------------------------------------
# Global instance and convenience functions
# ---------------------------------------------------------------------------

_registry: FeatureFlagRegistry | None = None
_lock = threading.Lock()


def get_flag_registry() -> FeatureFlagRegistry:
    """Get or create the global feature flag registry."""
    global _registry
    if _registry is None:
        with _lock:
            if _registry is None:
                _registry = FeatureFlagRegistry()
    return _registry


def reset_flag_registry() -> None:
    """Reset the global feature flag registry (for testing)."""
    global _registry
    with _lock:
        _registry = None


def is_enabled(name: str) -> bool:
    """Check if a boolean feature flag is enabled.

    Convenience function for checking feature flags.

    Args:
        name: Flag name

    Returns:
        True if enabled
    """
    return get_flag_registry().is_enabled(name)


@overload
def get_flag(name: str, default: T) -> T: ...


@overload
def get_flag(name: str) -> Any: ...


def get_flag(name: str, default: Any = None) -> Any:
    """Get a feature flag value.

    Convenience function for getting feature flag values.

    Args:
        name: Flag name
        default: Default value if not found

    Returns:
        Flag value
    """
    return get_flag_registry().get_value(name, default)


__all__ = [
    "FeatureFlagRegistry",
    "FlagCategory",
    "FlagDefinition",
    "FlagStatus",
    "FlagUsage",
    "RegistryStats",
    "get_flag",
    "get_flag_registry",
    "is_enabled",
    "reset_flag_registry",
]
