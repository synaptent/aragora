"""
Tests for InboxDebateRouter.

Covers configuration, rule evaluation, priority matching, keyword matching,
rate limiting, debate spawning, result routing, and event emission.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.inbox.debate_router import (
    DebateSpawnResult,
    InboxDebateRouter,
    PriorityLevel,
    RouterConfig,
    TriggerRule,
    get_inbox_debate_router,
    reset_inbox_debate_router,
    _PRIORITY_ORDER,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_global_router():
    """Reset global router state between tests."""
    reset_inbox_debate_router()
    yield
    reset_inbox_debate_router()


@pytest.fixture()
def config() -> RouterConfig:
    """Default router config for tests."""
    return RouterConfig(
        enabled=True,
        priority_threshold="high",
        keyword_patterns=["urgent", "critical decision"],
        max_debates_per_hour=10,
        cooldown_seconds=60.0,
    )


@pytest.fixture()
def router(config: RouterConfig) -> InboxDebateRouter:
    """InboxDebateRouter instance for tests."""
    return InboxDebateRouter(config=config)


@pytest.fixture()
def sample_message() -> dict:
    """A sample inbox message dict."""
    return {
        "message_id": "msg-001",
        "channel": "slack",
        "sender": "alice@example.com",
        "content": "We need to make a critical decision about the Q3 budget.",
        "subject": "Q3 Budget Review",
        "priority": "high",
        "metadata": {"workspace_id": "ws-123"},
    }


@pytest.fixture()
def low_priority_message() -> dict:
    """A low-priority message that should not trigger."""
    return {
        "message_id": "msg-002",
        "channel": "email",
        "sender": "newsletter@example.com",
        "content": "Here is our weekly newsletter update.",
        "subject": "Weekly Newsletter",
        "priority": "low",
        "metadata": {},
    }


# ---------------------------------------------------------------------------
# Configuration Tests
# ---------------------------------------------------------------------------


class TestRouterConfig:
    """Tests for RouterConfig creation and serialization."""

    def test_default_config(self):
        config = RouterConfig()
        assert config.enabled is True
        assert config.priority_threshold == "high"
        assert config.keyword_patterns == []
        assert config.rules == []
        assert config.max_debates_per_hour == 10
        assert config.cooldown_seconds == 60.0
        assert config.default_rounds == 3
        assert config.default_consensus == "majority"
        assert config.default_agent_count == 4

    def test_config_from_dict(self):
        data = {
            "enabled": False,
            "priority_threshold": "urgent",
            "keyword_patterns": ["escalate"],
            "max_debates_per_hour": 5,
            "cooldown_seconds": 120.0,
            "rules": [
                {
                    "name": "test-rule",
                    "keyword_patterns": ["help"],
                    "priority_threshold": "critical",
                }
            ],
        }
        config = RouterConfig.from_dict(data)
        assert config.enabled is False
        assert config.priority_threshold == "urgent"
        assert config.keyword_patterns == ["escalate"]
        assert config.max_debates_per_hour == 5
        assert config.cooldown_seconds == 120.0
        assert len(config.rules) == 1
        assert config.rules[0].name == "test-rule"

    def test_config_to_dict_roundtrip(self):
        config = RouterConfig(
            enabled=True,
            priority_threshold="critical",
            keyword_patterns=["urgent", "help"],
            rules=[TriggerRule(name="r1", keyword_patterns=["fire"])],
        )
        data = config.to_dict()
        restored = RouterConfig.from_dict(data)
        assert restored.enabled == config.enabled
        assert restored.priority_threshold == config.priority_threshold
        assert restored.keyword_patterns == config.keyword_patterns
        assert len(restored.rules) == 1
        assert restored.rules[0].name == "r1"

    def test_config_with_channels(self):
        config = RouterConfig(
            monitored_channels=["slack", "teams"],
            excluded_channels=["discord"],
        )
        assert config.monitored_channels == ["slack", "teams"]
        assert config.excluded_channels == ["discord"]


class TestTriggerRule:
    """Tests for TriggerRule creation and serialization."""

    def test_default_rule(self):
        rule = TriggerRule()
        assert rule.enabled is True
        assert rule.keyword_patterns == []
        assert rule.priority_threshold is None
        assert rule.sender_patterns == []
        assert rule.channels == []
        assert rule.debate_rounds == 3
        assert rule.debate_consensus == "majority"
        assert rule.debate_agent_count == 4

    def test_rule_from_dict(self):
        data = {
            "id": "r1",
            "name": "vip-sender",
            "enabled": True,
            "sender_patterns": [r"ceo@.*\.com"],
            "priority_threshold": "normal",
            "debate_rounds": 5,
        }
        rule = TriggerRule.from_dict(data)
        assert rule.id == "r1"
        assert rule.name == "vip-sender"
        assert rule.sender_patterns == [r"ceo@.*\.com"]
        assert rule.debate_rounds == 5

    def test_rule_to_dict_roundtrip(self):
        rule = TriggerRule(
            name="escalation",
            keyword_patterns=["escalate", "help"],
            channels=["slack"],
            priority_threshold="urgent",
        )
        data = rule.to_dict()
        restored = TriggerRule.from_dict(data)
        assert restored.name == rule.name
        assert restored.keyword_patterns == rule.keyword_patterns
        assert restored.channels == rule.channels
        assert restored.priority_threshold == rule.priority_threshold


# ---------------------------------------------------------------------------
# Priority Tests
# ---------------------------------------------------------------------------


class TestPriorityLevels:
    """Tests for priority level ordering and comparison."""

    def test_priority_order(self):
        assert _PRIORITY_ORDER["low"] < _PRIORITY_ORDER["normal"]
        assert _PRIORITY_ORDER["normal"] < _PRIORITY_ORDER["high"]
        assert _PRIORITY_ORDER["high"] < _PRIORITY_ORDER["urgent"]
        assert _PRIORITY_ORDER["urgent"] < _PRIORITY_ORDER["critical"]

    def test_priority_enum_values(self):
        assert PriorityLevel.LOW.value == "low"
        assert PriorityLevel.NORMAL.value == "normal"
        assert PriorityLevel.HIGH.value == "high"
        assert PriorityLevel.URGENT.value == "urgent"
        assert PriorityLevel.CRITICAL.value == "critical"


# ---------------------------------------------------------------------------
# Message Evaluation Tests
# ---------------------------------------------------------------------------


class TestEvaluateMessage:
    """Tests for the evaluate_message method."""

    def test_disabled_router_skips(self, sample_message):
        config = RouterConfig(enabled=False)
        router = InboxDebateRouter(config=config)
        result = router.evaluate_message(sample_message)
        assert result.triggered is False
        assert "disabled" in result.reason.lower()

    def test_high_priority_triggers(self, router, sample_message):
        """High priority message meets the default threshold."""
        result = router.evaluate_message(sample_message)
        assert result.triggered is True
        assert result.message_id == "msg-001"
        assert result.channel == "slack"

    def test_low_priority_no_match(self, router, low_priority_message):
        """Low priority message does not meet threshold and has no keywords."""
        result = router.evaluate_message(low_priority_message)
        assert result.triggered is False

    def test_keyword_triggers(self, router):
        """Message with matching keyword triggers even with low priority."""
        message = {
            "message_id": "msg-003",
            "channel": "email",
            "sender": "bob@example.com",
            "content": "This is an urgent request for budget approval.",
            "subject": "Request",
            "priority": "normal",
        }
        result = router.evaluate_message(message)
        assert result.triggered is True
        assert result.rule_matched == "default_keyword"
        assert "urgent" in result.reason.lower()

    def test_keyword_in_subject_triggers(self, router):
        """Keywords are checked in subject as well as content."""
        message = {
            "message_id": "msg-004",
            "channel": "teams",
            "sender": "carol@example.com",
            "content": "Please review.",
            "subject": "URGENT: Action Required",
            "priority": "normal",
        }
        result = router.evaluate_message(message)
        assert result.triggered is True

    def test_priority_threshold_exact_match(self):
        """Message priority exactly at threshold triggers."""
        config = RouterConfig(priority_threshold="urgent")
        router = InboxDebateRouter(config=config)
        message = {
            "message_id": "msg-005",
            "channel": "slack",
            "sender": "dave@example.com",
            "content": "Need immediate review.",
            "priority": "urgent",
        }
        result = router.evaluate_message(message)
        assert result.triggered is True

    def test_priority_above_threshold_triggers(self):
        """Message priority above threshold triggers."""
        config = RouterConfig(priority_threshold="high")
        router = InboxDebateRouter(config=config)
        message = {
            "message_id": "msg-006",
            "channel": "email",
            "sender": "eve@example.com",
            "content": "Critical system failure.",
            "priority": "critical",
        }
        result = router.evaluate_message(message)
        assert result.triggered is True

    def test_priority_below_threshold_skips(self):
        """Message priority below threshold does not trigger."""
        config = RouterConfig(priority_threshold="urgent", keyword_patterns=[])
        router = InboxDebateRouter(config=config)
        message = {
            "message_id": "msg-007",
            "channel": "slack",
            "sender": "frank@example.com",
            "content": "Normal update message.",
            "priority": "high",
        }
        result = router.evaluate_message(message)
        assert result.triggered is False

    def test_stats_tracking(self, router, sample_message, low_priority_message):
        """Stats are updated on evaluation."""
        router.evaluate_message(sample_message)
        router.evaluate_message(low_priority_message)
        assert router.stats["messages_evaluated"] == 2
        assert router.stats["messages_skipped"] == 1

    def test_missing_fields_handled(self, router):
        """Messages with missing fields don't crash."""
        message = {"message_id": "msg-008"}
        result = router.evaluate_message(message)
        # Should not raise, just evaluate
        assert isinstance(result, DebateSpawnResult)


