"""
Human Intervention Breakpoints.

Provides structured mechanics for human oversight in debates:
- Automatic breakpoints on low confidence or deadlocks
- Explicit appeal-to-human mechanics
- Integration with CLI/Slack/Discord for notifications
- Human guidance injection into debates
"""

import asyncio
import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class BreakpointTrigger(Enum):
    """Triggers for breakpoints."""

    LOW_CONFIDENCE = "low_confidence"  # Confidence below threshold
    DEADLOCK = "deadlock"  # No progress for N rounds
    HIGH_DISAGREEMENT = "high_disagreement"  # Agents fundamentally disagree
    CRITICAL_DECISION = "critical_decision"  # Explicit marker for important decision
    EXPLICIT_APPEAL = "explicit_appeal"  # Agent explicitly requests human input
    ROUND_LIMIT = "round_limit"  # Maximum rounds reached without consensus
    SAFETY_CONCERN = "safety_concern"  # Potential safety issue detected
    HOLLOW_CONSENSUS = "hollow_consensus"  # Evidence-Powered Trickster: agreement without substance
    CUSTOM = "custom"  # Custom trigger condition


@dataclass
class DebateSnapshot:
    """Snapshot of debate state for human review."""

    debate_id: str
    task: str
    current_round: int
    total_rounds: int

    # Current state
    latest_messages: list[dict]  # Last few messages
    active_proposals: list[str]
    open_critiques: list[str]
    current_consensus: str | None
    confidence: float

    # Context
    agent_positions: dict[str, str]  # Agent name -> their current position
    unresolved_issues: list[str]
    key_disagreements: list[str]

    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class HumanGuidance:
    """Guidance from a human reviewer."""

    guidance_id: str
    debate_id: str
    human_id: str

    # Decision
    action: str  # "continue", "resolve", "redirect", "abort"

    # Guidance content
    decision: str | None = None  # Direct decision if resolving
    hints: list[str] = field(default_factory=list)  # Hints for agents
    constraints: list[str] = field(default_factory=list)  # New constraints to apply
    preferred_direction: str | None = None  # Which approach to favor

    # For appeals
    answers: dict[str, str] = field(default_factory=dict)  # Answers to specific questions

    # Metadata
    reasoning: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class Breakpoint:
    """A breakpoint in the debate."""

    breakpoint_id: str
    trigger: BreakpointTrigger
    triggered_at: str
    debate_snapshot: DebateSnapshot

    # Resolution
    resolved: bool = False
    guidance: HumanGuidance | None = None
    resolved_at: str | None = None

    # Escalation
    escalation_level: int = 1  # 1-3, higher = more urgent
    timeout_minutes: int = 30  # How long to wait for human


@dataclass
class BreakpointConfig:
    """Configuration for when to trigger breakpoints."""

    # Thresholds
    min_confidence: float = 0.6  # Break if confidence drops below
    max_deadlock_rounds: int = 3  # Break after N rounds without progress
    max_total_rounds: int = 10  # Break if debate goes too long
    disagreement_threshold: float = 0.7  # Break on high disagreement

    # Behavior
    require_human_for_critical: bool = True
    auto_timeout_action: str = "continue"  # What to do if human doesn't respond
    notification_channels: list[str] = field(default_factory=list)  # ["cli", "slack", "discord"]

    # Safety
    safety_keywords: list[str] = field(
        default_factory=lambda: ["dangerous", "harmful", "illegal", "unethical", "unsafe"]
    )


