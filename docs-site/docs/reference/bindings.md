---
title: Message Binding Router Guide
description: Message Binding Router Guide
---

# Message Binding Router Guide

The Binding Router implements the ClawdBot pattern for flexible message routing. Bindings map message sources (provider/account/peer) to agent configurations, enabling context-aware agent selection for chat platforms.

## Overview

The Bindings system provides:
- **Pattern matching**: Route messages using wildcards (`channel:*`, `dm:*`)
- **Priority resolution**: Higher priority bindings match first
- **Time windows**: Route differently by hour of day
- **User filtering**: Allow/block specific users per binding
- **Binding types**: Default, specific agent, agent pool, debate team
- **Config overrides**: Per-binding configuration adjustments

## Architecture

```
┌─────────────────┐     ┌───────────────────┐     ┌─────────────────┐
│  Chat Message   │────>│  BindingRouter    │────>│  Agent/Team     │
│  (Slack/TG/etc) │     │                   │     │                 │
└─────────────────┘     └─────────┬─────────┘     └─────────────────┘
                                  │
                        ┌─────────┴─────────┐
                        │  Resolution Flow  │
                        ├───────────────────┤
                        │  1. Exact match   │
                        │  2. Wildcard acct │
                        │  3. Provider def  │
                        │  4. Global def    │
                        └───────────────────┘
```

## Quick Start

```python
from aragora.server.bindings import (
    BindingRouter,
    MessageBinding,
    BindingType,
    get_binding_router,
)

# Create router
router = BindingRouter()

# Add bindings with priority ordering
router.add_binding(MessageBinding(
    provider="slack",
    account_id="T12345",
    peer_pattern="channel:*",
    agent_binding="default",
    priority=10,
))

router.add_binding(MessageBinding(
    provider="slack",
    account_id="T12345",
    peer_pattern="dm:U67890",
    agent_binding="claude-opus",
    priority=20,  # Higher priority for specific user
))

# Resolve binding for a message
resolution = router.resolve("slack", "T12345", "dm:U67890")
print(f"Agent: {resolution.agent_binding}")  # claude-opus
print(f"Reason: {resolution.match_reason}")  # Matched pattern: dm:U67890
```

## Core Classes

### BindingType

Defines how agent selection works:

```python
from aragora.server.bindings import BindingType

class BindingType(str, Enum):
    DEFAULT = "default"          # Use default agent configuration
    SPECIFIC_AGENT = "specific_agent"  # Use a specific named agent
    AGENT_POOL = "agent_pool"    # Select from a pool of agents
    DEBATE_TEAM = "debate_team"  # Use a full debate team
    CUSTOM = "custom"            # Custom routing logic
```

### MessageBinding

Defines a routing rule:

```python
from aragora.server.bindings import MessageBinding, BindingType

binding = MessageBinding(
    # Required: Message source identification
    provider="slack",           # Platform: slack, telegram, discord
    account_id="T12345",        # Workspace/team/server ID
    peer_pattern="channel:*",   # Pattern to match channels/DMs

    # Agent configuration
    agent_binding="claude-opus",
    binding_type=BindingType.SPECIFIC_AGENT,

    # Priority (higher = more specific, checked first)
    priority=20,

    # Time constraints (optional)
    time_window_start=9,   # Start hour (0-23)
    time_window_end=17,    # End hour (0-23)

    # User filtering (optional)
    allowed_users={"U12345", "U67890"},  # Only these users
    blocked_users={"USPAMMER"},          # Never these users

    # Configuration overrides
    config_overrides={
        "temperature": 0.7,
        "max_tokens": 1000,
    },

    # Metadata
    name="enterprise-support",
    description="Route enterprise support to Claude Opus",
    enabled=True,
)

# Check matching
print(binding.matches_peer("channel:general"))  # True (matches channel:*)
print(binding.matches_peer("dm:someone"))       # False

print(binding.matches_time(10))  # True (within 9-17)
print(binding.matches_time(20))  # False (outside window)

print(binding.matches_user("U12345"))  # True (in allowed_users)
print(binding.matches_user("USPAMMER")) # False (in blocked_users)

# Serialize
data = binding.to_dict()
restored = MessageBinding.from_dict(data)
```

