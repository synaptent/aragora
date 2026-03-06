"""
Inbox Debate Router.

Subscribes to incoming message events from integration channels (Slack, email,
Discord, Teams, etc.) and auto-spawns debates for messages matching configurable
priority/keyword rules. Routes debate results back to the originating channel
via the existing debate_origin system.

Architecture:
    Connectors --> StreamEvent(CONNECTOR_*) --> InboxDebateRouter
        |-> evaluate against TriggerRules
        |-> spawn Arena debate (async)
        |-> register DebateOrigin for result routing
        |-> emit INBOX_DEBATE_TRIGGERED event
        |-> on completion: emit INBOX_DEBATE_COMPLETED event

Usage:
    from aragora.inbox.debate_router import InboxDebateRouter, RouterConfig

    config = RouterConfig(
        enabled=True,
        priority_threshold="high",
        keyword_patterns=["urgent", "critical decision", "need consensus"],
    )
    router = InboxDebateRouter(config=config)
    await router.start()
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


class PriorityLevel(str, Enum):
    """Priority levels for inbox messages, ordered from lowest to highest."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"
    CRITICAL = "critical"


# Numeric ordering for comparison
_PRIORITY_ORDER: dict[str, int] = {
    "low": 0,
    "normal": 1,
    "high": 2,
    "urgent": 3,
    "critical": 4,
}


