"""
Cross-Subscriber Manager.

Core CrossSubscriberManager class that orchestrates event dispatch
and subscriber lifecycle management.

The heavy lifting is delegated to specialized mixins:
- DispatchMixin: Event dispatch, batching, retry, circuit breaker, metrics
- AdminMixin: Stats reporting, enable/disable, sampling, filtering, retry config

The remaining built-in handlers (RLM feedback, cost/explainability tracking,
culture patterns, risk/genesis feedback loops) are domain-free and defined
directly below rather than via mixin.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol
from collections.abc import Callable

from aragora.events.subscribers.config import (
    AsyncDispatchConfig,
    RetryConfig,
    SubscriberStats,
)
from aragora.events.types import StreamEvent, StreamEventType
from aragora.resilience import CircuitBreaker

from .admin import AdminMixin
from .dispatch import CrossSubscriberHandler, DispatchMixin
from .registry import get_registered_subscribers

if TYPE_CHECKING:
    from aragora.config.settings import Settings

# Import settings for feature flags
try:
    from aragora.config.settings import get_settings as _get_settings

    SETTINGS_AVAILABLE = True

    def get_settings() -> Settings | None:
        """Get settings instance (wrapper for type safety)."""
        return _get_settings()

except ImportError:
    SETTINGS_AVAILABLE = False

    def get_settings() -> Settings | None:
        """Fallback when settings module not available."""
        return None


logger = logging.getLogger(__name__)


class CompressorProtocol(Protocol):
    """Protocol for RLM compressor with access pattern recording."""

    def record_access_pattern(
        self,
        tier: str,
        cache_hit: bool,
        importance: float,
    ) -> None:
        """Record a memory access pattern for compression optimization."""
        ...


class CrossSubscriberManager(
    DispatchMixin,
    AdminMixin,
):
    """
    Manages cross-subsystem event subscribers.

    Provides a central point for registering and managing subscribers
    that react to events from different subsystems.

    Example:
        manager = CrossSubscriberManager()

        # Register custom subscriber
        @manager.subscribe(StreamEventType.MEMORY_STORED)
        def on_memory_stored(event: StreamEvent):
            # Handle memory storage event
            pass

        # Connect to event stream
        manager.connect(event_emitter)
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
        default_retry_config: RetryConfig | None = None,
        async_config: AsyncDispatchConfig | None = None,
    ):
        """Initialize the cross-subscriber manager.

        Args:
            failure_threshold: Consecutive failures before circuit opens (default: 5)
            cooldown_seconds: Seconds before attempting recovery (default: 60)
            default_retry_config: Default retry configuration for handlers (default: 3 retries)
            async_config: Configuration for async/batched event dispatch
        """
        self._subscribers: dict[StreamEventType, list[tuple[str, CrossSubscriberHandler]]] = {}
        self._stats: dict[str, SubscriberStats] = {}
        self._filters: dict[str, Callable[[StreamEvent], bool]] = {}
        self._connected = False

        # Default retry configuration
        self._default_retry_config = default_retry_config or RetryConfig()

        # Cache settings reference for feature flags and batch config
        self._settings = get_settings() if SETTINGS_AVAILABLE else None

        # Async dispatch configuration (use settings if available)
        if async_config is not None:
            self._async_config = async_config
        else:
            self._async_config = self._create_async_config_from_settings()

        # Event batch queue for high-volume events
        self._event_batch: dict[StreamEventType, list[StreamEvent]] = {}
        self._batch_last_flush: float = 0.0

        # Circuit breaker for handler failure protection
        self._circuit_breaker = CircuitBreaker(
            failure_threshold=failure_threshold,
            cooldown_seconds=cooldown_seconds,
        )

        # Registry subscribers already wired into this manager instance
        self._applied_subscribers: set[str] = set()

        # Register built-in cross-subsystem handlers
        self._register_builtin_subscribers()

        # Registry subscribers are wired only by explicit layered bootstraps.
        # Direct construction stays infrastructure-only, so relocated domain
        # reactions cannot appear or disappear based on prior import order.

    def apply_registered_subscribers(self, *, include_names: set[str] | None = None) -> int:
        """Wire registry subscribers not yet applied into this manager.

        Home modules (domain/application/interface) self-register their
        subscribers via ``aragora.events.cross_subscribers.register_subscriber``;
        this applies them by delegating to each subscriber's ``register`` method,
        reusing the existing per-event dispatch/stats/retry machinery. Idempotent:
        each subscriber is applied at most once per manager instance.

        Args:
            include_names: When given, only registers subscribers whose home
                name is in this set on THIS call; every other registered home
                is left un-applied here (a later call - with a wider or no
                filter - can still apply it). ``None`` (default) applies every
                currently-registered home, the pre-existing behavior. This is
                what lets a subset bootstrap (e.g. domain-only) stay narrow
                even when an unrelated import has already populated the
                process-wide registry with a wider-tier home's subscriber -
                the registry itself has no tier concept, so without this the
                subset would silently inherit whatever happened to be
                registered first.

        Returns:
            The number of subscribers newly applied by this call.
        """
        applied = 0
        for name, subscriber in get_registered_subscribers().items():
            if name in self._applied_subscribers:
                continue
            if include_names is not None and name not in include_names:
                continue
            subscriber.register(self)
            self._applied_subscribers.add(name)
            applied += 1
        return applied

    def _create_async_config_from_settings(self) -> AsyncDispatchConfig:
        """Create AsyncDispatchConfig from settings or use defaults.

        Returns:
            Configured AsyncDispatchConfig
        """
        if self._settings is None:
            return AsyncDispatchConfig()

        try:
            integration = self._settings.integration
            return AsyncDispatchConfig(
                batch_size=integration.event_batch_size,
                batch_timeout_seconds=integration.event_batch_timeout_seconds,
                enable_batching=integration.event_batching_enabled,
            )
        except (AttributeError, TypeError):
            return AsyncDispatchConfig()

    def _is_km_handler_enabled(self, handler_name: str) -> bool:
        """Check if a KM handler is enabled via feature flags.

        Args:
            handler_name: The handler name (e.g., 'memory_to_mound')

        Returns:
            True if enabled (default) or settings not available
        """
        if self._settings is None:
            return True  # Default to enabled if settings unavailable
        try:
            integration = self._settings.integration
            return integration.is_km_handler_enabled(handler_name)
        except (AttributeError, TypeError):
            return True  # Default to enabled on error

    def _handle_memory_to_rlm(self, event: StreamEvent) -> None:
        """
        Memory retrieval → RLM feedback.

        When memory is retrieved, inform RLM about retrieval patterns
        to optimize compression strategies. Tracks access patterns
        for adaptive compression.
        """
        data = event.data
        tier = data.get("tier", "unknown")
        hit = data.get("cache_hit", False)
        importance = data.get("importance", 0.5)

        # Track access pattern for RLM optimization
        logger.debug("Memory retrieval: tier=%s, cache_hit=%s", tier, hit)

        # Update RLM compression hints based on access patterns
        try:
            import aragora.rlm.compressor as compressor_module

            # get_compressor may not exist yet (planned feature)
            get_compressor = getattr(compressor_module, "get_compressor", None)
            if get_compressor is None:
                return

            compressor: CompressorProtocol | None = get_compressor()
            if compressor and hasattr(compressor, "record_access_pattern"):
                compressor.record_access_pattern(
                    tier=tier,
                    cache_hit=hit,
                    importance=importance,
                )
        except ImportError:
            pass  # RLM module not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("RLM pattern recording failed: %s", e)

    def _handle_debate_end_to_cost_tracking(self, event: StreamEvent) -> None:
        """Debate end → Cost tracking record.

        When a debate ends, record the total cost for billing
        and usage analytics.
        """
        data = event.data
        debate_id = data.get("debate_id", "")
        total_cost = data.get("total_cost", 0.0)
        total_tokens = data.get("total_tokens", 0)

        if not total_cost:
            return

        logger.debug(f"Recording debate cost: {debate_id} ${total_cost:.4f}")

        try:
            from aragora.billing.cost_tracker import get_cost_tracker

            tracker = get_cost_tracker()
            if tracker and hasattr(tracker, "record_debate_total"):
                tracker.record_debate_total(
                    debate_id=debate_id,
                    total_cost=total_cost,
                    total_tokens=total_tokens,
                )
        except ImportError:
            pass  # CostTracker not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Cost tracking record failed: %s", e)

    def _handle_debate_end_to_explainability(self, event: StreamEvent) -> None:
        """Debate end → Explainability auto-trigger.

        When a debate ends, log the event for downstream explainability
        processing. The actual explanation generation happens in
        ArenaExtensions._auto_generate_explanation.
        """
        data = event.data
        debate_id = data.get("debate_id", "")
        consensus = data.get("consensus_reached", False)
        confidence = data.get("confidence", 0.0)

        logger.debug(
            f"Debate ended for explainability: {debate_id} "
            f"consensus={consensus} confidence={confidence:.2f}"
        )

    def _handle_culture_to_debate(self, event: StreamEvent) -> None:
        """
        Culture patterns updated → Debate protocol.

        When culture patterns emerge, inform debate protocol selection.
        Only handles MOUND_UPDATED events with type=culture_patterns.
        """
        if not self._is_km_handler_enabled("culture_to_debate"):
            return

        data = event.data
        update_type = data.get("update_type", "")

        if update_type != "culture_patterns":
            return

        patterns_count = data.get("patterns_count", 0)
        workspace_id = data.get("workspace_id", "")

        logger.debug(
            f"Culture patterns available: {patterns_count} patterns in workspace {workspace_id}"
        )

        # Culture patterns are used passively during debate initialization
        # by querying the CultureAccumulator

    def _handle_risk_warning_to_health(self, event: StreamEvent) -> None:
        """Risk warning → Health registry degradation.

        When a security anomaly or domain risk is detected, record it
        in the health registry so that affected components are marked
        as degraded. This prevents compromised agents from being
        selected for future debates.
        """
        data = event.data
        risk_type = data.get("risk_type", "unknown")
        severity = data.get("severity", "low")
        component = data.get("component", data.get("agent", ""))
        description = data.get("description", "")[:200]

        if not component:
            return

        # Only degrade health for medium+ severity
        if severity in ("info", "low"):
            return

        logger.info(
            "Risk warning → health degradation: component=%s severity=%s type=%s",
            component,
            severity,
            risk_type,
        )

        try:
            from aragora.resilience.health import get_global_health_registry

            registry = get_global_health_registry()

            # get_or_create ensures the checker exists
            checker = registry.get_or_create(component)
            checker.record_failure(
                error=f"[{risk_type}] {description}",
            )
            logger.debug(
                "Recorded health degradation for %s from risk warning",
                component,
            )
        except ImportError:
            pass  # Health registry not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Health degradation from risk warning failed: %s", e)

    def _handle_genesis_to_control_plane(self, event: StreamEvent) -> None:
        """Agent birth/death/evolution → Control plane registry sync.

        When the genesis system creates, retires, or mutates an agent,
        update the control plane's agent registry so it reflects the
        current population. This ensures the control plane doesn't
        route tasks to dead agents or miss newly born ones.
        """
        data = event.data
        event_subtype = data.get("event_type", data.get("type", ""))
        agent_id = data.get("agent_id", data.get("genome_id", ""))

        if not agent_id:
            return

        logger.debug(
            "Genesis → control plane: event=%s agent=%s",
            event_subtype,
            agent_id,
        )

        try:
            from aragora.control_plane.registry import AgentRegistry

            import asyncio

            registry = AgentRegistry()

            if event_subtype in ("birth", "agent_birth"):
                capabilities = data.get("capabilities", [])
                agent_type = data.get("agent_type", "evolved")
                metadata = {"source": "genesis", "generation": data.get("generation", 0)}

                async def _register():
                    await registry.register(
                        agent_id=agent_id,
                        capabilities=capabilities,
                        model=agent_type,
                        metadata=metadata,
                    )

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_register())
                except RuntimeError:
                    pass  # No event loop; skip async registration
                logger.info("Scheduled born agent %s for control plane registration", agent_id)

            elif event_subtype in ("death", "agent_death"):

                async def _unregister():
                    await registry.unregister(agent_id)

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_unregister())
                except RuntimeError:
                    pass
                logger.info("Scheduled dead agent %s for control plane removal", agent_id)

            elif event_subtype in ("mutation", "evolution", "agent_evolution"):
                new_capabilities = data.get("capabilities", data.get("new_traits", []))

                async def _update():
                    await registry.register(
                        agent_id=agent_id,
                        capabilities=new_capabilities,
                        model=data.get("agent_type", "evolved"),
                        metadata={"evolved": True},
                    )

                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(_update())
                except RuntimeError:
                    pass
                logger.debug("Scheduled evolved agent %s for control plane update", agent_id)

        except ImportError:
            pass  # Control plane not available
        except (RuntimeError, TypeError, AttributeError, ValueError) as e:
            logger.debug("Genesis → control plane sync failed: %s", e)

    def _register_builtin_subscribers(self) -> None:
        """Register built-in cross-subsystem event handlers."""
        # Memory → RLM feedback
        self.register(
            "memory_to_rlm",
            StreamEventType.MEMORY_RETRIEVED,
            self._handle_memory_to_rlm,
        )

        # Agent ELO → Debate team selection relocated to
        # aragora.debate.event_subscribers (P4a Batch E4 relocate-UP); wired at
        # bootstrap via apply_registered_subscribers, not registered here.

        # Knowledge → Memory sync relocated to aragora.memory.event_subscribers
        # (P4a Batch E3 relocate-UP); wired at bootstrap via
        # apply_registered_subscribers, not registered here.

        # Calibration → Agent weights relocated to
        # aragora.debate.event_subscribers (P4a Batch E4 relocate-UP); wired at
        # bootstrap via apply_registered_subscribers, not registered here.

        # Evidence → Insight extraction and Mound structure → Memory/Debate sync
        # relocated to aragora.memory.event_subscribers (P4a Batch E3 relocate-UP);
        # wired at bootstrap via apply_registered_subscribers, not registered here.

        # Bidirectional Knowledge Mound reactions relocated to their domain home
        # (aragora.knowledge.event_subscribers, P4a E2 relocate-UP): they self-register
        # via that module and are wired by apply_registered_subscribers at bootstrap,
        # so events/ no longer imports knowledge here.

        # Phase 6: Culture → Debate (pattern updates)
        self.register(
            "culture_to_debate",
            StreamEventType.MOUND_UPDATED,
            self._handle_culture_to_debate,
        )

        # Phase 6b: Debate Start → Load Culture (active retrieval) relocated to
        # aragora.knowledge.event_subscribers (P4a Batch E2c); wired at bootstrap
        # via apply_registered_subscribers, not registered here.

        # Phase 7: Staleness → Debate relocated to
        # aragora.server.event_subscribers (P4a Batch E6 relocate-UP; interface-tier
        # home); wired at bootstrap via apply_registered_subscribers
        # (interface-superset only - a pure-domain manager has no WebSocket state
        # manager to react through), not registered here.

        # Explainability: Debate End → Explanation auto-trigger
        self.register(
            "debate_end_to_explainability",
            StreamEventType.DEBATE_END,
            self._handle_debate_end_to_explainability,
        )

        # Knowledge: Debate End → Outcome persistence relocated to
        # aragora.knowledge.event_subscribers (P4a Batch E2c); wired at bootstrap
        # via apply_registered_subscribers, not registered here.

        # =====================================================================
        # Phase 3: Cross-Subsystem Event Bridges
        # =====================================================================

        # Gauntlet Complete → Notification relocated to
        # aragora.server.event_subscribers; notification delivery is an
        # interface concern and is wired only by the interface-superset
        # bootstrap.

        # Debate End → Cost Tracking
        self.register(
            "debate_end_to_cost_tracking",
            StreamEventType.DEBATE_END,
            self._handle_debate_end_to_cost_tracking,
        )

        # Consensus → Selection Learning relocated to
        # aragora.debate.event_subscribers (P4a Batch E4 relocate-UP); wired at
        # bootstrap via apply_registered_subscribers, not registered here.

        # Agent Message → Rhetorical Analysis relocated to
        # aragora.debate.event_subscribers (P4a Batch E4 relocate-UP); wired at
        # bootstrap via apply_registered_subscribers, not registered here.

        # Vote → Belief Network relocated to aragora.reasoning.event_subscribers
        # (P4a Batch E3 relocate-UP); wired at bootstrap via
        # apply_registered_subscribers, not registered here.

        # Workflow Complete/Failed → Supermemory and Memory Tier
        # Demotion/Promotion → Knowledge Mound all relocated to
        # aragora.knowledge.event_subscribers (P4a Batch E2c); wired at bootstrap
        # via apply_registered_subscribers, not registered here.

        # Webhook delivery for all cross-pollination events (8 webhook_* names)
        # relocated to aragora.server.event_subscribers (P4a Batch E6
        # relocate-UP; interface-tier home); wired at bootstrap via
        # apply_registered_subscribers (interface-superset only - a pure-domain
        # manager has no webhook store to react through), not registered here.

        # =====================================================================
        # Strategic Feedback Loops (Tier 5)
        # =====================================================================

        # Risk Warning → Health Registry degradation
        self.register(
            "risk_warning_to_health",
            StreamEventType.RISK_WARNING,
            self._handle_risk_warning_to_health,
        )

        # Agent Birth → Control Plane Registry
        self.register(
            "agent_birth_to_control_plane",
            StreamEventType.AGENT_BIRTH,
            self._handle_genesis_to_control_plane,
        )

        # Agent Death → Control Plane Registry
        self.register(
            "agent_death_to_control_plane",
            StreamEventType.AGENT_DEATH,
            self._handle_genesis_to_control_plane,
        )

        # Agent Evolution → Control Plane Registry
        self.register(
            "agent_evolution_to_control_plane",
            StreamEventType.AGENT_EVOLUTION,
            self._handle_genesis_to_control_plane,
        )

        # Approval Approved → KM Reinforcement relocated to
        # aragora.knowledge.event_subscribers (P4a Batch E2c); wired at bootstrap
        # via apply_registered_subscribers, not registered here.

        # Budget Alert → Team Selection Constraint relocated to
        # aragora.debate.event_subscribers (P4a Batch E4 relocate-UP); wired at
        # bootstrap via apply_registered_subscribers, not registered here.

        # Alert Escalated → Workflow Emergency Brake relocated to
        # aragora.workflow.event_subscribers (P4a Batch E5 relocate-UP;
        # application-tier home); wired at bootstrap via
        # apply_registered_subscribers (interface-superset only - a pure-domain
        # manager has no workflow engine to react through), not registered here.

        # Meta-Learning Adjusted → Team Selection Recalibration relocated to
        # aragora.debate.event_subscribers (P4a Batch E4 relocate-UP); wired at
        # bootstrap via apply_registered_subscribers, not registered here.

        logger.debug("Registered built-in cross-subsystem subscribers")

    def register(
        self,
        name: str,
        event_type: StreamEventType,
        handler: CrossSubscriberHandler,
    ) -> None:
        """
        Register a cross-subsystem subscriber.

        Args:
            name: Unique name for the subscriber
            event_type: Event type to subscribe to
            handler: Handler function called with StreamEvent
        """
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []

        self._subscribers[event_type].append((name, handler))
        self._stats[name] = SubscriberStats(name=name)

        logger.debug("Registered subscriber '%s' for %s", name, event_type.value)

    def subscribe(
        self,
        event_type: StreamEventType,
    ) -> Callable[[CrossSubscriberHandler], CrossSubscriberHandler]:
        """
        Decorator for registering subscribers.

        Usage:
            @manager.subscribe(StreamEventType.MEMORY_STORED)
            def on_memory_stored(event):
                pass
        """

        def decorator(func: CrossSubscriberHandler) -> CrossSubscriberHandler:
            self.register(func.__name__, event_type, func)
            return func

        return decorator

    def connect(self, event_emitter: Any) -> None:
        """
        Connect to an event emitter to receive events.

        Args:
            event_emitter: EventEmitter instance to subscribe to
        """
        if self._connected:
            logger.warning("CrossSubscriberManager already connected")
            return

        def on_event(event: StreamEvent) -> None:
            self._dispatch_event(event)

        event_emitter.subscribe(on_event)
        self._connected = True
        logger.info("CrossSubscriberManager connected to event stream")