### Pattern Matching

Peer patterns use fnmatch-style wildcards:

| Pattern | Matches | Does Not Match |
|---------|---------|----------------|
| `channel:*` | `channel:general`, `channel:eng` | `dm:user123` |
| `dm:U*` | `dm:U12345`, `dm:UABC` | `channel:foo`, `dm:B123` |
| `*` | Everything | - |
| `thread:C*:*` | `thread:C123:456` | `dm:user` |

### Time Windows

Support both normal and wrapping time ranges:

```python
# Normal range: 9 AM to 5 PM
binding = MessageBinding(
    provider="slack",
    account_id="*",
    peer_pattern="*",
    agent_binding="day-agent",
    time_window_start=9,
    time_window_end=17,
)

# Wrapping range: 10 PM to 6 AM (night shift)
night_binding = MessageBinding(
    provider="slack",
    account_id="*",
    peer_pattern="*",
    agent_binding="night-agent",
    time_window_start=22,
    time_window_end=6,
    priority=5,  # Lower priority than day binding
)
```

### BindingResolution

Result of resolving a message:

```python
from aragora.server.bindings import BindingResolution

resolution = router.resolve("slack", "T12345", "channel:general")

print(f"Matched: {resolution.matched}")
print(f"Agent: {resolution.agent_binding}")
print(f"Type: {resolution.binding_type}")
print(f"Config: {resolution.config_overrides}")
print(f"Reason: {resolution.match_reason}")
print(f"Checked: {resolution.candidates_checked} candidates")

# Access full binding details
if resolution.binding:
    print(f"Binding name: {resolution.binding.name}")
    print(f"Priority: {resolution.binding.priority}")
```

## BindingRouter

The router manages bindings and resolves messages.

### Initialization

```python
from aragora.server.bindings import BindingRouter

router = BindingRouter()

# Router starts with a global default binding:
# - provider: "*"
# - account_id: "*"
# - peer_pattern: "*"
# - agent_binding: "default"
# - priority: -1000
```

### Adding Bindings

```python
# Add specific binding
router.add_binding(MessageBinding(
    provider="telegram",
    account_id="@mybotname",
    peer_pattern="group:*",
    agent_binding="claude",
    priority=10,
))

# Bindings are sorted by priority (descending) within each provider/account
router.add_binding(MessageBinding(
    provider="telegram",
    account_id="@mybotname",
    peer_pattern="group:vip-*",
    agent_binding="claude-opus",
    priority=20,  # Checked before generic group pattern
))
```

### Removing Bindings

```python
# Remove by provider/account/pattern
removed = router.remove_binding("telegram", "@mybotname", "group:vip-*")
print(f"Removed: {removed}")  # True if found
```

### Default Bindings

Set fallback bindings at different levels:

```python
# Provider-level default (used when no specific binding matches)
router.set_default_binding("telegram", MessageBinding(
    provider="telegram",
    account_id="*",
    peer_pattern="*",
    agent_binding="telegram-default",
))

# Global default (used when nothing else matches)
router.set_global_default(MessageBinding(
    provider="*",
    account_id="*",
    peer_pattern="*",
    agent_binding="fallback-agent",
))
```

### Resolution Flow

Messages are resolved in this order:

1. **Exact match**: Provider + Account + matching pattern (by priority)
2. **Wildcard account**: Provider + "*" account + matching pattern
3. **Provider default**: Provider-specific default binding
4. **Global default**: Catch-all default

```python
# Example resolution
resolution = router.resolve(
    provider="slack",
    account_id="T12345",
    peer_id="channel:engineering",
    user_id="U67890",      # Optional user filtering
    hour=14,               # Optional time filtering
)
```

### Agent Pools

Group agents for pool-based routing:

```python
# Register a pool of agents
router.register_agent_pool("fast-agents", [
    "claude-haiku",
    "gpt-4o-mini",
    "gemini-flash",
])

# Create binding that uses the pool
router.add_binding(MessageBinding(
    provider="slack",
    account_id="*",
    peer_pattern="channel:quick-*",
    agent_binding="fast-agents",
    binding_type=BindingType.AGENT_POOL,
))

# When resolving, first available agent from pool is selected
```