class HumanNotifier:
    """
    Handles notifications to humans about breakpoints.

    Supports multiple channels: CLI, Slack, Discord, etc.
    """

    def __init__(self, config: BreakpointConfig):
        self.config = config
        self._handlers: dict[str, Callable] = {}

    def register_handler(self, channel: str, handler: Callable) -> None:
        """Register a notification handler for a channel."""
        self._handlers[channel] = handler

    async def notify(self, breakpoint: Breakpoint) -> bool:
        """Send notification about a breakpoint."""
        success = False

        for channel in self.config.notification_channels:
            if channel in self._handlers:
                try:
                    await self._handlers[channel](breakpoint)
                    success = True
                except Exception as e:  # noqa: BLE001 - notification channels are best-effort
                    logger.warning(
                        "Notification handler '%s' failed: %s: %s", channel, type(e).__name__, e
                    )
                    continue

        # Fallback to CLI if no handlers
        if not success:
            self._cli_notify(breakpoint)
            success = True

        return success

    def _cli_notify(self, breakpoint: Breakpoint):
        """Log notification to CLI."""
        snapshot = breakpoint.debate_snapshot
        logger.info("=" * 60)
        logger.info("BREAKPOINT TRIGGERED: %s", breakpoint.trigger.value)
        logger.info("=" * 60)
        logger.info("Debate: %s", snapshot.debate_id)
        logger.info("Task: %s...", snapshot.task[:100])
        logger.info("Round: %s/%s", snapshot.current_round, snapshot.total_rounds)
        logger.info("Confidence: %.0f%%", snapshot.confidence * 100)

        if snapshot.key_disagreements:
            logger.info("Key disagreements:")
            for d in snapshot.key_disagreements[:3]:
                logger.info("  - %s", d)

        logger.info("Agent positions:")
        for agent, position in snapshot.agent_positions.items():
            logger.info("  %s: %s...", agent, position[:80])

        logger.info("Escalation level: %s", breakpoint.escalation_level)
        logger.info("Timeout: %s minutes", breakpoint.timeout_minutes)
        logger.info("=" * 60)