@dataclass
class TriggerRule:
    """A rule that determines whether an inbox message should spawn a debate.

    Rules are evaluated in priority order. The first matching rule triggers
    a debate. Rules support keyword matching, priority thresholds, sender
    patterns, and channel filtering.
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "default"
    enabled: bool = True

    # Keyword patterns (any match triggers)
    keyword_patterns: list[str] = field(default_factory=list)

    # Priority threshold (messages at or above this level trigger)
    priority_threshold: str | None = None

    # Sender patterns (regex, any match triggers)
    sender_patterns: list[str] = field(default_factory=list)

    # Channel filter (only messages from these channels trigger)
    channels: list[str] = field(default_factory=list)

    # Debate configuration overrides
    debate_rounds: int = 3
    debate_consensus: str = "majority"
    debate_agent_count: int = 4

    # Rule priority (lower = evaluated first)
    priority: int = 10

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "enabled": self.enabled,
            "keyword_patterns": self.keyword_patterns,
            "priority_threshold": self.priority_threshold,
            "sender_patterns": self.sender_patterns,
            "channels": self.channels,
            "debate_rounds": self.debate_rounds,
            "debate_consensus": self.debate_consensus,
            "debate_agent_count": self.debate_agent_count,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TriggerRule:
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", "default"),
            enabled=data.get("enabled", True),
            keyword_patterns=data.get("keyword_patterns", []),
            priority_threshold=data.get("priority_threshold"),
            sender_patterns=data.get("sender_patterns", []),
            channels=data.get("channels", []),
            debate_rounds=data.get("debate_rounds", 3),
            debate_consensus=data.get("debate_consensus", "majority"),
            debate_agent_count=data.get("debate_agent_count", 4),
            priority=data.get("priority", 10),
        )


@dataclass
class RouterConfig:
    """Configuration for the InboxDebateRouter.

    Controls whether auto-debate is enabled, what rules to apply, rate
    limiting, and default debate parameters.
    """

    # Master toggle
    enabled: bool = True

    # Default priority threshold (messages at or above this trigger debate)
    priority_threshold: str = "high"

    # Default keyword patterns that trigger debates
    keyword_patterns: list[str] = field(default_factory=list)

    # Custom trigger rules (evaluated in addition to defaults)
    rules: list[TriggerRule] = field(default_factory=list)

    # Rate limiting: max debates spawned per time window
    max_debates_per_hour: int = 10
    cooldown_seconds: float = 60.0  # Min time between debates from same channel

    # Default debate parameters
    default_rounds: int = 3
    default_consensus: str = "majority"
    default_agent_count: int = 4

    # Channels to monitor (empty = all channels)
    monitored_channels: list[str] = field(default_factory=list)

    # Channels to exclude
    excluded_channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "priority_threshold": self.priority_threshold,
            "keyword_patterns": self.keyword_patterns,
            "rules": [r.to_dict() for r in self.rules],
            "max_debates_per_hour": self.max_debates_per_hour,
            "cooldown_seconds": self.cooldown_seconds,
            "default_rounds": self.default_rounds,
            "default_consensus": self.default_consensus,
            "default_agent_count": self.default_agent_count,
            "monitored_channels": self.monitored_channels,
            "excluded_channels": self.excluded_channels,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RouterConfig:
        rules = [TriggerRule.from_dict(r) for r in data.get("rules", [])]
        return cls(
            enabled=data.get("enabled", True),
            priority_threshold=data.get("priority_threshold", "high"),
            keyword_patterns=data.get("keyword_patterns", []),
            rules=rules,
            max_debates_per_hour=data.get("max_debates_per_hour", 10),
            cooldown_seconds=data.get("cooldown_seconds", 60.0),
            default_rounds=data.get("default_rounds", 3),
            default_consensus=data.get("default_consensus", "majority"),
            default_agent_count=data.get("default_agent_count", 4),
            monitored_channels=data.get("monitored_channels", []),
            excluded_channels=data.get("excluded_channels", []),
        )


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class DebateSpawnResult:
    """Result of attempting to spawn a debate from an inbox message."""

    triggered: bool
    debate_id: str | None = None
    rule_matched: str | None = None
    reason: str = ""
    message_id: str | None = None
    channel: str | None = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "triggered": self.triggered,
            "debate_id": self.debate_id,
            "rule_matched": self.rule_matched,
            "reason": self.reason,
            "message_id": self.message_id,
            "channel": self.channel,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# InboxDebateRouter
# ---------------------------------------------------------------------------


class InboxDebateRouter:
    """Routes high-priority inbox messages to auto-spawned debates.

    Subscribes to incoming message events from integration channels and
    evaluates them against configurable trigger rules. When a rule matches,
    a debate is spawned via the Arena and the result is routed back to the
    originating channel.

    Features:
    - Configurable keyword and priority-based trigger rules
    - Per-channel rate limiting and cooldowns
    - Debate result routing back to originating channel
    - Event emission for monitoring (INBOX_ITEM_FLAGGED, INBOX_DEBATE_TRIGGERED)
    - Thread-safe stats tracking
    """

    def __init__(
        self,
        config: RouterConfig | None = None,
        event_bus: Any | None = None,
    ) -> None:
        self._config = config or RouterConfig()
        self._event_bus = event_bus
        self._running = False

        # Rate limiting state
        self._debate_timestamps: list[float] = []
        self._channel_cooldowns: dict[str, float] = {}

        # Stats
        self._stats = {
            "messages_evaluated": 0,
            "debates_triggered": 0,
            "debates_completed": 0,
            "debates_failed": 0,
            "messages_skipped": 0,
            "rate_limited": 0,
        }

        # Active debate tracking
        self._active_debates: dict[str, dict[str, Any]] = {}

    @property
    def config(self) -> RouterConfig:
        """Get the current router configuration."""
        return self._config

    @config.setter
    def config(self, value: RouterConfig) -> None:
        """Update the router configuration."""
        self._config = value

    @property
    def stats(self) -> dict[str, Any]:
        """Get router statistics."""
        return {
            **self._stats,
            "active_debates": len(self._active_debates),
            "enabled": self._config.enabled,
            "running": self._running,
        }

    @property
    def running(self) -> bool:
        """Check if the router is currently running."""
        return self._running

    async def start(self) -> None:
        """Start the router and subscribe to events.

        Subscribes to inbox-relevant event types from the event bus.
        """
        if self._running:
            logger.debug("InboxDebateRouter already running")
            return

        self._running = True
        logger.info(
            "InboxDebateRouter started (enabled=%s, threshold=%s, rules=%d)",
            self._config.enabled,
            self._config.priority_threshold,
            len(self._config.rules),
        )

    async def stop(self) -> None:
        """Stop the router and unsubscribe from events."""
        self._running = False
        logger.info("InboxDebateRouter stopped")

    def evaluate_message(self, message: dict[str, Any]) -> DebateSpawnResult:
        """Evaluate whether an inbox message should trigger a debate.

        Checks the message against all configured trigger rules and the
        default priority/keyword rules.

        Args:
            message: Message data dict with keys:
                - message_id: Unique message identifier
                - channel: Source channel (slack, email, discord, teams, etc.)
                - sender: Sender identifier
                - content: Message content/body
                - subject: Optional subject line
                - priority: Optional priority level string
                - metadata: Optional additional metadata

        Returns:
            DebateSpawnResult indicating whether a debate should be triggered
        """
        if not self._config.enabled:
            return DebateSpawnResult(
                triggered=False,
                reason="Router is disabled",
                message_id=message.get("message_id"),
                channel=message.get("channel"),
            )

        self._stats["messages_evaluated"] += 1

        message_id = message.get("message_id", "")
        channel = message.get("channel", "")
        content = message.get("content", "")
        subject = message.get("subject", "")
        priority = message.get("priority", "normal")

        # Check channel filters
        if self._config.monitored_channels and channel not in self._config.monitored_channels:
            self._stats["messages_skipped"] += 1
            return DebateSpawnResult(
                triggered=False,
                reason=f"Channel '{channel}' not in monitored channels",
                message_id=message_id,
                channel=channel,
            )

        if channel in self._config.excluded_channels:
            self._stats["messages_skipped"] += 1
            return DebateSpawnResult(
                triggered=False,
                reason=f"Channel '{channel}' is excluded",
                message_id=message_id,
                channel=channel,
            )

        # Check rate limits
        if not self._check_rate_limit(channel):
            self._stats["rate_limited"] += 1
            return DebateSpawnResult(
                triggered=False,
                reason="Rate limited",
                message_id=message_id,
                channel=channel,
            )

        # Evaluate custom rules first (sorted by priority)
        sorted_rules = sorted(
            [r for r in self._config.rules if r.enabled],
            key=lambda r: r.priority,
        )

        for rule in sorted_rules:
            if self._rule_matches(rule, message):
                return DebateSpawnResult(
                    triggered=True,
                    rule_matched=rule.name,
                    reason=f"Matched rule: {rule.name}",
                    message_id=message_id,
                    channel=channel,
                )

        # Evaluate default priority threshold
        if self._config.priority_threshold:
            threshold_order = _PRIORITY_ORDER.get(self._config.priority_threshold, 2)
            message_order = _PRIORITY_ORDER.get(priority, 1)
            if message_order >= threshold_order:
                return DebateSpawnResult(
                    triggered=True,
                    rule_matched="default_priority",
                    reason=f"Priority '{priority}' meets threshold '{self._config.priority_threshold}'",
                    message_id=message_id,
                    channel=channel,
                )

        # Evaluate default keyword patterns
        searchable_text = f"{subject} {content}".lower()
        for pattern in self._config.keyword_patterns:
            if pattern.lower() in searchable_text:
                return DebateSpawnResult(
                    triggered=True,
                    rule_matched="default_keyword",
                    reason=f"Matched keyword pattern: '{pattern}'",
                    message_id=message_id,
                    channel=channel,
                )

        self._stats["messages_skipped"] += 1
        return DebateSpawnResult(
            triggered=False,
            reason="No rules matched",
            message_id=message_id,
            channel=channel,
        )

    def _rule_matches(self, rule: TriggerRule, message: dict[str, Any]) -> bool:
        """Check if a trigger rule matches a message.

        Args:
            rule: The trigger rule to evaluate
            message: Message data dict

        Returns:
            True if the rule matches
        """
        channel = message.get("channel", "")
        content = message.get("content", "")
        subject = message.get("subject", "")
        sender = message.get("sender", "")
        priority = message.get("priority", "normal")

        # Channel filter (if specified, must match)
        if rule.channels and channel not in rule.channels:
            return False

        # Check priority threshold
        if rule.priority_threshold:
            threshold_order = _PRIORITY_ORDER.get(rule.priority_threshold, 2)
            message_order = _PRIORITY_ORDER.get(priority, 1)
            if message_order < threshold_order:
                return False

        matched_any = False

        # Check keyword patterns
        if rule.keyword_patterns:
            searchable = f"{subject} {content}".lower()
            for pattern in rule.keyword_patterns:
                if pattern.lower() in searchable:
                    matched_any = True
                    break

        # Check sender patterns
        if rule.sender_patterns:
            for pattern in rule.sender_patterns:
                try:
                    if re.search(pattern, sender, re.IGNORECASE):
                        matched_any = True
                        break
                except re.error:
                    logger.warning("Invalid sender regex pattern: %s", pattern)

        # If the rule has keyword or sender patterns, at least one must match
        if rule.keyword_patterns or rule.sender_patterns:
            return matched_any

        # If only priority threshold is set and it was met (not returned False above)
        if rule.priority_threshold:
            return True

        return False

    def _check_rate_limit(self, channel: str) -> bool:
        """Check if a debate can be spawned (rate limiting).

        Args:
            channel: Source channel identifier

        Returns:
            True if within rate limits
        """
        now = time.time()

        # Check per-channel cooldown
        last_trigger = self._channel_cooldowns.get(channel, 0.0)
        if now - last_trigger < self._config.cooldown_seconds:
            return False

        # Check hourly rate limit
        one_hour_ago = now - 3600.0
        self._debate_timestamps = [t for t in self._debate_timestamps if t > one_hour_ago]
        if len(self._debate_timestamps) >= self._config.max_debates_per_hour:
            return False

        return True

    def _record_debate_spawn(self, channel: str) -> None:
        """Record that a debate was spawned for rate limiting."""
        now = time.time()
        self._debate_timestamps.append(now)
        self._channel_cooldowns[channel] = now

    async def spawn_debate(self, message: dict[str, Any]) -> DebateSpawnResult:
        """Evaluate a message and spawn a debate if triggered.

        This is the main entry point for processing inbox messages. It
        evaluates the message, and if triggered, spawns a debate via the
        Arena and registers the origin for result routing.

        Args:
            message: Message data dict (see evaluate_message for schema)

        Returns:
            DebateSpawnResult with debate_id if triggered
        """
        result = self.evaluate_message(message)

        if not result.triggered:
            return result

        # Determine debate parameters from matched rule
        rule = self._find_rule(result.rule_matched)
        rounds = rule.debate_rounds if rule else self._config.default_rounds
        consensus = rule.debate_consensus if rule else self._config.default_consensus
        agent_count = rule.debate_agent_count if rule else self._config.default_agent_count

        # Generate debate ID
        debate_id = f"inbox-{uuid.uuid4().hex[:12]}"
        result.debate_id = debate_id

        channel = message.get("channel", "unknown")
        message_id = message.get("message_id", "")
        sender = message.get("sender", "")

        # Build debate question from message
        question = self._build_debate_question(message)

        # Record rate limiting
        self._record_debate_spawn(channel)

        # Emit INBOX_ITEM_FLAGGED event
        self._emit_event(
            "inbox_item_flagged",
            {
                "message_id": message_id,
                "channel": channel,
                "sender": sender,
                "priority": message.get("priority", "normal"),
                "rule_matched": result.rule_matched,
                "reason": result.reason,
            },
        )

        # Track active debate
        self._active_debates[debate_id] = {
            "debate_id": debate_id,
            "message_id": message_id,
            "channel": channel,
            "sender": sender,
            "question": question,
            "rule_matched": result.rule_matched,
            "started_at": time.time(),
        }

        # Register debate origin for result routing
        self._register_origin(
            debate_id=debate_id,
            channel=channel,
            sender=sender,
            message_id=message_id,
            metadata=message.get("metadata", {}),
        )

        # Spawn debate in background
        asyncio.ensure_future(
            self._run_debate(
                debate_id=debate_id,
                question=question,
                rounds=rounds,
                consensus=consensus,
                agent_count=agent_count,
                channel=channel,
                message_id=message_id,
            )
        )

        # Emit INBOX_DEBATE_TRIGGERED event
        self._emit_event(
            "inbox_debate_triggered",
            {
                "debate_id": debate_id,
                "message_id": message_id,
                "channel": channel,
                "question": question[:500],
                "rule_matched": result.rule_matched,
                "rounds": rounds,
                "consensus": consensus,
            },
        )

        self._stats["debates_triggered"] += 1
        logger.info(
            "Auto-debate spawned: debate_id=%s channel=%s rule=%s",
            debate_id,
            channel,
            result.rule_matched,
        )

        return result

    def _find_rule(self, rule_name: str | None) -> TriggerRule | None:
        """Find a trigger rule by name."""
        if not rule_name:
            return None
        for rule in self._config.rules:
            if rule.name == rule_name:
                return rule
        return None

    def _build_debate_question(self, message: dict[str, Any]) -> str:
        """Build a debate question from an inbox message.

        Constructs a concise question that captures the essence of the
        incoming message for multi-agent debate.

        Args:
            message: Message data dict

        Returns:
            Formatted debate question string
        """
        subject = message.get("subject", "").strip()
        content = message.get("content", "").strip()
        channel = message.get("channel", "unknown")
        sender = message.get("sender", "unknown")

        parts = []

        if subject:
            parts.append(f"Subject: {subject}")

        if content:
            # Truncate very long messages
            truncated = content[:2000]
            if len(content) > 2000:
                truncated += "..."
            parts.append(truncated)

        body = "\n".join(parts) if parts else "No content provided"

        question = (
            f"An incoming message from {channel} (sender: {sender}) requires "
            f"a multi-perspective analysis and decision. "
            f"Please analyze the following and provide a recommendation:\n\n"
            f"{body}"
        )

        return question

    def _register_origin(
        self,
        debate_id: str,
        channel: str,
        sender: str,
        message_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register the debate origin for result routing.

        Uses the existing debate_origin registry to enable routing
        the debate result back to the originating channel.
        """
        try:
            from aragora.server.debate_origin.registry import register_debate_origin

            register_debate_origin(
                debate_id=debate_id,
                platform=channel,
                channel_id=channel,
                user_id=sender,
                message_id=message_id,
                metadata={
                    **(metadata or {}),
                    "source": "inbox_debate_router",
                    "auto_spawned": True,
                },
            )
        except ImportError:
            logger.debug("debate_origin module not available for origin registration")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Failed to register debate origin: %s", e)

    async def _run_debate(
        self,
        debate_id: str,
        question: str,
        rounds: int,
        consensus: str,
        agent_count: int,
        channel: str,
        message_id: str,
    ) -> None:
        """Run a debate in the background and handle completion.

        Creates an Arena, runs the debate, and routes the result back
        to the originating channel.

        Args:
            debate_id: Unique debate identifier
            question: Debate question
            rounds: Number of debate rounds
            consensus: Consensus type
            agent_count: Number of agents
            channel: Originating channel
            message_id: Original message ID
        """
        try:
            from aragora.core import Environment
            from aragora.debate.protocol import DebateProtocol
            from aragora.debate.orchestrator import Arena

            env = Environment(task=question)
            protocol = DebateProtocol(rounds=rounds, consensus=consensus)

            # Use default agents (Arena will auto-select)
            arena = Arena(env, agents=[], protocol=protocol)
            result = await arena.run()

            # Emit completion event
            self._emit_event(
                "inbox_debate_completed",
                {
                    "debate_id": debate_id,
                    "message_id": message_id,
                    "channel": channel,
                    "consensus_reached": getattr(result, "consensus_reached", False),
                    "final_answer": getattr(result, "final_answer", "")[:1000],
                    "confidence": getattr(result, "confidence", 0.0),
                    "rounds_used": getattr(result, "rounds_used", 0),
                },
            )

            # Route result back to originating channel
            await self._route_result(debate_id, result)

            self._stats["debates_completed"] += 1
            logger.info("Inbox debate completed: %s", debate_id)

        except ImportError as e:
            logger.warning("Debate engine not available: %s", e)
            self._stats["debates_failed"] += 1
        except (RuntimeError, OSError, ValueError, TypeError, asyncio.CancelledError) as e:
            logger.error("Inbox debate failed: debate_id=%s error=%s", debate_id, e)
            self._stats["debates_failed"] += 1
        finally:
            # Clean up active debate tracking
            self._active_debates.pop(debate_id, None)

    async def _route_result(self, debate_id: str, result: Any) -> None:
        """Route the debate result back to the originating channel.

        Args:
            debate_id: Debate identifier
            result: DebateResult from the Arena
        """
        try:
            from aragora.server.result_router import route_result

            # Convert result to dict
            if hasattr(result, "to_dict"):
                result_dict = result.to_dict()
            elif hasattr(result, "__dict__"):
                result_dict = {
                    "debate_id": debate_id,
                    "consensus_reached": getattr(result, "consensus_reached", False),
                    "final_answer": getattr(result, "final_answer", ""),
                    "confidence": getattr(result, "confidence", 0.0),
                    "participants": getattr(result, "participants", []),
                    "task": getattr(result, "task", ""),
                }
            else:
                result_dict = {"debate_id": debate_id}

            success = await route_result(debate_id, result_dict)
            if success:
                logger.info("Debate result routed to origin: %s", debate_id)
            else:
                logger.debug("No origin found for debate result routing: %s", debate_id)

        except ImportError:
            logger.debug("Result router not available")
        except (RuntimeError, OSError, ValueError) as e:
            logger.warning("Failed to route debate result: %s", e)

    def _emit_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event through the event bus.

        Args:
            event_type: Event type string
            data: Event data payload
        """
        if self._event_bus is not None:
            try:
                if asyncio.iscoroutinefunction(getattr(self._event_bus, "emit", None)):
                    try:
                        loop = asyncio.get_running_loop()
                        loop.create_task(self._event_bus.emit(event_type, **data))
                    except RuntimeError:
                        pass
                else:
                    self._event_bus.emit(event_type, **data)
            except (TypeError, AttributeError, RuntimeError) as e:
                logger.debug("Event emission failed: %s", e)

        # Also dispatch through the webhook dispatcher
        try:
            from aragora.events.dispatcher import dispatch_event

            dispatch_event(event_type, data)
        except ImportError:
            pass
        except (RuntimeError, OSError, ValueError) as e:
            logger.debug("Webhook event dispatch failed: %s", e)

    # -----------------------------------------------------------------
    # Event subscription
    # -----------------------------------------------------------------

    async def on_message_received(self, event: Any) -> None:
        """Handle an incoming connector message event.

        Extracts message data from the event payload and evaluates it.
        If the message triggers a rule, a debate is spawned.

        This method is designed to be subscribed to the event dispatcher
        so that connector message events are automatically routed here.

        Args:
            event: Event object or dict with ``data`` containing message fields
                   (``message_id``, ``channel``, ``sender``, ``content``,
                   ``subject``, ``priority``, ``metadata``).
        """
        if not self._running:
            return

        # Normalize: accept both StreamEvent objects and plain dicts
        if hasattr(event, "data"):
            data = event.data if isinstance(event.data, dict) else {}
        elif isinstance(event, dict):
            data = event.get("data", event)
        else:
            logger.debug("on_message_received: unrecognized event type %s", type(event))
            return

        # Build message dict from event data
        message: dict[str, Any] = {
            "message_id": data.get("message_id", ""),
            "channel": data.get("channel", data.get("platform", "")),
            "sender": data.get("sender", data.get("user_id", "")),
            "content": data.get("content", data.get("text", data.get("body", ""))),
            "subject": data.get("subject", ""),
            "priority": data.get("priority", "normal"),
            "metadata": data.get("metadata", {}),
        }

        if not message["content"] and not message["subject"]:
            return

        try:
            await self.spawn_debate(message)
        except (RuntimeError, OSError, ValueError, TypeError) as exc:
            logger.warning("on_message_received: spawn_debate failed: %s", exc)

    # -----------------------------------------------------------------
    # Rule management
    # -----------------------------------------------------------------

    def add_rule(self, rule: TriggerRule) -> None:
        """Add a trigger rule to the configuration.

        Args:
            rule: TriggerRule to add
        """
        self._config.rules.append(rule)
        logger.info("Added trigger rule: %s", rule.name)

    def remove_rule(self, rule_id: str) -> bool:
        """Remove a trigger rule by ID.

        Args:
            rule_id: ID of the rule to remove

        Returns:
            True if a rule was removed
        """
        before = len(self._config.rules)
        self._config.rules = [r for r in self._config.rules if r.id != rule_id]
        removed = len(self._config.rules) < before
        if removed:
            logger.info("Removed trigger rule: %s", rule_id)
        return removed

    def list_rules(self) -> list[dict[str, Any]]:
        """List all configured trigger rules.

        Returns:
            List of rule dictionaries
        """
        return [r.to_dict() for r in self._config.rules]

    def get_active_debates(self) -> list[dict[str, Any]]:
        """Get currently active debates spawned by this router.

        Returns:
            List of active debate info dicts
        """
        return list(self._active_debates.values())

    def reset_stats(self) -> None:
        """Reset all statistics counters."""
        self._stats = {
            "messages_evaluated": 0,
            "debates_triggered": 0,
            "debates_completed": 0,
            "debates_failed": 0,
            "messages_skipped": 0,
            "rate_limited": 0,
        }


# ---------------------------------------------------------------------------
# Global instance
# ---------------------------------------------------------------------------

_router: InboxDebateRouter | None = None


def get_inbox_debate_router(config: RouterConfig | None = None) -> InboxDebateRouter:
    """Get or create the global InboxDebateRouter.

    Args:
        config: Optional configuration. Only used when creating a new instance.

    Returns:
        The global InboxDebateRouter instance
    """
    global _router
    if _router is None:
        _router = InboxDebateRouter(config=config)
    return _router


def reset_inbox_debate_router() -> None:
    """Reset the global InboxDebateRouter (for testing)."""
    global _router
    _router = None


__all__ = [
    "InboxDebateRouter",
    "RouterConfig",
    "TriggerRule",
    "DebateSpawnResult",
    "PriorityLevel",
    "get_inbox_debate_router",
    "reset_inbox_debate_router",
]