### Agent Selection

Select an agent based on binding resolution:

```python
# Assuming you have a list of Agent objects
available_agents = [claude_agent, gpt_agent, gemini_agent]

selection = router.get_agent_for_message(
    provider="slack",
    account_id="T12345",
    peer_id="channel:engineering",
    available_agents=available_agents,
    user_id="U67890",
)

print(f"Selected: {selection.agent_name}")
print(f"Config: {selection.config}")
print(f"Reason: {selection.selection_reason}")
```

### Listing and Statistics

```python
# List all bindings
all_bindings = router.list_bindings()

# Filter by provider
slack_bindings = router.list_bindings(provider="slack")

# Filter by provider and account
specific_bindings = router.list_bindings(
    provider="slack",
    account_id="T12345",
)

# Get router statistics
stats = router.get_stats()
print(f"Total bindings: {stats['total_bindings']}")
print(f"Providers: {stats['providers']}")
print(f"Agent pools: {stats['agent_pools']}")
```

## Global Router

Access the singleton router instance:

```python
from aragora.server.bindings import (
    get_binding_router,
    reset_binding_router,
)

# Get singleton instance
router = get_binding_router()

# Reset for testing
reset_binding_router()
```

## Integration with Chat Connectors

The binding router integrates with Aragora's chat connectors:

### Telegram Integration

```python
from aragora.connectors.chat.telegram import TelegramConnector
from aragora.server.bindings import get_binding_router, MessageBinding

router = get_binding_router()

# Route group messages to debate teams
router.add_binding(MessageBinding(
    provider="telegram",
    account_id="@mybot",
    peer_pattern="group:*",
    agent_binding="debate-team-alpha",
    binding_type=BindingType.DEBATE_TEAM,
))

# Route DMs to single agent
router.add_binding(MessageBinding(
    provider="telegram",
    account_id="@mybot",
    peer_pattern="dm:*",
    agent_binding="claude-sonnet",
    binding_type=BindingType.SPECIFIC_AGENT,
))

# In connector message handler:
async def handle_message(message):
    resolution = router.resolve(
        provider="telegram",
        account_id="@mybot",
        peer_id=f"group:{message.chat.id}",
        user_id=str(message.from_user.id),
    )

    if resolution.binding_type == BindingType.DEBATE_TEAM:
        # Start a debate
        await start_debate(message, resolution.config_overrides)
    else:
        # Single agent response
        await get_agent_response(message, resolution.agent_binding)
```

### Slack Integration

```python
from aragora.connectors.slack import SlackConnector

router = get_binding_router()

# VIP channel gets premium agent
router.add_binding(MessageBinding(
    provider="slack",
    account_id="T123WORKSPACE",
    peer_pattern="channel:C456VIP",
    agent_binding="claude-opus",
    binding_type=BindingType.SPECIFIC_AGENT,
    priority=100,
))

# Support channels during business hours
router.add_binding(MessageBinding(
    provider="slack",
    account_id="T123WORKSPACE",
    peer_pattern="channel:C*-support",
    agent_binding="support-team",
    binding_type=BindingType.AGENT_POOL,
    time_window_start=9,
    time_window_end=17,
    priority=50,
))

# All other channels
router.add_binding(MessageBinding(
    provider="slack",
    account_id="T123WORKSPACE",
    peer_pattern="channel:*",
    agent_binding="default",
    priority=10,
))
```

## REST API

The bindings system is exposed via REST endpoints:

```
GET  /api/bindings              # List all bindings
GET  /api/bindings/:provider    # List bindings for provider
POST /api/bindings              # Create a new binding
DELETE /api/bindings/:provider/:account/:pattern  # Delete binding
POST /api/bindings/resolve      # Resolve binding for message
GET  /api/bindings/stats        # Get router statistics
```

### Create Binding

```bash
curl -X POST /api/bindings \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "slack",
    "account_id": "T12345",
    "peer_pattern": "channel:eng-*",
    "agent_binding": "claude-sonnet",
    "binding_type": "specific_agent",
    "priority": 20
  }'
```

### Resolve Binding

