# Aragora Events Module

The events module provides event types, webhook delivery, and event routing for external integrations. It serves as a shared dependency layer that can be imported by any module without circular dependencies.

## Architecture

```
events/
├── __init__.py              # Module exports
├── types.py                 # Event types and emitters
├── schema.py                # Event schema definitions
├── context.py               # Event context management
├── dispatcher.py            # Core webhook dispatcher
├── async_dispatcher.py      # Async event dispatching
├── batch_dispatcher.py      # Batch webhook delivery
├── security_dispatcher.py   # Security-focused events
├── security_events.py       # Security event definitions
├── arena_bridge.py          # Arena event integration
├── dead_letter_queue.py     # Failed event handling
├── webhook_verify.py        # Webhook signature verification
├── subscribers/             # Event subscriber implementations
└── cross_subscribers/       # Cross-debate event routing
```

## Core Components

### Event Types

```python
from aragora.events import StreamEvent, StreamEventType, EventEmitter

# Available event types
StreamEventType.DEBATE_START
StreamEventType.DEBATE_END
StreamEventType.ROUND_START
StreamEventType.AGENT_MESSAGE
StreamEventType.CRITIQUE
StreamEventType.VOTE
StreamEventType.CONSENSUS
StreamEventType.ERROR
```

### Event Emitter

```python
from aragora.events import EventEmitter

class MyComponent:
    def __init__(self):
        self.events = EventEmitter()

    async def do_something(self):
        # Emit an event
        await self.events.emit(StreamEvent(
            event_type=StreamEventType.CUSTOM,
            debate_id="debate-123",
            data={"key": "value"}
        ))

# Subscribe to events
async def handler(event: StreamEvent):
    print(f"Received: {event.event_type}")

emitter.subscribe(handler)
```

### Webhook Dispatcher

```python
from aragora.events import get_dispatcher, dispatch_event

# Get global dispatcher
dispatcher = get_dispatcher()

# Subscribe to arena events
dispatcher.subscribe_to_stream(arena.events)

# Manually dispatch events
await dispatch_event("debate_end", {
    "debate_id": "debate-123",
    "consensus": True,
    "final_answer": "Use PostgreSQL"
})

# Direct webhook dispatch
await dispatch_webhook(
    url="https://example.com/webhook",
    event_type="debate_end",
    payload={"debate_id": "..."}
)
```

### Batch Dispatcher

For high-volume event delivery:

```python
from aragora.events import BatchWebhookDispatcher, get_batch_dispatcher

dispatcher = get_batch_dispatcher()

# Queue events for batch delivery
dispatcher.queue_event("debate_end", payload)
dispatcher.queue_event("consensus", payload)

# Events are automatically batched and delivered
# based on configured thresholds
```

### Webhook Verification

Secure webhook delivery with signature verification:

```python
from aragora.events import (
    generate_signature,
    verify_signature,
    verify_webhook_request,
)

# Generate signature for outgoing webhook
signature = generate_signature(
    secret="your-webhook-secret",
    payload=json.dumps(data),
    timestamp=int(time.time())
)

# Verify incoming webhook
result = verify_webhook_request(
    request=request,
    secret="your-webhook-secret",
    max_age_seconds=300
)

if result.valid:
    process_webhook(request)
else:
    return 401, result.error
```

## Cross-Debate Event Routing

Route events across debates and workspaces:

```python
from aragora.events import (
    CrossSubscriberManager,
    get_cross_subscriber_manager,
)

manager = get_cross_subscriber_manager()

# Subscribe to events from multiple debates
manager.subscribe(
    subscriber_id="analytics",
    event_types=["debate_end", "consensus"],
    handler=analytics_handler
)

# Get subscriber stats
stats = manager.get_stats("analytics")
print(f"Events processed: {stats.events_processed}")
```

## Arena Bridge

Connect Arena debates to the event system:

```python
from aragora.debate.arena_bridge import ArenaEventBridge, create_arena_bridge

# Create bridge for an arena
bridge = create_arena_bridge(arena)

# Events are automatically routed:
# - debate_start -> webhook subscribers
# - agent_message -> WebSocket clients
# - consensus -> Knowledge Mound, analytics
```

## Dead Letter Queue

Handle failed event deliveries:

```python
from aragora.events.dead_letter_queue import (
    DeadLetterQueue,
    get_dead_letter_queue,
)

dlq = get_dead_letter_queue()

# Failed events are automatically queued
# Retry with exponential backoff
await dlq.retry_failed(max_retries=3)

# Get failed events
failed = await dlq.get_failed_events(
    event_type="debate_end",
    limit=100
)
```

## Security Events

Track security-relevant events:

```python
from aragora.events import SecurityEventDispatcher

dispatcher = SecurityEventDispatcher()

# Log security events
await dispatcher.log_auth_failure(
    user_id="user-123",
    reason="invalid_token",
    ip_address="192.168.1.1"
)

await dispatcher.log_suspicious_activity(
    user_id="user-123",
    activity_type="rate_limit_exceeded",
    metadata={"endpoint": "/api/v2/debates"}
)
```

## Event Subscribers

Built-in subscriber implementations:

| Subscriber | Location | Purpose |
|------------|----------|---------|
| WebhookSubscriber | `subscribers/webhook.py` | HTTP webhook delivery |
| WebSocketSubscriber | `subscribers/websocket.py` | Real-time WebSocket push |
| KafkaSubscriber | `subscribers/kafka.py` | Kafka topic publishing |
| AnalyticsSubscriber | `subscribers/analytics.py` | Analytics pipeline |

## Event Schema

```python
from aragora.events.schema import (
    EventSchema,
    validate_event,
    get_schema,
)

# Validate event payload
schema = get_schema("debate_end")
is_valid = validate_event(payload, schema)

# Event payloads follow JSON Schema
{
    "event_type": "debate_end",
    "debate_id": "string",
    "timestamp": "ISO8601",
    "data": {
        "consensus": "boolean",
        "final_answer": "string",
        "duration_seconds": "number"
    }
}
```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `WEBHOOK_TIMEOUT_SECONDS` | Webhook request timeout | `30` |
| `WEBHOOK_MAX_RETRIES` | Max delivery retries | `3` |
| `WEBHOOK_BATCH_SIZE` | Batch dispatcher threshold | `100` |
| `WEBHOOK_BATCH_INTERVAL_MS` | Batch flush interval | `1000` |
| `DLQ_RETENTION_HOURS` | Dead letter retention | `72` |
| `EVENT_SIGNATURE_SECRET` | Webhook signing secret | Required |

### Dispatcher Configuration

```python
from aragora.events.dispatcher import DispatcherConfig

config = DispatcherConfig(
    timeout_seconds=30,
    max_retries=3,
    retry_delay_seconds=5,
    batch_size=100,
    enable_dlq=True,
)
```

## Integration Points

### WebSocket Streaming

Events are automatically pushed to WebSocket clients:

```python
# Client receives events via WebSocket
ws://api.aragora.ai/ws/debates/{debate_id}/stream

# Events include: debate_start, agent_message, consensus, etc.
```

### Prometheus Metrics

Event delivery metrics are exposed:

```
aragora_events_dispatched_total{event_type="debate_end"}
aragora_events_failed_total{event_type="debate_end"}
aragora_webhook_latency_seconds{endpoint="..."}
```

## Related Modules

- `aragora/connectors/` - External integration connectors
- `aragora/server/stream/` - WebSocket streaming
- `aragora/webhooks/` - Webhook configuration
- `aragora/broadcast/` - Event broadcasting