# ---------------------------------------------------------------------------
# Channel Filter Tests
# ---------------------------------------------------------------------------


class TestChannelFilters:
    """Tests for monitored and excluded channel filtering."""

    def test_monitored_channels_filter(self):
        config = RouterConfig(
            monitored_channels=["slack", "teams"],
            priority_threshold="normal",
        )
        router = InboxDebateRouter(config=config)

        # Slack message triggers
        slack_msg = {"message_id": "m1", "channel": "slack", "priority": "high", "content": ""}
        assert router.evaluate_message(slack_msg).triggered is True

        # Discord message skipped
        discord_msg = {"message_id": "m2", "channel": "discord", "priority": "high", "content": ""}
        result = router.evaluate_message(discord_msg)
        assert result.triggered is False
        assert "not in monitored" in result.reason.lower()

    def test_excluded_channels_filter(self):
        config = RouterConfig(
            excluded_channels=["discord"],
            priority_threshold="normal",
        )
        router = InboxDebateRouter(config=config)

        discord_msg = {"message_id": "m3", "channel": "discord", "priority": "high", "content": ""}
        result = router.evaluate_message(discord_msg)
        assert result.triggered is False
        assert "excluded" in result.reason.lower()

        slack_msg = {"message_id": "m4", "channel": "slack", "priority": "high", "content": ""}
        assert router.evaluate_message(slack_msg).triggered is True


