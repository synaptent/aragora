"""
Unified Event Type Registry.

Provides a single source of truth for all event types across Aragora subsystems,
with schema validation, documentation, and discovery capabilities.

Current state (consolidated):
- StreamEventType: 197 event types (core debate, knowledge, memory, workflow)
- NotificationEventType: 19 event types (control plane tasks, alerts)
- DeliberationEventType: 18 event types (control plane deliberations)
- SecurityEventType: 13 event types (vulnerability scanning, threat detection)

Total: 247 event types across 4 subsystems.

Usage:
    from aragora.events.registry import (
        EventRegistry,
        get_event_registry,
        EventCategory,
        EventMetadata,
    )

    # Get registry
    registry = get_event_registry()

    # Look up event metadata
    metadata = registry.get_event("debate_start")

    # List events by category
    events = registry.list_events(category=EventCategory.DEBATE)

    # Validate event payload
    is_valid = registry.validate_payload("debate_start", payload)

    # Get schema for event
    schema = registry.get_schema("debate_start")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, TypeVar
from collections.abc import Callable, Iterable

logger = logging.getLogger(__name__)

NotificationEventContributor = Callable[[], Iterable[str]]
_notification_event_contributor: NotificationEventContributor | None = None


def register_notification_event_contributor(
    contributor: NotificationEventContributor | None,
) -> None:
    """Register the application-owned source of notification event names."""
    global _notification_event_contributor
    _notification_event_contributor = contributor


class EventCategory(str, Enum):
    """Categories for organizing events."""

    # Core categories
    DEBATE = "debate"  # debate_start, round_start, agent_message, etc.
    KNOWLEDGE = "knowledge"  # km_*, knowledge_*
    MEMORY = "memory"  # memory_*, tier_*
    WORKFLOW = "workflow"  # workflow_*
    GAUNTLET = "gauntlet"  # gauntlet_*

    # Integration categories
    STREAMING = "streaming"  # token_*, voice_*
    WEBHOOK = "webhook"  # connector_*
    NOTIFICATION = "notification"  # alert_*, sla_*

    # Subsystem categories
    CONTROL_PLANE = "control_plane"  # task_*, agent_*, deliberation_*
    SECURITY = "security"  # vulnerability_*, threat_*, scan_*
    AUTONOMOUS = "autonomous"  # approval_*, learning_*, trigger_*

    # Meta categories
    SYSTEM = "system"  # heartbeat, error, progress
    TELEMETRY = "telemetry"  # telemetry_*
    EXPLAINABILITY = "explainability"  # explainability_*


class EventSeverity(str, Enum):
    """Severity levels for events."""

    DEBUG = "debug"  # Internal debugging
    INFO = "info"  # Informational
    WARNING = "warning"  # Potential issues
    ERROR = "error"  # Errors requiring attention
    CRITICAL = "critical"  # Critical issues


class EventSource(str, Enum):
    """Source subsystems for events."""

    STREAM = "stream"  # StreamEventType
    CONTROL_PLANE = "control_plane"  # NotificationEventType
    DELIBERATION = "deliberation"  # DeliberationEventType
    SECURITY = "security"  # SecurityEventType


@dataclass
class EventMetadata:
    """Metadata for a registered event type."""

    name: str  # Event name (e.g., "debate_start")
    category: EventCategory
    source: EventSource
    severity: EventSeverity = EventSeverity.INFO

    # Documentation
    description: str = ""
    example_payload: dict[str, Any] = field(default_factory=dict)

    # Schema
    schema_class: type | None = None  # Payload dataclass if available
    required_fields: list[str] = field(default_factory=list)
    optional_fields: list[str] = field(default_factory=list)

    # Routing
    webhookable: bool = True  # Can be sent via webhook
    streamable: bool = True  # Can be sent via WebSocket
    batchable: bool = False  # Can be batched with other events

    # SLA
    sla_critical: bool = False  # Part of SLA monitoring
    max_latency_ms: int | None = None  # Max acceptable latency

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "category": self.category.value,
            "source": self.source.value,
            "severity": self.severity.value,
            "description": self.description,
            "required_fields": self.required_fields,
            "optional_fields": self.optional_fields,
            "webhookable": self.webhookable,
            "streamable": self.streamable,
            "batchable": self.batchable,
            "sla_critical": self.sla_critical,
        }


T = TypeVar("T")


class EventRegistry:
    """Unified registry for all event types.

    Provides:
    - Event type discovery and documentation
    - Schema validation for payloads
    - Category-based event lookup
    - Cross-subsystem event unification
    """

    def __init__(self):
        self._events: dict[str, EventMetadata] = {}
        self._by_category: dict[EventCategory, list[str]] = {cat: [] for cat in EventCategory}
        self._by_source: dict[EventSource, list[str]] = {src: [] for src in EventSource}
        self._validators: dict[str, Callable[[dict], bool]] = {}

        # Auto-register known events
        self._register_builtin_events()

    def register(
        self,
        name: str,
        category: EventCategory,
        source: EventSource,
        severity: EventSeverity = EventSeverity.INFO,
        description: str = "",
        schema_class: type | None = None,
        required_fields: list[str] | None = None,
        optional_fields: list[str] | None = None,
        webhookable: bool = True,
        streamable: bool = True,
        batchable: bool = False,
        sla_critical: bool = False,
        max_latency_ms: int | None = None,
        validator: Callable[[dict], bool] | None = None,
    ) -> EventMetadata:
        """Register an event type.

        Args:
            name: Event name (lowercase snake_case)
            category: Event category
            source: Source subsystem
            severity: Event severity
            description: Human-readable description
            schema_class: Optional payload dataclass
            required_fields: Required payload fields
            optional_fields: Optional payload fields
            webhookable: Can be sent via webhook
            streamable: Can be sent via WebSocket
            batchable: Can be batched
            sla_critical: Part of SLA monitoring
            max_latency_ms: Max acceptable latency
            validator: Optional payload validator function

        Returns:
            Registered EventMetadata
        """
        metadata = EventMetadata(
            name=name,
            category=category,
            source=source,
            severity=severity,
            description=description,
            schema_class=schema_class,
            required_fields=required_fields or [],
            optional_fields=optional_fields or [],
            webhookable=webhookable,
            streamable=streamable,
            batchable=batchable,
            sla_critical=sla_critical,
            max_latency_ms=max_latency_ms,
        )

        self._events[name] = metadata
        self._by_category[category].append(name)
        self._by_source[source].append(name)

        if validator:
            self._validators[name] = validator

        return metadata

    def get_event(self, name: str) -> EventMetadata | None:
        """Get metadata for an event type."""
        return self._events.get(name)

    def list_events(
        self,
        category: EventCategory | None = None,
        source: EventSource | None = None,
        sla_critical_only: bool = False,
    ) -> list[EventMetadata]:
        """List events with optional filtering.

        Args:
            category: Filter by category
            source: Filter by source
            sla_critical_only: Only return SLA-critical events

        Returns:
            List of matching EventMetadata
        """
        if category:
            names = self._by_category.get(category, [])
        elif source:
            names = self._by_source.get(source, [])
        else:
            names = list(self._events.keys())

        events = [self._events[n] for n in names if n in self._events]

        if sla_critical_only:
            events = [e for e in events if e.sla_critical]

        return events

    def validate_payload(self, event_name: str, payload: dict[str, Any]) -> tuple[bool, str]:
        """Validate an event payload.

        Args:
            event_name: Event type name
            payload: Payload to validate

        Returns:
            Tuple of (is_valid, error_message)
        """
        metadata = self.get_event(event_name)
        if not metadata:
            return False, f"Unknown event type: {event_name}"

        # Check required fields
        for field_name in metadata.required_fields:
            if field_name not in payload:
                return False, f"Missing required field: {field_name}"

        # Run custom validator if available
        if event_name in self._validators:
            try:
                if not self._validators[event_name](payload):
                    return False, "Custom validation failed"
            except (TypeError, ValueError, KeyError, AttributeError) as e:
                return False, f"Validation error: {e}"

        return True, ""

    def get_schema(self, event_name: str) -> dict[str, Any] | None:
        """Get JSON schema for an event type.

        Args:
            event_name: Event type name

        Returns:
            JSON schema dict or None
        """
        metadata = self.get_event(event_name)
        if not metadata:
            return None

        schema: dict[str, Any] = {
            "type": "object",
            "properties": {},
            "required": metadata.required_fields,
        }

        # Add required fields
        for field_name in metadata.required_fields:
            schema["properties"][field_name] = {"type": "string"}  # Default to string

        # Add optional fields
        for field_name in metadata.optional_fields:
            schema["properties"][field_name] = {"type": "string"}

        return schema

    def get_stats(self) -> dict[str, Any]:
        """Get registry statistics."""
        return {
            "total_events": len(self._events),
            "by_category": {cat.value: len(names) for cat, names in self._by_category.items()},
            "by_source": {src.value: len(names) for src, names in self._by_source.items()},
            "sla_critical_count": len([e for e in self._events.values() if e.sla_critical]),
            "with_schema": len([e for e in self._events.values() if e.schema_class]),
        }

    def to_openapi_webhooks(self) -> dict[str, Any]:
        """Generate OpenAPI webhooks section for documentation."""
        webhooks = {}
        for name, metadata in self._events.items():
            if metadata.webhookable:
                webhooks[name] = {
                    "post": {
                        "summary": metadata.description or f"{name} event",
                        "tags": [metadata.category.value],
                        "requestBody": {
                            "content": {
                                "application/json": {
                                    "schema": self.get_schema(name) or {"type": "object"}
                                }
                            }
                        },
                        "responses": {"200": {"description": "Event acknowledged"}},
                    }
                }
        return webhooks

    def _register_builtin_events(self) -> None:
        """Register all known event types from existing enums."""
        # Import existing types
        try:
            from aragora.events.types import StreamEventType

            self._register_stream_events(StreamEventType)
        except ImportError:
            logger.debug("StreamEventType not available")

        if _notification_event_contributor is not None:
            try:
                self._register_notification_events(_notification_event_contributor())
            except (ImportError, RuntimeError, TypeError, ValueError) as e:
                logger.debug("Notification event contributor not available: %s", e)

        try:
            from aragora.control_plane.deliberation_events import DeliberationEventType

            self._register_deliberation_events(DeliberationEventType)
        except ImportError:
            logger.debug("DeliberationEventType not available")

        try:
            from aragora.events.security_events import SecurityEventType

            self._register_security_events(SecurityEventType)
        except ImportError:
            logger.debug("SecurityEventType not available")

    def _register_stream_events(self, enum_class: type[Enum]) -> None:
        """Register StreamEventType events."""
        # Category mappings based on event name prefixes
        category_map = {
            "debate_": EventCategory.DEBATE,
            "round_": EventCategory.DEBATE,
            "agent_": EventCategory.DEBATE,
            "critique": EventCategory.DEBATE,
            "vote": EventCategory.DEBATE,
            "consensus": EventCategory.DEBATE,
            "synthesis": EventCategory.DEBATE,
            "knowledge_": EventCategory.KNOWLEDGE,
            "km_": EventCategory.KNOWLEDGE,
            "mound_": EventCategory.KNOWLEDGE,
            "memory_": EventCategory.MEMORY,
            "workflow_": EventCategory.WORKFLOW,
            "gauntlet_": EventCategory.GAUNTLET,
            "receipt_": EventCategory.GAUNTLET,
            "token_": EventCategory.STREAMING,
            "voice_": EventCategory.STREAMING,
            "transcription_": EventCategory.STREAMING,
            "connector_": EventCategory.WEBHOOK,
            "telemetry_": EventCategory.TELEMETRY,
            "explainability_": EventCategory.EXPLAINABILITY,
            "approval_": EventCategory.AUTONOMOUS,
            "learning_": EventCategory.AUTONOMOUS,
            "trigger_": EventCategory.AUTONOMOUS,
            "heartbeat": EventCategory.SYSTEM,
            "error": EventCategory.SYSTEM,
            "phase_": EventCategory.SYSTEM,
        }

        for member in enum_class:
            name = member.value
            category = EventCategory.SYSTEM  # Default

            for prefix, cat in category_map.items():
                if name.startswith(prefix) or name == prefix.rstrip("_"):
                    category = cat
                    break

            self.register(
                name=name,
                category=category,
                source=EventSource.STREAM,
                description=f"Stream event: {name}",
            )

    def _register_notification_events(self, event_names: Iterable[str]) -> None:
        """Register application-contributed notification event names."""
        category_map = {
            "task_": EventCategory.CONTROL_PLANE,
            "deliberation_": EventCategory.CONTROL_PLANE,
            "agent_": EventCategory.CONTROL_PLANE,
            "sla_": EventCategory.NOTIFICATION,
            "policy_": EventCategory.CONTROL_PLANE,
            "system_": EventCategory.SYSTEM,
            "connector_": EventCategory.WEBHOOK,
        }

        for name in event_names:
            category = EventCategory.CONTROL_PLANE

            for prefix, cat in category_map.items():
                if name.startswith(prefix):
                    category = cat
                    break

            # SLA events are critical
            sla_critical = name.startswith("sla_")

            self.register(
                name=name,
                category=category,
                source=EventSource.CONTROL_PLANE,
                severity=EventSeverity.WARNING if sla_critical else EventSeverity.INFO,
                sla_critical=sla_critical,
                description=f"Control plane event: {name}",
            )

    def _register_deliberation_events(self, enum_class: type[Enum]) -> None:
        """Register DeliberationEventType events."""
        for member in enum_class:
            name = member.value
            # Convert dot-notation to snake_case for consistency
            normalized_name = name.replace(".", "_")

            sla_critical = "sla" in name.lower()

            self.register(
                name=normalized_name,
                category=EventCategory.CONTROL_PLANE,
                source=EventSource.DELIBERATION,
                severity=EventSeverity.WARNING if sla_critical else EventSeverity.INFO,
                sla_critical=sla_critical,
                description=f"Deliberation event: {name}",
            )

    def _register_security_events(self, enum_class: type[Enum]) -> None:
        """Register SecurityEventType events."""
        for member in enum_class:
            name = member.value

            # Critical events
            is_critical = "critical" in name.lower() or "threat" in name.lower()

            self.register(
                name=name,
                category=EventCategory.SECURITY,
                source=EventSource.SECURITY,
                severity=EventSeverity.CRITICAL if is_critical else EventSeverity.WARNING,
                sla_critical=is_critical,
                description=f"Security event: {name}",
            )


# Singleton registry
_event_registry: EventRegistry | None = None


def get_event_registry() -> EventRegistry:
    """Get or create the global event registry."""
    global _event_registry
    if _event_registry is None:
        _event_registry = EventRegistry()
    return _event_registry


def reset_event_registry() -> None:
    """Reset the global event registry (for testing)."""
    global _event_registry
    _event_registry = None
