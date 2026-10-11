"""
Telemetry configuration for Cognitive Firewall system.

Controls observation levels for agent thought streaming:
- SILENT: No telemetry output
- DIAGNOSTIC: Internal debugging only (logs, no broadcast)
- CONTROLLED: Filtered telemetry with security redaction
- SPECTACLE: Full transparency for demos/debugging

Now integrated with ServiceRegistry for centralized dependency management.
"""

from __future__ import annotations

__all__ = [
    "TelemetryLevel",
    "TelemetryConfig",
]

import logging
import os
from enum import Enum, auto

logger = logging.getLogger(__name__)


class TelemetryLevel(Enum):
    """Observation levels for agent telemetry."""

    SILENT = auto()  # No telemetry output
    DIAGNOSTIC = auto()  # Internal debugging only (logs, no broadcast)
    CONTROLLED = auto()  # Filtered telemetry with security redaction
    SPECTACLE = auto()  # Full transparency for demos/debugging


# Level name mappings for environment variable parsing
_LEVEL_NAMES = {
    "silent": TelemetryLevel.SILENT,
    "diagnostic": TelemetryLevel.DIAGNOSTIC,
    "controlled": TelemetryLevel.CONTROLLED,
    "spectacle": TelemetryLevel.SPECTACLE,
    # Numeric shortcuts
    "0": TelemetryLevel.SILENT,
    "1": TelemetryLevel.DIAGNOSTIC,
    "2": TelemetryLevel.CONTROLLED,
    "3": TelemetryLevel.SPECTACLE,
}


class TelemetryConfig:
    """
    Configuration manager for telemetry observation levels.

    Reads from ARAGORA_TELEMETRY_LEVEL environment variable.
    Defaults to CONTROLLED for security.
    """

    _instance: TelemetryConfig | None = None

    def __init__(self, level: TelemetryLevel | None = None):
        """
        Initialize telemetry configuration.

        Args:
            level: Explicit level override. If None, reads from environment.
        """
        if level is not None:
            self._level = level
        else:
            self._level = self._load_from_env()

    @classmethod
    def get_instance(cls) -> TelemetryConfig:
        """Get singleton instance via ServiceRegistry.

        Falls back to class-level singleton if ServiceRegistry unavailable.
        """
        # Try ServiceRegistry first (preferred)
        try:
            from aragora.runtime.service_registry import ServiceRegistry

            registry = ServiceRegistry.get()
            if registry.has(cls):
                return registry.resolve(cls)
            # Not in registry, create and register
            instance = cls()
            registry.register(cls, instance)
            logger.debug("TelemetryConfig registered with ServiceRegistry")
            return instance
        except ImportError:
            logger.debug("ServiceRegistry not available for TelemetryConfig")

        # Fallback to class-level singleton
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing).

        Clears both ServiceRegistry and class-level singleton.
        """
        # Clear from ServiceRegistry
        try:
            from aragora.runtime.service_registry import ServiceRegistry

            registry = ServiceRegistry.get()
            if registry.has(cls):
                registry.unregister(cls)
        except ImportError:
            logger.debug("ServiceRegistry not available for unregister")

        # Clear class-level singleton
        cls._instance = None

    def _load_from_env(self) -> TelemetryLevel:
        """Load telemetry level from environment variable."""
        env_value = os.environ.get("ARAGORA_TELEMETRY_LEVEL", "").lower().strip()

        if not env_value:
            # Default to CONTROLLED for security
            return TelemetryLevel.CONTROLLED

        level = _LEVEL_NAMES.get(env_value)
        if level is None:
            # Invalid value, log warning and default to CONTROLLED
            logger.warning(
                "Invalid ARAGORA_TELEMETRY_LEVEL '%s', defaulting to CONTROLLED. Valid values: %s",
                env_value,
                list(_LEVEL_NAMES.keys()),
            )
            return TelemetryLevel.CONTROLLED

        return level

    @property
    def level(self) -> TelemetryLevel:
        """Current telemetry level."""
        return self._level

    @level.setter
    def level(self, value: TelemetryLevel) -> None:
        """Set telemetry level."""
        self._level = value

    def is_silent(self) -> bool:
        """Check if telemetry is completely disabled."""
        return self._level == TelemetryLevel.SILENT

    def is_diagnostic(self) -> bool:
        """Check if telemetry is in diagnostic mode (logs only)."""
        return self._level == TelemetryLevel.DIAGNOSTIC

    def is_controlled(self) -> bool:
        """Check if telemetry is in controlled mode (redacted broadcast)."""
        return self._level == TelemetryLevel.CONTROLLED

    def is_spectacle(self) -> bool:
        """Check if telemetry is in spectacle mode (full transparency)."""
        return self._level == TelemetryLevel.SPECTACLE

    def should_broadcast(self) -> bool:
        """Check if telemetry should be broadcast to WebSocket clients."""
        return self._level in (TelemetryLevel.CONTROLLED, TelemetryLevel.SPECTACLE)

    def should_redact(self) -> bool:
        """Check if telemetry content should be redacted."""
        return self._level == TelemetryLevel.CONTROLLED

    def allows_level(self, required: TelemetryLevel) -> bool:
        """
        Check if current level allows the required observation level.

        Higher levels allow lower level operations.
        SPECTACLE > CONTROLLED > DIAGNOSTIC > SILENT
        """
        level_order = {
            TelemetryLevel.SILENT: 0,
            TelemetryLevel.DIAGNOSTIC: 1,
            TelemetryLevel.CONTROLLED: 2,
            TelemetryLevel.SPECTACLE: 3,
        }
        return level_order[self._level] >= level_order[required]

    def __repr__(self) -> str:
        return f"TelemetryConfig(level={self._level.name})"
