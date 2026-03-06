"""
End-to-end integration tests for the Inbox-to-Debate pipeline.

Validates the full flow:
    Message --> trigger rule evaluation --> debate spawning --> result routing

All external dependencies (Arena, debate_origin, result_router) are mocked
to keep tests fast and deterministic.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.inbox.debate_router import (
    InboxDebateRouter,
    RouterConfig,
    TriggerRule,
    get_inbox_debate_router,
    reset_inbox_debate_router,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_router():
    """Reset global router state between tests."""
    reset_inbox_debate_router()
    yield
    reset_inbox_debate_router()


@pytest.fixture
def config() -> RouterConfig:
    """Default router config that triggers on high-priority + keyword."""
    return RouterConfig(
        enabled=True,
        priority_threshold="high",
        keyword_patterns=["urgent", "critical decision"],
        max_debates_per_hour=20,
        cooldown_seconds=0,  # disable cooldown for fast tests
    )


@pytest.fixture
def router(config: RouterConfig) -> InboxDebateRouter:
    """Pre-configured router with an event_bus mock."""
    event_bus = MagicMock()
    return InboxDebateRouter(config=config, event_bus=event_bus)


@pytest.fixture
def high_priority_message() -> dict:
    """A message that should trigger debate via priority threshold."""
    return {
        "message_id": "msg-e2e-001",
        "channel": "slack",
        "sender": "alice@example.com",
        "content": "We need to decide on the Q3 budget allocation.",
        "subject": "Q3 Budget Review",
        "priority": "high",
        "metadata": {"workspace_id": "ws-123"},
    }


@pytest.fixture
def keyword_message() -> dict:
    """A message that triggers via keyword match, normal priority."""
    return {
        "message_id": "msg-e2e-002",
        "channel": "email",
        "sender": "bob@example.com",
        "content": "This is an urgent matter that needs immediate attention.",
        "subject": "Urgent: Server outage",
        "priority": "normal",
        "metadata": {},
    }


@pytest.fixture
def low_priority_message() -> dict:
    """A message that should NOT trigger any debate."""
    return {
        "message_id": "msg-e2e-003",
        "channel": "email",
        "sender": "newsletter@example.com",
        "content": "Here is the weekly newsletter.",
        "subject": "Weekly update",
        "priority": "low",
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Happy Path
# ---------------------------------------------------------------------------


class TestHappyPath:
    """Tests for the happy path: message triggers debate and routes result."""

    @pytest.mark.asyncio
    async def test_high_priority_triggers_debate(self, router, high_priority_message):
        """A high-priority message should trigger a debate."""
        with (
            patch(
                "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
                new_callable=AsyncMock,
            ) as mock_run,
            patch(
                "aragora.inbox.debate_router.InboxDebateRouter._register_origin",
            ) as mock_origin,
        ):
            await router.start()
            result = await router.spawn_debate(high_priority_message)

            assert result.triggered is True
            assert result.debate_id is not None
            assert result.debate_id.startswith("inbox-")
            assert result.channel == "slack"
            assert router.stats["debates_triggered"] == 1

            # Verify debate origin was registered
            mock_origin.assert_called_once()
            call_kwargs = mock_origin.call_args
            assert call_kwargs[1]["debate_id"] == result.debate_id
            assert call_kwargs[1]["channel"] == "slack"

            # Verify debate was launched
            mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_keyword_triggers_debate(self, router, keyword_message):
        """A keyword-matching message should trigger a debate."""
        with patch(
            "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
            new_callable=AsyncMock,
        ):
            await router.start()
            result = await router.spawn_debate(keyword_message)

            assert result.triggered is True
            assert result.rule_matched == "default_keyword"
            assert "urgent" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_event_emissions(self, router, high_priority_message):
        """spawn_debate should emit inbox_item_flagged and inbox_debate_triggered events."""
        with patch(
            "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
            new_callable=AsyncMock,
        ):
            await router.start()
            await router.spawn_debate(high_priority_message)

            bus = router._event_bus

            # Collect all emit calls
            emit_calls = bus.emit.call_args_list
            event_types = [call[0][0] for call in emit_calls]

            assert "inbox_item_flagged" in event_types
            assert "inbox_debate_triggered" in event_types


# ---------------------------------------------------------------------------
# No-Match
# ---------------------------------------------------------------------------


class TestNoMatch:
    """Tests where no trigger rule matches."""

    @pytest.mark.asyncio
    async def test_low_priority_no_trigger(self, router, low_priority_message):
        """A low-priority message without keyword match should not trigger."""
        await router.start()
        result = await router.spawn_debate(low_priority_message)

        assert result.triggered is False
        assert result.debate_id is None
        assert router.stats["debates_triggered"] == 0
        assert router.stats["messages_skipped"] == 1


# ---------------------------------------------------------------------------
# Rate-Limited
# ---------------------------------------------------------------------------


class TestRateLimited:
    """Tests for rate limiting behavior."""

    @pytest.mark.asyncio
    async def test_rate_limited_after_max_debates(self, high_priority_message):
        """Once max_debates_per_hour is hit, further messages are rate-limited."""
        config = RouterConfig(
            enabled=True,
            priority_threshold="high",
            max_debates_per_hour=2,
            cooldown_seconds=0,
        )
        router = InboxDebateRouter(config=config)

        with patch(
            "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
            new_callable=AsyncMock,
        ):
            await router.start()

            # Trigger 2 debates (the max)
            for i in range(2):
                msg = {**high_priority_message, "message_id": f"msg-{i}"}
                result = await router.spawn_debate(msg)
                assert result.triggered is True

            # Third should be rate-limited
            msg3 = {**high_priority_message, "message_id": "msg-rate-limited"}
            result3 = await router.spawn_debate(msg3)
            assert result3.triggered is False
            assert "Rate limited" in result3.reason
            assert router.stats["rate_limited"] >= 1


# ---------------------------------------------------------------------------
# Disabled Router
# ---------------------------------------------------------------------------


class TestDisabledRouter:
    """Tests with the router disabled."""

    @pytest.mark.asyncio
    async def test_disabled_router_skips_evaluation(self, high_priority_message):
        """When the router is disabled, no messages trigger debates."""
        config = RouterConfig(enabled=False)
        router = InboxDebateRouter(config=config)
        await router.start()

        result = await router.spawn_debate(high_priority_message)
        assert result.triggered is False
        assert "disabled" in result.reason.lower()
        assert router.stats["debates_triggered"] == 0


# ---------------------------------------------------------------------------
# on_message_received event handler
# ---------------------------------------------------------------------------


class TestOnMessageReceived:
    """Tests for the event subscription handler."""

    @pytest.mark.asyncio
    async def test_on_message_received_dict_event(self, router, high_priority_message):
        """on_message_received handles plain dict events."""
        with patch(
            "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
            new_callable=AsyncMock,
        ):
            await router.start()

            event = {"data": high_priority_message}
            await router.on_message_received(event)

            assert router.stats["debates_triggered"] >= 1

    @pytest.mark.asyncio
    async def test_on_message_received_stream_event(self, router, high_priority_message):
        """on_message_received handles StreamEvent-like objects."""
        with patch(
            "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
            new_callable=AsyncMock,
        ):
            await router.start()

            # Simulate a StreamEvent-like object
            event = MagicMock()
            event.data = high_priority_message

            await router.on_message_received(event)
            assert router.stats["debates_triggered"] >= 1

    @pytest.mark.asyncio
    async def test_on_message_received_skips_when_not_running(self, router):
        """on_message_received does nothing when the router is not running."""
        # Don't call start()
        event = {"data": {"content": "urgent issue", "priority": "critical"}}
        await router.on_message_received(event)
        assert router.stats["messages_evaluated"] == 0

    @pytest.mark.asyncio
    async def test_on_message_received_empty_content_skipped(self, router):
        """on_message_received skips messages with no content or subject."""
        await router.start()
        event = {"data": {"message_id": "empty", "channel": "slack"}}
        await router.on_message_received(event)
        assert router.stats["messages_evaluated"] == 0


# ---------------------------------------------------------------------------
# Debate Origin Registration
# ---------------------------------------------------------------------------


class TestDebateOriginRegistration:
    """Tests verifying debate origin is registered for result routing."""

    @pytest.mark.asyncio
    async def test_origin_registered_with_correct_metadata(self, router, high_priority_message):
        """Debate origin should include auto_spawned and source metadata."""
        with (
            patch(
                "aragora.inbox.debate_router.InboxDebateRouter._run_debate",
                new_callable=AsyncMock,
            ),
            patch(
                "aragora.server.debate_origin.registry.register_debate_origin",
            ) as mock_register,
        ):
            await router.start()
            result = await router.spawn_debate(high_priority_message)

            mock_register.assert_called_once()
            call_kwargs = mock_register.call_args[1]
            assert call_kwargs["platform"] == "slack"
            assert call_kwargs["user_id"] == "alice@example.com"
            assert call_kwargs["metadata"]["auto_spawned"] is True
            assert call_kwargs["metadata"]["source"] == "inbox_debate_router"