```bash
curl -X POST /api/bindings/resolve \
  -H "Content-Type: application/json" \
  -d '{
    "provider": "slack",
    "account_id": "T12345",
    "peer_id": "channel:eng-backend",
    "user_id": "U67890"
  }'
```

## Best Practices

1. **Use meaningful priorities** - Higher numbers for more specific patterns:
   ```python
   # Priority scale example:
   # 100+ : Specific user/channel overrides
   # 50-99: Category patterns (support-*, vip-*)
   # 10-49: General patterns (channel:*, dm:*)
   # 0-9  : Provider defaults
   # &lt;0   : Global fallback
   ```

2. **Order patterns from specific to general**:
   ```python
   router.add_binding(MessageBinding(..., peer_pattern="dm:UVIP", priority=100))
   router.add_binding(MessageBinding(..., peer_pattern="dm:*", priority=10))
   ```

3. **Use time windows for coverage**:
   ```python
   # Day shift: premium agents
   router.add_binding(MessageBinding(
       ...,
       agent_binding="claude-opus",
       time_window_start=9,
       time_window_end=17,
       priority=20,
   ))

   # Night shift: efficient agents
   router.add_binding(MessageBinding(
       ...,
       agent_binding="claude-haiku",
       time_window_start=17,
       time_window_end=9,
       priority=15,
   ))
   ```

4. **Block problematic users at binding level**:
   ```python
   router.add_binding(MessageBinding(
       provider="telegram",
       account_id="*",
       peer_pattern="*",
       agent_binding="default",
       blocked_users={"spam_user_1", "spam_user_2"},
   ))
   ```

5. **Use config_overrides for fine-tuning**:
   ```python
   router.add_binding(MessageBinding(
       ...,
       config_overrides={
           "temperature": 0.3,  # More deterministic
           "max_tokens": 500,   # Shorter responses
           "system_prompt": "Be concise.",
       },
   ))
   ```

## Testing

```python
from aragora.server.bindings import (
    BindingRouter,
    MessageBinding,
    BindingType,
    reset_binding_router,
)

def test_priority_resolution():
    """Higher priority bindings match first."""
    router = BindingRouter()

    router.add_binding(MessageBinding(
        provider="slack",
        account_id="T1",
        peer_pattern="channel:*",
        agent_binding="low-priority",
        priority=10,
    ))

    router.add_binding(MessageBinding(
        provider="slack",
        account_id="T1",
        peer_pattern="channel:vip-*",
        agent_binding="high-priority",
        priority=20,
    ))

    # VIP channel matches high-priority
    resolution = router.resolve("slack", "T1", "channel:vip-support")
    assert resolution.agent_binding == "high-priority"

    # Regular channel matches low-priority
    resolution = router.resolve("slack", "T1", "channel:general")
    assert resolution.agent_binding == "low-priority"

def test_time_window():
    """Time windows filter bindings."""
    router = BindingRouter()

    router.add_binding(MessageBinding(
        provider="slack",
        account_id="*",
        peer_pattern="*",
        agent_binding="day-agent",
        time_window_start=9,
        time_window_end=17,
        priority=10,
    ))

    # During business hours
    resolution = router.resolve("slack", "T1", "channel:any", hour=12)
    assert resolution.agent_binding == "day-agent"

    # Outside business hours (falls to global default)
    resolution = router.resolve("slack", "T1", "channel:any", hour=20)
    assert resolution.agent_binding == "default"

def test_user_filtering():
    """User allow/block lists work correctly."""
    router = BindingRouter()

    router.add_binding(MessageBinding(
        provider="slack",
        account_id="*",
        peer_pattern="*",
        agent_binding="premium",
        allowed_users={"UVIP"},
        priority=20,
    ))

    # VIP user matches
    resolution = router.resolve("slack", "T1", "dm:x", user_id="UVIP")
    assert resolution.agent_binding == "premium"

    # Non-VIP falls to default
    resolution = router.resolve("slack", "T1", "dm:x", user_id="URANDOM")
    assert resolution.agent_binding == "default"
```

## See Also

- [Chat Connector Guide](../guides/chat-connector) - Telegram, WhatsApp integration
- [Skills System](../guides/skills) - Agent capabilities
- [Control Plane](../enterprise/control-plane-overview) - Agent registry and scheduling
