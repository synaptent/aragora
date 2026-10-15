"""
Aragora Events Package.

Provides event types, webhook delivery, and event routing for external integrations.

The events layer is a shared dependency that can be imported by any layer
(CLI, debate, memory, server) without creating circular dependencies.

Usage:
    # Import event types (available to all layers)
    from aragora.events import StreamEvent, StreamEventType, EventEmitter

    # Import webhook dispatcher
    from aragora.events import WebhookDispatcher, get_dispatcher

    # Get the global dispatcher
    dispatcher = get_dispatcher()

    # Subscribe to events
    dispatcher.subscribe_to_stream(event_emitter)

    # Or manually dispatch an event
    from aragora.events.dispatcher import dispatch_event
    dispatch_event("debate_end", {"debate_id": "...", "consensus": True})
"""

from .dispatcher import (
    WebhookDispatcher,
    dispatch_event,
    dispatch_webhook,
    get_dispatcher,
    shutdown_dispatcher,
)
from .types import (
    AudienceMessage,
    EventEmitter,
    StreamEvent,
    StreamEventType,
)
from .cross_subscribers import (
    CrossSubscriberManager,
    SubscriberStats,
    get_cross_subscriber_manager,
    reset_cross_subscriber_manager,
)
from .webhook_verify import (
    VerificationResult,
    generate_signature,
    verify_signature,
    verify_timestamp,
    verify_webhook_request,
    create_test_webhook_payload,
)
from .batch_dispatcher import (
    BatchWebhookDispatcher,
    BatchedEvent,
    EventBatch,
    get_batch_dispatcher,
    queue_batched_event,
    shutdown_batch_dispatcher,
)
from .async_dispatcher import (
    AsyncWebhookDispatcher,
    AsyncDeliveryResult,
    get_async_dispatcher,
    dispatch_webhook_async,
    dispatch_webhook_async_with_retry,
    shutdown_async_dispatcher,
)
from .security_events import (
    # Event types
    SecurityEventType,
    SecuritySeverity,
    SecurityFinding,
    SecurityEvent,
    # Emitter
    SecurityEventEmitter,
    SecurityEventHandler,
    get_security_emitter,
    set_security_emitter,
    # Debate integration (domain-free hook; implementation lives in
    # aragora.debate.security_response - import from there directly, this
    # package never re-exports domain-coupled symbols)
    SecurityDebateRunner,
    register_security_debate_runner,
    get_security_debate_runner,
    get_security_debate_result,
    list_security_debates,
    # Convenience functions
    create_vulnerability_event,
    create_secret_event,
    create_scan_completed_event,
)
from .security_dispatcher import (
    # Main class
    SecurityDispatcher,
    DispatcherConfig,
    DispatcherStats,
    # Global instance functions
    get_security_dispatcher,
    set_security_dispatcher,
    start_security_dispatcher,
    stop_security_dispatcher,
)

__all__ = [
    # Event types (shared layer)
    "StreamEventType",
    "StreamEvent",
    "AudienceMessage",
    "EventEmitter",
    # Webhook dispatcher
    "WebhookDispatcher",
    "get_dispatcher",
    "dispatch_event",
    "dispatch_webhook",
    "shutdown_dispatcher",
    # Cross-subsystem subscribers
    "CrossSubscriberManager",
    "SubscriberStats",
    "get_cross_subscriber_manager",
    "reset_cross_subscriber_manager",
    # Webhook verification
    "VerificationResult",
    "generate_signature",
    "verify_signature",
    "verify_timestamp",
    "verify_webhook_request",
    "create_test_webhook_payload",
    # Batch dispatcher
    "BatchWebhookDispatcher",
    "BatchedEvent",
    "EventBatch",
    "get_batch_dispatcher",
    "queue_batched_event",
    "shutdown_batch_dispatcher",
    # Async dispatcher
    "AsyncWebhookDispatcher",
    "AsyncDeliveryResult",
    "get_async_dispatcher",
    "dispatch_webhook_async",
    "dispatch_webhook_async_with_retry",
    "shutdown_async_dispatcher",
    # Security events
    "SecurityEventType",
    "SecuritySeverity",
    "SecurityFinding",
    "SecurityEvent",
    "SecurityEventEmitter",
    "SecurityEventHandler",
    "get_security_emitter",
    "set_security_emitter",
    "SecurityDebateRunner",
    "register_security_debate_runner",
    "get_security_debate_runner",
    "get_security_debate_result",
    "list_security_debates",
    "create_vulnerability_event",
    "create_secret_event",
    "create_scan_completed_event",
    # Security dispatcher
    "SecurityDispatcher",
    "DispatcherConfig",
    "DispatcherStats",
    "get_security_dispatcher",
    "set_security_dispatcher",
    "start_security_dispatcher",
    "stop_security_dispatcher",
    # Event registry (unified)
    "EventRegistry",
    "EventCategory",
    "EventSeverity",
    "EventSource",
    "EventMetadata",
    "get_event_registry",
    "reset_event_registry",
]

# Event registry (late import to avoid circular dependencies)
from .registry import (
    EventRegistry,
    EventCategory,
    EventSeverity,
    EventSource,
    EventMetadata,
    get_event_registry,
    reset_event_registry,
)