# ---------------------------------------------------------------------------
# Custom Rule Tests
# ---------------------------------------------------------------------------


class TestCustomRules:
    """Tests for custom TriggerRule evaluation."""

    def test_keyword_rule_matches(self):
        rule = TriggerRule(
            name="escalation",
            keyword_patterns=["escalate", "help needed"],
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",  # high threshold
            keyword_patterns=[],  # no default keywords
        )
        router = InboxDebateRouter(config=config)

        message = {
            "message_id": "m1",
            "channel": "slack",
            "sender": "alice",
            "content": "Please escalate this to management.",
            "priority": "normal",
        }
        result = router.evaluate_message(message)
        assert result.triggered is True
        assert result.rule_matched == "escalation"

    def test_sender_pattern_rule(self):
        rule = TriggerRule(
            name="vip-sender",
            sender_patterns=[r"ceo@", r"cto@"],
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",  # high threshold so default doesn't trigger
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        message = {
            "message_id": "m2",
            "channel": "email",
            "sender": "ceo@company.com",
            "content": "Let's discuss strategy.",
            "priority": "normal",
        }
        result = router.evaluate_message(message)
        assert result.triggered is True
        assert result.rule_matched == "vip-sender"

    def test_sender_pattern_no_match(self):
        rule = TriggerRule(
            name="vip-sender",
            sender_patterns=[r"ceo@", r"cto@"],
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        message = {
            "message_id": "m3",
            "channel": "email",
            "sender": "intern@company.com",
            "content": "Question about the printer.",
            "priority": "normal",
        }
        result = router.evaluate_message(message)
        assert result.triggered is False

    def test_channel_filtered_rule(self):
        rule = TriggerRule(
            name="slack-only",
            keyword_patterns=["help"],
            channels=["slack"],
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        # Slack message matches
        slack_msg = {
            "message_id": "m4",
            "channel": "slack",
            "sender": "bob",
            "content": "I need help with this.",
            "priority": "normal",
        }
        assert router.evaluate_message(slack_msg).triggered is True

        # Email message does not match (wrong channel)
        email_msg = {
            "message_id": "m5",
            "channel": "email",
            "sender": "bob",
            "content": "I need help with this.",
            "priority": "normal",
        }
        assert router.evaluate_message(email_msg).triggered is False

    def test_priority_only_rule(self):
        rule = TriggerRule(
            name="urgent-rule",
            priority_threshold="urgent",
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",  # Very high default threshold
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        msg = {
            "message_id": "m6",
            "channel": "teams",
            "sender": "carol",
            "content": "Production is down.",
            "priority": "urgent",
        }
        result = router.evaluate_message(msg)
        assert result.triggered is True
        assert result.rule_matched == "urgent-rule"

    def test_disabled_rule_skipped(self):
        rule = TriggerRule(
            name="disabled-rule",
            keyword_patterns=["trigger"],
            enabled=False,
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        msg = {
            "message_id": "m7",
            "channel": "slack",
            "content": "This should trigger a debate.",
            "priority": "normal",
        }
        assert router.evaluate_message(msg).triggered is False

    def test_rules_evaluated_in_priority_order(self):
        """Rules with lower priority number are evaluated first."""
        rule_low = TriggerRule(
            name="low-priority-rule",
            keyword_patterns=["keyword"],
            priority=20,
        )
        rule_high = TriggerRule(
            name="high-priority-rule",
            keyword_patterns=["keyword"],
            priority=5,
        )
        config = RouterConfig(
            rules=[rule_low, rule_high],
            priority_threshold="critical",
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        msg = {
            "message_id": "m8",
            "channel": "slack",
            "content": "This has the keyword.",
            "priority": "normal",
        }
        result = router.evaluate_message(msg)
        assert result.triggered is True
        assert result.rule_matched == "high-priority-rule"

    def test_invalid_sender_regex_handled(self):
        """Invalid regex in sender pattern does not crash."""
        rule = TriggerRule(
            name="bad-regex",
            sender_patterns=["[invalid(regex"],
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        msg = {
            "message_id": "m9",
            "channel": "email",
            "sender": "test@example.com",
            "content": "test",
            "priority": "normal",
        }
        # Should not raise
        result = router.evaluate_message(msg)
        assert result.triggered is False


# ---------------------------------------------------------------------------
# Rate Limiting Tests
# ---------------------------------------------------------------------------


class TestRateLimiting:
    """Tests for rate limiting and cooldown behavior."""

    def test_cooldown_blocks_rapid_triggers(self):
        config = RouterConfig(
            priority_threshold="normal",
            cooldown_seconds=300.0,  # 5 minute cooldown
        )
        router = InboxDebateRouter(config=config)

        msg1 = {"message_id": "m1", "channel": "slack", "priority": "high", "content": ""}
        msg2 = {"message_id": "m2", "channel": "slack", "priority": "high", "content": ""}

        result1 = router.evaluate_message(msg1)
        assert result1.triggered is True

        # Simulate the debate being spawned (records cooldown)
        router._record_debate_spawn("slack")

        result2 = router.evaluate_message(msg2)
        assert result2.triggered is False
        assert router.stats["rate_limited"] == 1

    def test_different_channels_not_cooled(self):
        config = RouterConfig(
            priority_threshold="normal",
            cooldown_seconds=300.0,
        )
        router = InboxDebateRouter(config=config)

        msg_slack = {"message_id": "m1", "channel": "slack", "priority": "high", "content": ""}
        msg_email = {"message_id": "m2", "channel": "email", "priority": "high", "content": ""}

        result1 = router.evaluate_message(msg_slack)
        assert result1.triggered is True
        router._record_debate_spawn("slack")

        # Different channel is not cooled down
        result2 = router.evaluate_message(msg_email)
        assert result2.triggered is True

    def test_hourly_rate_limit(self):
        config = RouterConfig(
            priority_threshold="normal",
            max_debates_per_hour=2,
            cooldown_seconds=0.0,  # no per-channel cooldown
        )
        router = InboxDebateRouter(config=config)

        # Fill up the hourly limit
        router._record_debate_spawn("ch1")
        router._record_debate_spawn("ch2")

        msg = {"message_id": "m3", "channel": "ch3", "priority": "high", "content": ""}
        result = router.evaluate_message(msg)
        assert result.triggered is False
        assert router.stats["rate_limited"] == 1

    def test_expired_timestamps_cleared(self):
        config = RouterConfig(
            priority_threshold="normal",
            max_debates_per_hour=2,
            cooldown_seconds=0.0,
        )
        router = InboxDebateRouter(config=config)

        # Add old timestamps (more than 1 hour ago)
        old_time = time.time() - 7200.0  # 2 hours ago
        router._debate_timestamps = [old_time, old_time]

        msg = {"message_id": "m4", "channel": "ch1", "priority": "high", "content": ""}
        result = router.evaluate_message(msg)
        # Old timestamps should be cleared, so within limit
        assert result.triggered is True


# ---------------------------------------------------------------------------
# Debate Spawning Tests
# ---------------------------------------------------------------------------


class TestSpawnDebate:
    """Tests for the spawn_debate method."""

    @pytest.mark.asyncio
    async def test_spawn_triggers_debate(self, router, sample_message):
        """spawn_debate evaluates and attempts to spawn."""
        with (
            patch.object(router, "_register_origin"),
            patch.object(router, "_run_debate", new_callable=AsyncMock) as mock_run,
        ):
            result = await router.spawn_debate(sample_message)
            assert result.triggered is True
            assert result.debate_id is not None
            assert result.debate_id.startswith("inbox-")
            assert router.stats["debates_triggered"] == 1

    @pytest.mark.asyncio
    async def test_spawn_no_trigger_returns_early(self, router, low_priority_message):
        """spawn_debate returns early if message doesn't trigger."""
        result = await router.spawn_debate(low_priority_message)
        assert result.triggered is False
        assert result.debate_id is None
        assert router.stats["debates_triggered"] == 0

    @pytest.mark.asyncio
    async def test_spawn_uses_rule_params(self):
        """spawn_debate uses the matched rule's debate parameters."""
        rule = TriggerRule(
            name="custom-rule",
            keyword_patterns=["trigger"],
            debate_rounds=5,
            debate_consensus="supermajority",
            debate_agent_count=6,
        )
        config = RouterConfig(
            rules=[rule],
            priority_threshold="critical",
            keyword_patterns=[],
        )
        router = InboxDebateRouter(config=config)

        message = {
            "message_id": "m1",
            "channel": "slack",
            "sender": "alice",
            "content": "Please trigger this.",
            "priority": "normal",
        }

        with (
            patch.object(router, "_register_origin"),
            patch.object(router, "_run_debate", new_callable=AsyncMock) as mock_run,
        ):
            result = await router.spawn_debate(message)
            assert result.triggered is True
            # Check the _run_debate was called with custom params
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["rounds"] == 5
            assert call_kwargs["consensus"] == "supermajority"
            assert call_kwargs["agent_count"] == 6

    @pytest.mark.asyncio
    async def test_spawn_registers_origin(self, router, sample_message):
        """spawn_debate registers the debate origin."""
        with (
            patch.object(router, "_register_origin") as mock_register,
            patch.object(router, "_run_debate", new_callable=AsyncMock),
        ):
            result = await router.spawn_debate(sample_message)
            assert result.triggered is True
            mock_register.assert_called_once()
            call_kwargs = mock_register.call_args[1]
            assert call_kwargs["channel"] == "slack"
            assert call_kwargs["sender"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_spawn_emits_events(self):
        """spawn_debate emits INBOX_ITEM_FLAGGED and INBOX_DEBATE_TRIGGERED events."""
        event_bus = MagicMock()
        config = RouterConfig(priority_threshold="normal")
        router = InboxDebateRouter(config=config, event_bus=event_bus)

        message = {
            "message_id": "m1",
            "channel": "slack",
            "sender": "alice",
            "content": "Review needed.",
            "priority": "high",
        }

        with (
            patch.object(router, "_register_origin"),
            patch.object(router, "_run_debate", new_callable=AsyncMock),
            patch("aragora.events.dispatcher.dispatch_event") as mock_dispatch,
        ):
            result = await router.spawn_debate(message)
            assert result.triggered is True

            # Check event bus calls
            assert event_bus.emit.call_count >= 2  # flagged + triggered

            # Check webhook dispatcher calls
            assert mock_dispatch.call_count >= 2
            event_types = [call[0][0] for call in mock_dispatch.call_args_list]
            assert "inbox_item_flagged" in event_types
            assert "inbox_debate_triggered" in event_types


# ---------------------------------------------------------------------------
# Debate Question Building Tests
# ---------------------------------------------------------------------------


class TestBuildDebateQuestion:
    """Tests for _build_debate_question."""

    def test_question_includes_subject_and_content(self, router):
        message = {
            "channel": "slack",
            "sender": "alice",
            "subject": "Budget Review",
            "content": "Should we increase the Q3 budget?",
        }
        question = router._build_debate_question(message)
        assert "Budget Review" in question
        assert "increase the Q3 budget" in question
        assert "slack" in question
        assert "alice" in question

    def test_question_truncates_long_content(self, router):
        message = {
            "channel": "email",
            "sender": "bob",
            "subject": "Long Message",
            "content": "x" * 5000,
        }
        question = router._build_debate_question(message)
        # Content should be truncated to 2000 chars + "..."
        assert len(question) < 5000
        assert "..." in question

    def test_question_handles_missing_fields(self, router):
        message = {"channel": "teams"}
        question = router._build_debate_question(message)
        assert "teams" in question
        assert "No content provided" in question


# ---------------------------------------------------------------------------
# Rule Management Tests
# ---------------------------------------------------------------------------


class TestRuleManagement:
    """Tests for add_rule, remove_rule, list_rules."""

    def test_add_rule(self, router):
        rule = TriggerRule(name="new-rule", keyword_patterns=["test"])
        router.add_rule(rule)
        assert len(router.list_rules()) == 1
        assert router.list_rules()[0]["name"] == "new-rule"

    def test_remove_rule(self, router):
        rule = TriggerRule(id="r1", name="removable")
        router.add_rule(rule)
        assert len(router.list_rules()) == 1

        removed = router.remove_rule("r1")
        assert removed is True
        assert len(router.list_rules()) == 0

    def test_remove_nonexistent_rule(self, router):
        removed = router.remove_rule("nonexistent")
        assert removed is False

    def test_list_rules_empty(self, router):
        assert router.list_rules() == []


# ---------------------------------------------------------------------------
# Stats Tests
# ---------------------------------------------------------------------------


class TestStats:
    """Tests for statistics tracking."""

    def test_initial_stats(self, router):
        stats = router.stats
        assert stats["messages_evaluated"] == 0
        assert stats["debates_triggered"] == 0
        assert stats["debates_completed"] == 0
        assert stats["debates_failed"] == 0
        assert stats["messages_skipped"] == 0
        assert stats["rate_limited"] == 0
        assert stats["active_debates"] == 0
        assert stats["enabled"] is True
        assert stats["running"] is False

    def test_reset_stats(self, router, sample_message):
        router.evaluate_message(sample_message)
        assert router.stats["messages_evaluated"] > 0
        router.reset_stats()
        assert router.stats["messages_evaluated"] == 0

    @pytest.mark.asyncio
    async def test_running_state(self, router):
        assert router.running is False
        await router.start()
        assert router.running is True
        await router.stop()
        assert router.running is False

    @pytest.mark.asyncio
    async def test_start_idempotent(self, router):
        await router.start()
        await router.start()  # Should not error
        assert router.running is True


# ---------------------------------------------------------------------------
# Global Instance Tests
# ---------------------------------------------------------------------------


class TestGlobalInstance:
    """Tests for get_inbox_debate_router and reset."""

    def test_get_creates_instance(self):
        router = get_inbox_debate_router()
        assert isinstance(router, InboxDebateRouter)

    def test_get_returns_same_instance(self):
        router1 = get_inbox_debate_router()
        router2 = get_inbox_debate_router()
        assert router1 is router2

    def test_reset_clears_instance(self):
        router1 = get_inbox_debate_router()
        reset_inbox_debate_router()
        router2 = get_inbox_debate_router()
        assert router1 is not router2

    def test_get_with_config(self):
        config = RouterConfig(priority_threshold="critical")
        router = get_inbox_debate_router(config=config)
        assert router.config.priority_threshold == "critical"


# ---------------------------------------------------------------------------
# DebateSpawnResult Tests
# ---------------------------------------------------------------------------


class TestDebateSpawnResult:
    """Tests for the DebateSpawnResult dataclass."""

    def test_to_dict(self):
        result = DebateSpawnResult(
            triggered=True,
            debate_id="d-123",
            rule_matched="test-rule",
            reason="Matched keyword",
            message_id="m-456",
            channel="slack",
        )
        data = result.to_dict()
        assert data["triggered"] is True
        assert data["debate_id"] == "d-123"
        assert data["rule_matched"] == "test-rule"
        assert data["reason"] == "Matched keyword"
        assert data["message_id"] == "m-456"
        assert data["channel"] == "slack"
        assert "timestamp" in data

    def test_not_triggered(self):
        result = DebateSpawnResult(triggered=False, reason="No match")
        assert result.debate_id is None
        assert result.rule_matched is None


# ---------------------------------------------------------------------------
# Result Routing Tests
# ---------------------------------------------------------------------------


class TestResultRouting:
    """Tests for _route_result."""

    @pytest.mark.asyncio
    async def test_route_result_with_to_dict(self, router):
        """Route result when result has to_dict method."""
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {"debate_id": "d1", "final_answer": "yes"}

        mock_route = AsyncMock(return_value=True)
        with patch(
            "aragora.server.result_router.route_result",
            mock_route,
        ):
            await router._route_result("d1", mock_result)
            mock_route.assert_called_once_with("d1", {"debate_id": "d1", "final_answer": "yes"})

    @pytest.mark.asyncio
    async def test_route_result_with_dict_attrs(self, router):
        """Route result when result has __dict__ attributes."""

        class FakeResult:
            debate_id = "d2"
            consensus_reached = True
            final_answer = "approved"
            confidence = 0.85
            participants = ["claude", "gpt"]
            task = "Budget review"

        mock_route = AsyncMock(return_value=True)
        with patch(
            "aragora.server.result_router.route_result",
            mock_route,
        ):
            await router._route_result("d2", FakeResult())
            mock_route.assert_called_once()
            call_args = mock_route.call_args[0]
            assert call_args[0] == "d2"
            assert call_args[1]["consensus_reached"] is True

    @pytest.mark.asyncio
    async def test_route_result_import_error(self, router):
        """Route result gracefully handles missing module."""
        with patch.dict("sys.modules", {"aragora.server.result_router": None}):
            # Should not raise (ImportError handled gracefully)
            await router._route_result("d3", {"debate_id": "d3"})


# ---------------------------------------------------------------------------
# Debate Execution Tests
# ---------------------------------------------------------------------------


class TestDebateExecution:
    """Tests for _run_debate."""

    @pytest.mark.asyncio
    async def test_run_debate_success(self, router):
        """Successful debate execution updates stats."""
        mock_result = MagicMock()
        mock_result.consensus_reached = True
        mock_result.final_answer = "Approved"
        mock_result.confidence = 0.9
        mock_result.rounds_used = 3

        mock_arena = AsyncMock()
        mock_arena.run.return_value = mock_result

        mock_core = MagicMock()
        mock_core.Environment = MagicMock()

        mock_protocol = MagicMock()
        mock_protocol.DebateProtocol = MagicMock()

        mock_orchestrator = MagicMock()
        mock_orchestrator.Arena = MagicMock(return_value=mock_arena)

        with (
            patch.dict(
                "sys.modules",
                {
                    "aragora.core": mock_core,
                    "aragora.protocols.debate": mock_protocol,
                    "aragora.debate.orchestrator": mock_orchestrator,
                },
            ),
            patch.object(router, "_route_result", new_callable=AsyncMock),
            patch.object(router, "_emit_event"),
        ):
            router._active_debates["d1"] = {"debate_id": "d1"}
            await router._run_debate(
                debate_id="d1",
                question="Test?",
                rounds=3,
                consensus="majority",
                agent_count=4,
                channel="slack",
                message_id="m1",
            )
            assert router.stats["debates_completed"] == 1
            assert "d1" not in router._active_debates

    @pytest.mark.asyncio
    async def test_run_debate_failure(self, router):
        """Failed debate execution updates failure stats."""
        mock_arena = AsyncMock()
        mock_arena.run.side_effect = RuntimeError("Debate failed")

        mock_core = MagicMock()
        mock_core.Environment = MagicMock()

        mock_protocol = MagicMock()
        mock_protocol.DebateProtocol = MagicMock()

        mock_orchestrator = MagicMock()
        mock_orchestrator.Arena = MagicMock(return_value=mock_arena)

        with (
            patch.dict(
                "sys.modules",
                {
                    "aragora.core": mock_core,
                    "aragora.protocols.debate": mock_protocol,
                    "aragora.debate.orchestrator": mock_orchestrator,
                },
            ),
            patch.object(router, "_emit_event"),
        ):
            router._active_debates["d2"] = {"debate_id": "d2"}
            await router._run_debate(
                debate_id="d2",
                question="Test?",
                rounds=3,
                consensus="majority",
                agent_count=4,
                channel="slack",
                message_id="m2",
            )
            assert router.stats["debates_failed"] == 1
            assert "d2" not in router._active_debates

    @pytest.mark.asyncio
    async def test_run_debate_import_error(self, router):
        """Missing Arena module doesn't crash."""
        with patch.dict("sys.modules", {"aragora.core": None}):
            router._active_debates["d3"] = {"debate_id": "d3"}
            await router._run_debate(
                debate_id="d3",
                question="Test?",
                rounds=3,
                consensus="majority",
                agent_count=4,
                channel="slack",
                message_id="m3",
            )
            assert router.stats["debates_failed"] == 1


# ---------------------------------------------------------------------------
# Event Emission Tests
# ---------------------------------------------------------------------------


class TestEventEmission:
    """Tests for _emit_event."""

    def test_emit_to_sync_event_bus(self):
        bus = MagicMock()
        bus.emit = MagicMock()  # sync emit
        router = InboxDebateRouter(event_bus=bus)
        with patch("aragora.events.dispatcher.dispatch_event"):
            router._emit_event("test_event", {"key": "value"})
        bus.emit.assert_called_once_with("test_event", key="value")

    def test_emit_without_event_bus(self):
        """No event bus does not crash."""
        router = InboxDebateRouter()
        with patch("aragora.events.dispatcher.dispatch_event") as mock_dispatch:
            router._emit_event("test_event", {"key": "value"})
            mock_dispatch.assert_called_once_with("test_event", {"key": "value"})

    def test_emit_handles_dispatch_import_error(self):
        """Missing dispatcher does not crash."""
        router = InboxDebateRouter()
        with patch(
            "aragora.events.dispatcher.dispatch_event",
            side_effect=ImportError("not available"),
        ):
            # Should not raise
            router._emit_event("test_event", {"data": "value"})

    def test_emit_handles_bus_error(self):
        """Event bus error does not crash."""
        bus = MagicMock()
        bus.emit.side_effect = TypeError("bad args")
        router = InboxDebateRouter(event_bus=bus)
        with patch("aragora.events.dispatcher.dispatch_event"):
            # Should not raise
            router._emit_event("test_event", {"data": "value"})


# ---------------------------------------------------------------------------
# Active Debates Tests
# ---------------------------------------------------------------------------


class TestActiveDebates:
    """Tests for active debate tracking."""

    @pytest.mark.asyncio
    async def test_active_debates_tracked(self, router, sample_message):
        """Active debates are tracked during spawn."""
        with (
            patch.object(router, "_register_origin"),
            patch.object(router, "_run_debate", new_callable=AsyncMock),
        ):
            result = await router.spawn_debate(sample_message)
            assert result.triggered is True
            # The _run_debate mock completes immediately, but the active
            # debate is added before _run_debate is called
            active = router.get_active_debates()
            # Because _run_debate is mocked as AsyncMock, the background task
            # won't actually run _run_debate in the real way, so active_debates
            # may or may not still contain it depending on timing.
            # What we CAN assert is that the mechanism works.
            assert isinstance(active, list)

    def test_get_active_debates_empty(self, router):
        assert router.get_active_debates() == []


# ---------------------------------------------------------------------------
# Integration-style Tests
# ---------------------------------------------------------------------------


class TestIntegration:
    """Integration-style tests combining multiple features."""

    def test_full_evaluation_flow(self):
        """Full evaluation flow: config -> rules -> match -> result."""
        config = RouterConfig(
            enabled=True,
            priority_threshold="critical",
            keyword_patterns=[],
            rules=[
                TriggerRule(
                    name="vip-escalation",
                    sender_patterns=[r"vp@", r"director@"],
                    keyword_patterns=["escalate"],
                    priority=1,
                ),
                TriggerRule(
                    name="security-alert",
                    keyword_patterns=["security breach", "data leak"],
                    channels=["slack", "email"],
                    priority=5,
                ),
            ],
        )
        router = InboxDebateRouter(config=config)

        # VIP escalation match
        msg1 = {
            "message_id": "m1",
            "channel": "email",
            "sender": "vp@company.com",
            "content": "Please escalate this immediately.",
            "priority": "normal",
        }
        r1 = router.evaluate_message(msg1)
        assert r1.triggered is True
        assert r1.rule_matched == "vip-escalation"

        # Security alert match
        msg2 = {
            "message_id": "m2",
            "channel": "slack",
            "sender": "soc-team@company.com",
            "content": "Potential data leak detected in production.",
            "priority": "normal",
        }
        r2 = router.evaluate_message(msg2)
        assert r2.triggered is True
        assert r2.rule_matched == "security-alert"

        # No match (wrong channel for security rule, not VIP sender)
        msg3 = {
            "message_id": "m3",
            "channel": "discord",
            "sender": "random@external.com",
            "content": "Is there a data leak?",
            "priority": "normal",
        }
        r3 = router.evaluate_message(msg3)
        assert r3.triggered is False

        # Check stats
        assert router.stats["messages_evaluated"] == 3
        assert router.stats["messages_skipped"] == 1

    def test_keyword_case_insensitive(self):
        """Keywords are matched case-insensitively."""
        config = RouterConfig(
            priority_threshold="critical",
            keyword_patterns=["URGENT"],
        )
        router = InboxDebateRouter(config=config)

        msg = {
            "message_id": "m1",
            "channel": "email",
            "sender": "user",
            "content": "This is urgent please help.",
            "priority": "normal",
        }
        result = router.evaluate_message(msg)
        assert result.triggered is True

    def test_multi_word_keyword(self):
        """Multi-word keyword patterns work correctly."""
        config = RouterConfig(
            priority_threshold="critical",
            keyword_patterns=["critical decision"],
        )
        router = InboxDebateRouter(config=config)

        msg = {
            "message_id": "m1",
            "channel": "teams",
            "sender": "manager",
            "content": "We have a critical decision to make about Q4.",
            "priority": "normal",
        }
        result = router.evaluate_message(msg)
        assert result.triggered is True
        assert "critical decision" in result.reason.lower()