class BreakpointManager:
    """
    Manages breakpoints during debates.

    Monitors debate state and triggers human intervention when needed.
    """

    def __init__(
        self,
        config: BreakpointConfig | None = None,
        get_human_input: Callable[[Breakpoint], Awaitable[HumanGuidance]] | None = None,
        event_emitter: Any | None = None,
        loop_id: str | None = None,
    ):
        self.config = config or BreakpointConfig()
        self.get_human_input = get_human_input or self._default_human_input
        self.notifier = HumanNotifier(self.config)
        self.event_emitter = event_emitter
        self.loop_id = loop_id

        self.breakpoints: list[Breakpoint] = []
        self._breakpoint_counter = 0

    def check_triggers(
        self,
        debate_id: str,
        task: str,
        messages: list[Any],
        confidence: float,
        round_num: int,
        max_rounds: int,
        critiques: list[Any] | None = None,
    ) -> Breakpoint | None:
        """Check if any breakpoint should trigger."""

        # Low confidence
        if confidence < self.config.min_confidence:
            return self._create_breakpoint(
                BreakpointTrigger.LOW_CONFIDENCE,
                debate_id,
                task,
                messages,
                confidence,
                round_num,
                max_rounds,
            )

        # Deadlock detection - check if last N rounds had similar content
        if round_num >= self.config.max_deadlock_rounds:
            if self._detect_deadlock(messages, self.config.max_deadlock_rounds):
                return self._create_breakpoint(
                    BreakpointTrigger.DEADLOCK,
                    debate_id,
                    task,
                    messages,
                    confidence,
                    round_num,
                    max_rounds,
                )

        # Round limit
        if round_num >= max_rounds:
            return self._create_breakpoint(
                BreakpointTrigger.ROUND_LIMIT,
                debate_id,
                task,
                messages,
                confidence,
                round_num,
                max_rounds,
            )

        # High disagreement from critiques
        if critiques:
            avg_severity = sum(c.severity for c in critiques) / len(critiques)
            if avg_severity > self.config.disagreement_threshold:
                return self._create_breakpoint(
                    BreakpointTrigger.HIGH_DISAGREEMENT,
                    debate_id,
                    task,
                    messages,
                    confidence,
                    round_num,
                    max_rounds,
                )

        # Safety concerns
        all_content = " ".join(m.content.lower() for m in messages if hasattr(m, "content"))
        for keyword in self.config.safety_keywords:
            if keyword in all_content:
                return self._create_breakpoint(
                    BreakpointTrigger.SAFETY_CONCERN,
                    debate_id,
                    task,
                    messages,
                    confidence,
                    round_num,
                    max_rounds,
                    escalation=3,  # High priority
                )

        return None

    def _detect_deadlock(self, messages: list[Any], lookback: int) -> bool:
        """Detect if debate is stuck in a loop."""
        if len(messages) < lookback * 2:
            return False

        # Get recent messages
        recent = messages[-lookback:]
        earlier = messages[-lookback * 2 : -lookback]

        # Simple check: are agents repeating themselves?
        recent_content = set()
        for m in recent:
            if hasattr(m, "content"):
                # Normalize and take first 100 chars
                normalized = m.content.lower().strip()[:100]
                recent_content.add(normalized)

        earlier_content = set()
        for m in earlier:
            if hasattr(m, "content"):
                normalized = m.content.lower().strip()[:100]
                earlier_content.add(normalized)

        # If high overlap, likely deadlocked
        overlap = len(recent_content & earlier_content) / max(len(recent_content), 1)
        return overlap > 0.5

    def _create_breakpoint(
        self,
        trigger: BreakpointTrigger,
        debate_id: str,
        task: str,
        messages: list[Any],
        confidence: float,
        round_num: int,
        max_rounds: int,
        escalation: int = 1,
    ) -> Breakpoint:
        """Create a breakpoint with current debate snapshot."""
        self._breakpoint_counter += 1

        def _truncate_message_content(message: Any, limit: int) -> str:
            content = getattr(message, "content", "")
            if content is None:
                return ""
            if not isinstance(content, str):
                content = str(content)
            return content[:limit]

        # Build snapshot
        latest = messages[-5:] if len(messages) >= 5 else messages
        latest_dicts = [
            {
                "agent": m.agent,
                "content": _truncate_message_content(m, 200),
                "round": getattr(m, "round", 0),
            }
            for m in latest
            if hasattr(m, "agent")
        ]

        # Extract agent positions
        positions = {}
        for m in reversed(messages):
            if hasattr(m, "agent") and m.agent not in positions:
                positions[m.agent] = _truncate_message_content(m, 150)

        snapshot = DebateSnapshot(
            debate_id=debate_id,
            task=task,
            current_round=round_num,
            total_rounds=max_rounds,
            latest_messages=latest_dicts,
            active_proposals=[],
            open_critiques=[],
            current_consensus=None,
            confidence=confidence,
            agent_positions=positions,
            unresolved_issues=[],
            key_disagreements=[],
        )

        breakpoint = Breakpoint(
            breakpoint_id=f"bp-{debate_id}-{self._breakpoint_counter}",
            trigger=trigger,
            triggered_at=datetime.now().isoformat(),
            debate_snapshot=snapshot,
            escalation_level=escalation,
        )

        self.breakpoints.append(breakpoint)

        # Emit WebSocket event
        self._emit_breakpoint_event(breakpoint)

        return breakpoint

    def _emit_breakpoint_event(self, breakpoint: Breakpoint) -> None:
        """Emit BREAKPOINT event to WebSocket clients."""
        if not self.event_emitter:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            snapshot = breakpoint.debate_snapshot
            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.BREAKPOINT,
                    loop_id=self.loop_id or "",
                    data={
                        "breakpoint_id": breakpoint.breakpoint_id,
                        "trigger": breakpoint.trigger.value,
                        "debate_id": snapshot.debate_id,
                        "task": snapshot.task[:200],
                        "round": snapshot.current_round,
                        "confidence": snapshot.confidence,
                        "escalation_level": breakpoint.escalation_level,
                        "timeout_minutes": breakpoint.timeout_minutes,
                        "agent_positions": snapshot.agent_positions,
                        "key_disagreements": snapshot.key_disagreements,
                        "triggered_at": breakpoint.triggered_at,
                    },
                )
            )
            logger.info("Emitted BREAKPOINT event for %s", breakpoint.breakpoint_id)
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.warning("Failed to emit breakpoint event: %s", e)

    async def handle_breakpoint(self, breakpoint: Breakpoint) -> HumanGuidance:
        """Handle a breakpoint by getting human input."""
        # Notify human
        await self.notifier.notify(breakpoint)

        # Get human input (with timeout)
        try:
            guidance = await asyncio.wait_for(
                self.get_human_input(breakpoint),
                timeout=breakpoint.timeout_minutes * 60,
            )
        except asyncio.TimeoutError:
            # Use default action
            guidance = HumanGuidance(
                guidance_id=f"auto-{breakpoint.breakpoint_id}",
                debate_id=breakpoint.debate_snapshot.debate_id,
                human_id="system",
                action=self.config.auto_timeout_action,
                reasoning="Human input timeout - using default action",
            )

        # Mark as resolved
        breakpoint.resolved = True
        breakpoint.guidance = guidance
        breakpoint.resolved_at = datetime.now().isoformat()

        # Emit WebSocket event
        self._emit_breakpoint_resolved_event(breakpoint)

        return guidance

    async def _default_human_input(self, breakpoint: Breakpoint) -> HumanGuidance:
        """Default handler that prompts on CLI.

        Note: Uses stdout for interactive CLI prompts. For non-CLI contexts,
        override this method or use a custom human_input_handler.
        """
        snapshot = breakpoint.debate_snapshot
        logger.debug("Prompting for human input on breakpoint %s", breakpoint.breakpoint_id)

        menu = """
----------------------------------------
How would you like to proceed?
1. continue - Let agents continue debating
2. resolve - Provide your decision
3. redirect - Give hints to agents
4. abort - Stop the debate
----------------------------------------"""
        sys.stdout.write(f"{menu}\n")

        try:
            choice = input("Enter choice (1-4): ").strip()
        except EOFError:
            choice = "1"

        action_map = {"1": "continue", "2": "resolve", "3": "redirect", "4": "abort"}
        action = action_map.get(choice, "continue")

        guidance = HumanGuidance(
            guidance_id=f"human-{breakpoint.breakpoint_id}",
            debate_id=snapshot.debate_id,
            human_id="cli_user",
            action=action,
        )

        if action == "resolve":
            try:
                guidance.decision = input("Enter your decision: ").strip()
            except EOFError:
                guidance.action = "continue"

        elif action == "redirect":
            try:
                hint = input("Enter hint for agents: ").strip()
                guidance.hints = [hint] if hint else []
            except EOFError:
                guidance.action = "continue"

        return guidance

    def get_pending_breakpoints(self) -> list[Breakpoint]:
        """Get all unresolved breakpoints."""
        return [bp for bp in self.breakpoints if not bp.resolved]

    def get_breakpoint(self, breakpoint_id: str) -> Breakpoint | None:
        """Get a specific breakpoint by ID."""
        for bp in self.breakpoints:
            if bp.breakpoint_id == breakpoint_id:
                return bp
        return None

    def resolve_breakpoint(self, breakpoint_id: str, guidance: HumanGuidance) -> bool:
        """
        Resolve a pending breakpoint with human guidance.

        Args:
            breakpoint_id: ID of the breakpoint to resolve
            guidance: Human guidance for resolution

        Returns:
            True if resolved successfully, False if breakpoint not found
        """
        bp = self.get_breakpoint(breakpoint_id)
        if not bp:
            return False

        if bp.resolved:
            logger.warning("Breakpoint %s already resolved", breakpoint_id)
            return False

        bp.resolved = True
        bp.guidance = guidance
        bp.resolved_at = datetime.now().isoformat()

        # Emit WebSocket event
        self._emit_breakpoint_resolved_event(bp)

        logger.info("Breakpoint %s resolved with action: %s", breakpoint_id, guidance.action)
        return True

    def _emit_breakpoint_resolved_event(self, breakpoint: Breakpoint) -> None:
        """Emit BREAKPOINT_RESOLVED event to WebSocket clients."""
        if not self.event_emitter or not breakpoint.guidance:
            return

        try:
            from aragora.events.types import StreamEvent, StreamEventType

            guidance = breakpoint.guidance
            self.event_emitter.emit(
                StreamEvent(
                    type=StreamEventType.BREAKPOINT_RESOLVED,
                    loop_id=self.loop_id or "",
                    data={
                        "breakpoint_id": breakpoint.breakpoint_id,
                        "trigger": breakpoint.trigger.value,
                        "debate_id": breakpoint.debate_snapshot.debate_id,
                        "action": guidance.action,
                        "decision": guidance.decision,
                        "hints": guidance.hints,
                        "constraints": guidance.constraints,
                        "human_id": guidance.human_id,
                        "reasoning": guidance.reasoning[:200] if guidance.reasoning else "",
                        "resolved_at": breakpoint.resolved_at,
                    },
                )
            )
            logger.info("Emitted BREAKPOINT_RESOLVED event for %s", breakpoint.breakpoint_id)
        except (RuntimeError, ValueError, TypeError, AttributeError, OSError) as e:
            logger.warning("Failed to emit breakpoint resolved event: %s", e)

    def inject_guidance(
        self,
        guidance: HumanGuidance,
        messages: list[Any],
        environment: Any,
    ) -> tuple[list[Any], Any]:
        """Inject human guidance into the debate state."""
        from aragora.core import Message

        if guidance.action == "resolve":
            # Add human decision as final message
            human_msg = Message(
                agent="human",
                role="judge",
                content=f"[HUMAN DECISION]\n\n{guidance.decision}",
                round=len(set(m.round for m in messages)) + 1,
            )
            messages.append(human_msg)

        elif guidance.action == "redirect":
            # Add hints as system message
            hints_text = "\n".join(f"- {h}" for h in guidance.hints)
            hint_msg = Message(
                agent="human",
                role="moderator",
                content=f"[HUMAN GUIDANCE]\n\nConsider the following:\n{hints_text}",
                round=len(set(m.round for m in messages)),
            )
            messages.append(hint_msg)

            # Add constraints to environment
            if guidance.constraints and hasattr(environment, "constraints"):
                environment.constraints.extend(guidance.constraints)

        return messages, environment


# Decorator for marking critical decision points
def critical_decision(reason: str = "") -> Callable[[Callable], Callable]:
    """Decorator to mark a debate point as requiring human review."""

    def decorator(func: Callable) -> Callable:
        setattr(func, "_aragora_critical", True)
        setattr(func, "_aragora_critical_reason", reason)
        return func

    return decorator


# Example usage helper
def breakpoint(
    trigger: str = "low_confidence",
    threshold: float = 0.6,
    message: str = "",
) -> Callable[[Callable], Callable]:
    """
    Mark a breakpoint condition in debate flow.

    Usage:
        @debate.breakpoint(trigger="confidence < 0.6 OR deadlock_rounds > 3")
        async def human_tiebreaker(state: DebateState) -> Guidance:
            return await get_human_input(state.summary, state.open_questions)
    """

    def decorator(func: Callable) -> Callable:
        setattr(func, "_aragora_breakpoint", True)
        setattr(func, "_aragora_breakpoint_trigger", trigger)
        setattr(func, "_aragora_breakpoint_threshold", threshold)
        setattr(func, "_aragora_breakpoint_message", message)
        return func

    return decorator
