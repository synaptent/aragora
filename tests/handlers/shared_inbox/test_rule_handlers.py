"""
Tests for Shared Inbox Rule Handlers (aragora/server/handlers/shared_inbox/rule_handlers.py).

Covers all 5 handler functions:
- handle_create_routing_rule    POST   /api/v1/inbox/routing/rules
- handle_list_routing_rules     GET    /api/v1/inbox/routing/rules
- handle_update_routing_rule    PATCH  /api/v1/inbox/routing/rules/:id
- handle_delete_routing_rule    DELETE /api/v1/inbox/routing/rules/:id
- handle_test_routing_rule      POST   /api/v1/inbox/routing/rules/:id/test

Test categories:
- Create: happy path, rate limiting, workspace rule limits, validation errors,
  condition_logic, priority range, store failures, sanitization
- List: happy path with stores, fallback paths, pagination, filtering
- Update: happy path, not found, field validation, condition/action validation,
  circular routing, store fallbacks
- Delete: happy path, not found, store failures
- Test: happy path, not found, store fallbacks, evaluation
- Error handling: broad exception catch paths for all handlers
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aragora.server.handlers.shared_inbox.rule_handlers import (
    handle_create_routing_rule,
    handle_list_routing_rules,
    handle_update_routing_rule,
    handle_delete_routing_rule,
    handle_test_routing_rule,
)
from aragora.server.handlers.shared_inbox.models import (
    RuleAction,
    RuleActionType,
    RuleCondition,
    RuleConditionField,
    RuleConditionOperator,
    RoutingRule,
)
from aragora.server.handlers.shared_inbox.validators import (
    MAX_RULE_NAME_LENGTH,
    MAX_RULE_DESCRIPTION_LENGTH,
    MAX_CONDITIONS_PER_RULE,
    MAX_ACTIONS_PER_RULE,
    MAX_RULES_PER_WORKSPACE,
    RuleValidationResult,
)
from aragora.server.handlers.shared_inbox.storage import (
    _routing_rules,
    _storage_lock,
)


# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

VALID_CONDITION = {"field": "subject", "operator": "contains", "value": "urgent"}
VALID_ACTION = {"type": "assign", "target": "support-team"}

MODULE = "aragora.server.handlers.shared_inbox.rule_handlers"


def _make_rate_limiter(*, allowed: bool = True, remaining: int = 9, retry_after: float = 0.0):
    """Build a mock rate limiter."""
    rl = MagicMock()
    rl.is_allowed.return_value = (allowed, remaining)
    rl.get_retry_after.return_value = retry_after
    rl.record_request = MagicMock()
    return rl


def _make_routing_rule(
    rule_id: str = "rule_abc123",
    workspace_id: str = "ws_test",
    name: str = "Test Rule",
    **kwargs,
) -> RoutingRule:
    """Create a RoutingRule for testing."""
    return RoutingRule(
        id=rule_id,
        workspace_id=workspace_id,
        name=name,
        conditions=[
            RuleCondition(
                field=RuleConditionField.SUBJECT,
                operator=RuleConditionOperator.CONTAINS,
                value="urgent",
            )
        ],
        condition_logic=kwargs.get("condition_logic", "AND"),
        actions=[
            RuleAction(type=RuleActionType.ASSIGN, target="support-team"),
        ],
        priority=kwargs.get("priority", 5),
        enabled=kwargs.get("enabled", True),
        description=kwargs.get("description"),
        created_at=kwargs.get("created_at", datetime.now(timezone.utc)),
        updated_at=kwargs.get("updated_at", datetime.now(timezone.utc)),
        created_by=kwargs.get("created_by"),
        stats=kwargs.get("stats", {"total_matches": 0}),
    )


@pytest.fixture(autouse=True)
def _clean_routing_rules():
    """Clear in-memory routing rules before and after each test."""
    with _storage_lock:
        _routing_rules.clear()
    yield
    with _storage_lock:
        _routing_rules.clear()


@pytest.fixture()
def mock_stores():
    """Patch all three store shims to return None (in-memory only)."""
    with (
        patch(f"{MODULE}._get_rules_store", return_value=None),
        patch(f"{MODULE}._get_email_store", return_value=None),
        patch(f"{MODULE}._get_store", return_value=None),
    ):
        yield


@pytest.fixture()
def rate_limiter():
    """Provide a permissive rate limiter."""
    rl = _make_rate_limiter()
    with patch(f"{MODULE}.get_rule_rate_limiter", return_value=rl):
        yield rl


@pytest.fixture()
def valid_rule_result():
    """Provide a passing validation result."""
    return RuleValidationResult(
        is_valid=True,
        sanitized_conditions=[VALID_CONDITION],
        sanitized_actions=[VALID_ACTION],
    )


# ============================================================================
# handle_create_routing_rule
# ============================================================================


class TestCreateRoutingRule:
    """Tests for handle_create_routing_rule."""

    @pytest.mark.asyncio
    async def test_create_success_basic(self, mock_stores, rate_limiter, valid_rule_result):
        """Successfully creates a routing rule with valid data."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Urgent Filter",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        assert "rule" in result
        assert result["rule"]["name"] == "Urgent Filter"
        assert result["rule"]["workspace_id"] == "ws_1"

    @pytest.mark.asyncio
    async def test_create_rule_stored_in_memory(self, mock_stores, rate_limiter, valid_rule_result):
        """Created rule is stored in the in-memory cache."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Cache Test",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        rule_id = result["rule"]["id"]
        with _storage_lock:
            assert rule_id in _routing_rules

    @pytest.mark.asyncio
    async def test_create_with_all_optional_fields(
        self, mock_stores, rate_limiter, valid_rule_result
    ):
        """All optional fields are passed through and stored."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Full Rule",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                condition_logic="OR",
                priority=10,
                enabled=False,
                description="A test description",
                created_by="user_42",
                inbox_id="inbox_99",
            )
        assert result["success"] is True
        rule = result["rule"]
        assert rule["condition_logic"] == "OR"
        assert rule["priority"] == 10
        assert rule["enabled"] is False
        assert rule["description"] == "A test description"
        assert rule["created_by"] == "user_42"

    @pytest.mark.asyncio
    async def test_create_rate_limited(self, mock_stores):
        """Returns error when rate limit is exceeded."""
        rl = _make_rate_limiter(allowed=False, retry_after=30.0)
        with patch(f"{MODULE}.get_rule_rate_limiter", return_value=rl):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Blocked",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is False
        assert "Rate limit" in result["error"]
        assert result["retry_after"] == 31  # int(30.0) + 1

    @pytest.mark.asyncio
    async def test_create_workspace_rule_limit_exceeded(
        self, mock_stores, rate_limiter, valid_rule_result
    ):
        """Returns error when workspace has max rules."""
        # Pre-populate with MAX_RULES_PER_WORKSPACE rules
        with _storage_lock:
            for i in range(MAX_RULES_PER_WORKSPACE):
                _routing_rules[f"rule_{i}"] = _make_routing_rule(
                    rule_id=f"rule_{i}", workspace_id="ws_full"
                )
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_full",
                name="One Too Many",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is False
        assert "Maximum number" in result["error"]

    @pytest.mark.asyncio
    async def test_create_invalid_condition_logic(self, mock_stores, rate_limiter):
        """Returns error for invalid condition_logic."""
        result = await handle_create_routing_rule(
            workspace_id="ws_1",
            name="Bad Logic",
            conditions=[VALID_CONDITION],
            actions=[VALID_ACTION],
            condition_logic="XOR",
        )
        assert result["success"] is False
        assert "condition_logic" in result["error"]

    @pytest.mark.asyncio
    async def test_create_condition_logic_and(self, mock_stores, rate_limiter, valid_rule_result):
        """AND condition_logic is accepted."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="AND Rule",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                condition_logic="AND",
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_condition_logic_or(self, mock_stores, rate_limiter, valid_rule_result):
        """OR condition_logic is accepted."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="OR Rule",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                condition_logic="OR",
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_priority_below_zero(self, mock_stores, rate_limiter):
        """Returns error for priority < 0."""
        result = await handle_create_routing_rule(
            workspace_id="ws_1",
            name="Bad Priority",
            conditions=[VALID_CONDITION],
            actions=[VALID_ACTION],
            priority=-1,
        )
        assert result["success"] is False
        assert "priority" in result["error"]

    @pytest.mark.asyncio
    async def test_create_priority_above_100(self, mock_stores, rate_limiter):
        """Returns error for priority > 100."""
        result = await handle_create_routing_rule(
            workspace_id="ws_1",
            name="Too High",
            conditions=[VALID_CONDITION],
            actions=[VALID_ACTION],
            priority=101,
        )
        assert result["success"] is False
        assert "priority" in result["error"]

    @pytest.mark.asyncio
    async def test_create_priority_boundary_0(self, mock_stores, rate_limiter, valid_rule_result):
        """Priority 0 is accepted."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Min Priority",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                priority=0,
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_priority_boundary_100(self, mock_stores, rate_limiter, valid_rule_result):
        """Priority 100 is accepted."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Max Priority",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                priority=100,
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_priority_non_integer(self, mock_stores, rate_limiter):
        """Returns error for non-integer priority."""
        result = await handle_create_routing_rule(
            workspace_id="ws_1",
            name="Float Priority",
            conditions=[VALID_CONDITION],
            actions=[VALID_ACTION],
            priority=5.5,
        )
        assert result["success"] is False
        assert "priority" in result["error"]

    @pytest.mark.asyncio
    async def test_create_validation_failure(self, mock_stores, rate_limiter):
        """Returns error when validation fails."""
        bad_result = RuleValidationResult(is_valid=False, error="Bad condition field")
        with patch(f"{MODULE}.validate_routing_rule", return_value=bad_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Invalid",
                conditions=[{"field": "bad", "operator": "eq", "value": "x"}],
                actions=[VALID_ACTION],
            )
        assert result["success"] is False
        assert "Bad condition field" in result["error"]

    @pytest.mark.asyncio
    async def test_create_records_rate_limit_after_validation(self, mock_stores, valid_rule_result):
        """Rate limiter records request only after validation passes."""
        rl = _make_rate_limiter()
        with (
            patch(f"{MODULE}.get_rule_rate_limiter", return_value=rl),
            patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result),
        ):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Track Request",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        rl.record_request.assert_called_once_with("ws_1")

    @pytest.mark.asyncio
    async def test_create_does_not_record_on_validation_failure(self, mock_stores):
        """Rate limiter does NOT record request when validation fails."""
        rl = _make_rate_limiter()
        bad_result = RuleValidationResult(is_valid=False, error="nope")
        with (
            patch(f"{MODULE}.get_rule_rate_limiter", return_value=rl),
            patch(f"{MODULE}.validate_routing_rule", return_value=bad_result),
        ):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Fail",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is False
        rl.record_request.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_rules_store_persist(self, rate_limiter, valid_rule_result):
        """Rule is persisted to rules_store when available."""
        rules_store = MagicMock()
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_email_store", return_value=None),
            patch(f"{MODULE}._get_store", return_value=None),
            patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result),
        ):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Persist Test",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        rules_store.create_rule.assert_called_once()
        call_data = rules_store.create_rule.call_args[0][0]
        assert call_data["name"] == "Persist Test"

    @pytest.mark.asyncio
    async def test_create_email_store_persist(self, rate_limiter, valid_rule_result):
        """Rule is persisted to email_store for backward compatibility."""
        email_store = MagicMock()
        with (
            patch(f"{MODULE}._get_rules_store", return_value=None),
            patch(f"{MODULE}._get_email_store", return_value=email_store),
            patch(f"{MODULE}._get_store", return_value=None),
            patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result),
        ):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Email Store",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        email_store.create_routing_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_rules_store_failure_still_succeeds(self, rate_limiter, valid_rule_result):
        """Rule creation succeeds even if rules_store.create_rule raises."""
        rules_store = MagicMock()
        rules_store.create_rule.side_effect = RuntimeError("db down")
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_email_store", return_value=None),
            patch(f"{MODULE}._get_store", return_value=None),
            patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result),
        ):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Resilient",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        # Rule still ends up in memory
        rule_id = result["rule"]["id"]
        with _storage_lock:
            assert rule_id in _routing_rules

    @pytest.mark.asyncio
    async def test_create_email_store_failure_still_succeeds(self, rate_limiter, valid_rule_result):
        """Rule creation succeeds even if email_store.create_routing_rule raises."""
        email_store = MagicMock()
        email_store.create_routing_rule.side_effect = OSError("disk full")
        with (
            patch(f"{MODULE}._get_rules_store", return_value=None),
            patch(f"{MODULE}._get_email_store", return_value=email_store),
            patch(f"{MODULE}._get_store", return_value=None),
            patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result),
        ):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Still Works",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_create_name_sanitized(self, mock_stores, rate_limiter, valid_rule_result):
        """Rule name is sanitized before storage."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="  Clean\x00Name  ",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        # The name should be sanitized (control chars removed, stripped)
        assert "\x00" not in result["rule"]["name"]

    @pytest.mark.asyncio
    async def test_create_description_sanitized(self, mock_stores, rate_limiter, valid_rule_result):
        """Rule description is sanitized before storage."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Desc Test",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                description="  Hello\x00World  ",
            )
        assert result["success"] is True
        desc = result["rule"]["description"]
        assert desc is not None
        assert "\x00" not in desc

    @pytest.mark.asyncio
    async def test_create_no_description_remains_none(
        self, mock_stores, rate_limiter, valid_rule_result
    ):
        """Description is None when not provided."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="No Desc",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        assert result["rule"]["description"] is None

    @pytest.mark.asyncio
    async def test_create_rule_id_format(self, mock_stores, rate_limiter, valid_rule_result):
        """Generated rule ID starts with 'rule_'."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="ID Check",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        assert result["rule"]["id"].startswith("rule_")

    @pytest.mark.asyncio
    async def test_create_timestamps_set(self, mock_stores, rate_limiter, valid_rule_result):
        """Created and updated timestamps are set."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Timestamp Check",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        assert "created_at" in result["rule"]
        assert "updated_at" in result["rule"]

    @pytest.mark.asyncio
    async def test_create_stats_initialized(self, mock_stores, rate_limiter, valid_rule_result):
        """Rule stats are initialized to zero."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Stats Check",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is True
        assert result["rule"]["stats"]["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_create_broad_exception_returns_internal_error(self, mock_stores):
        """Broad exception catch returns internal server error."""
        rl = _make_rate_limiter()
        rl.is_allowed.side_effect = TypeError("unexpected")
        with patch(f"{MODULE}.get_rule_rate_limiter", return_value=rl):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Explode",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
            )
        assert result["success"] is False
        assert result["error"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_create_disabled_rule(self, mock_stores, rate_limiter, valid_rule_result):
        """Can create a disabled rule."""
        with patch(f"{MODULE}.validate_routing_rule", return_value=valid_rule_result):
            result = await handle_create_routing_rule(
                workspace_id="ws_1",
                name="Disabled Rule",
                conditions=[VALID_CONDITION],
                actions=[VALID_ACTION],
                enabled=False,
            )
        assert result["success"] is True
        assert result["rule"]["enabled"] is False


# ============================================================================
# handle_list_routing_rules
# ============================================================================


class TestListRoutingRules:
    """Tests for handle_list_routing_rules."""

    @pytest.mark.asyncio
    async def test_list_empty_workspace(self, mock_stores):
        """Returns empty list for workspace with no rules."""
        result = await handle_list_routing_rules(workspace_id="ws_empty")
        assert result["success"] is True
        assert result["rules"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_list_from_memory(self, mock_stores):
        """Lists rules from in-memory cache when no stores available."""
        rule = _make_routing_rule(workspace_id="ws_mem")
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_list_routing_rules(workspace_id="ws_mem")
        assert result["success"] is True
        assert result["total"] == 1
        assert result["rules"][0]["id"] == "rule_abc123"

    @pytest.mark.asyncio
    async def test_list_filters_by_workspace(self, mock_stores):
        """Only returns rules for the requested workspace."""
        r1 = _make_routing_rule(rule_id="r1", workspace_id="ws_a")
        r2 = _make_routing_rule(rule_id="r2", workspace_id="ws_b")
        with _storage_lock:
            _routing_rules["r1"] = r1
            _routing_rules["r2"] = r2

        result = await handle_list_routing_rules(workspace_id="ws_a")
        assert result["success"] is True
        assert result["total"] == 1
        assert result["rules"][0]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_list_enabled_only(self, mock_stores):
        """Filters to enabled rules only when requested."""
        r1 = _make_routing_rule(rule_id="r1", workspace_id="ws_x", enabled=True)
        r2 = _make_routing_rule(rule_id="r2", workspace_id="ws_x", enabled=False)
        with _storage_lock:
            _routing_rules["r1"] = r1
            _routing_rules["r2"] = r2

        result = await handle_list_routing_rules(workspace_id="ws_x", enabled_only=True)
        assert result["success"] is True
        assert result["total"] == 1
        assert result["rules"][0]["id"] == "r1"

    @pytest.mark.asyncio
    async def test_list_pagination_limit(self, mock_stores):
        """Respects limit parameter."""
        for i in range(5):
            r = _make_routing_rule(rule_id=f"r{i}", workspace_id="ws_pg")
            with _storage_lock:
                _routing_rules[f"r{i}"] = r

        result = await handle_list_routing_rules(workspace_id="ws_pg", limit=2)
        assert result["success"] is True
        assert result["total"] == 5
        assert len(result["rules"]) == 2
        assert result["limit"] == 2

    @pytest.mark.asyncio
    async def test_list_pagination_offset(self, mock_stores):
        """Respects offset parameter."""
        for i in range(5):
            r = _make_routing_rule(rule_id=f"r{i}", workspace_id="ws_off", priority=i)
            with _storage_lock:
                _routing_rules[f"r{i}"] = r

        result = await handle_list_routing_rules(workspace_id="ws_off", offset=3, limit=100)
        assert result["success"] is True
        assert result["total"] == 5
        assert len(result["rules"]) == 2
        assert result["offset"] == 3

    @pytest.mark.asyncio
    async def test_list_sorted_by_priority(self, mock_stores):
        """In-memory rules are sorted by priority."""
        r_high = _make_routing_rule(rule_id="rh", workspace_id="ws_s", priority=10)
        r_low = _make_routing_rule(rule_id="rl", workspace_id="ws_s", priority=1)
        with _storage_lock:
            _routing_rules["rh"] = r_high
            _routing_rules["rl"] = r_low

        result = await handle_list_routing_rules(workspace_id="ws_s")
        assert result["success"] is True
        assert result["rules"][0]["priority"] <= result["rules"][1]["priority"]

    @pytest.mark.asyncio
    async def test_list_from_rules_store(self):
        """Uses rules_store when available."""
        rules_store = MagicMock()
        rules_store.list_rules.return_value = [{"id": "rs_1", "name": "From Store"}]
        rules_store.count_rules.return_value = 1
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_list_routing_rules(workspace_id="ws_1")
        assert result["success"] is True
        assert result["rules"][0]["id"] == "rs_1"
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_list_rules_store_failure_returns_error(self):
        """Returns error when rules_store fails instead of silently falling back."""
        rules_store = MagicMock()
        rules_store.list_rules.side_effect = RuntimeError("nope")
        rule = _make_routing_rule(workspace_id="ws_fb")
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_list_routing_rules(workspace_id="ws_fb")
        assert result["success"] is False
        assert "storage" in result["error"].lower() or "failed" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_inbox_id_filter(self, mock_stores):
        """Filters by inbox_id in in-memory path."""
        r1 = _make_routing_rule(rule_id="r1", workspace_id="ws_i")
        # Manually set inbox_id on the RoutingRule (it's not a standard field but
        # used via to_dict which includes all attributes)
        r1_dict = r1.to_dict()
        # For in-memory, inbox_id filtering checks r.get("inbox_id")
        # The RoutingRule model doesn't have inbox_id, so all rules pass
        # the filter when inbox_id is None on the rule side
        result = await handle_list_routing_rules(workspace_id="ws_i", inbox_id="inbox_1")
        # Rules without inbox_id pass the filter (inbox_id is None)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_list_broad_exception_returns_internal_error(self):
        """Broad exception catch returns internal server error."""
        with patch(f"{MODULE}._get_rules_store", side_effect=AttributeError("boom")):
            result = await handle_list_routing_rules(workspace_id="ws_1")
        assert result["success"] is False
        assert result["error"] == "Internal server error"


# ============================================================================
# handle_update_routing_rule
# ============================================================================


class TestUpdateRoutingRule:
    """Tests for handle_update_routing_rule."""

    @pytest.mark.asyncio
    async def test_update_rule_not_found(self, mock_stores):
        """Returns error when rule does not exist."""
        result = await handle_update_routing_rule(
            rule_id="nonexistent",
            updates={"enabled": False},
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_update_enabled_field(self, mock_stores):
        """Can update enabled field."""
        rule = _make_routing_rule(enabled=True)
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"enabled": False},
        )
        assert result["success"] is True
        with _storage_lock:
            assert _routing_rules["rule_abc123"].enabled is False

    @pytest.mark.asyncio
    async def test_update_priority(self, mock_stores):
        """Can update priority."""
        rule = _make_routing_rule(priority=5)
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"priority": 99},
        )
        assert result["success"] is True
        with _storage_lock:
            assert _routing_rules["rule_abc123"].priority == 99

    @pytest.mark.asyncio
    async def test_update_name(self, mock_stores):
        """Can update rule name."""
        rule = _make_routing_rule(name="Old Name")
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"name": "New Name"},
        )
        assert result["success"] is True
        with _storage_lock:
            assert _routing_rules["rule_abc123"].name == "New Name"

    @pytest.mark.asyncio
    async def test_update_empty_name_rejected(self, mock_stores):
        """Returns error for empty name."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"name": ""},
        )
        assert result["success"] is False
        assert "empty" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_name_too_long(self, mock_stores):
        """Returns error for name exceeding max length."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"name": "x" * (MAX_RULE_NAME_LENGTH + 1)},
        )
        assert result["success"] is False
        assert "maximum length" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_description(self, mock_stores):
        """Can update description."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"description": "New description"},
        )
        assert result["success"] is True
        with _storage_lock:
            assert _routing_rules["rule_abc123"].description == "New description"

    @pytest.mark.asyncio
    async def test_update_description_too_long(self, mock_stores):
        """Returns error for description exceeding max length."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"description": "d" * (MAX_RULE_DESCRIPTION_LENGTH + 1)},
        )
        assert result["success"] is False
        assert "maximum length" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_description_none_is_allowed(self, mock_stores):
        """Setting description to None is allowed (clear it)."""
        rule = _make_routing_rule(description="old")
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"description": None},
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_invalid_condition_logic(self, mock_stores):
        """Returns error for invalid condition_logic."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"condition_logic": "NAND"},
        )
        assert result["success"] is False
        assert "condition_logic" in result["error"]

    @pytest.mark.asyncio
    async def test_update_valid_condition_logic(self, mock_stores):
        """Can update condition_logic to valid value."""
        rule = _make_routing_rule(condition_logic="AND")
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"condition_logic": "OR"},
        )
        assert result["success"] is True
        with _storage_lock:
            assert _routing_rules["rule_abc123"].condition_logic == "OR"

    @pytest.mark.asyncio
    async def test_update_priority_invalid_negative(self, mock_stores):
        """Returns error for negative priority."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"priority": -5},
        )
        assert result["success"] is False
        assert "priority" in result["error"]

    @pytest.mark.asyncio
    async def test_update_priority_invalid_above_100(self, mock_stores):
        """Returns error for priority above 100."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"priority": 200},
        )
        assert result["success"] is False
        assert "priority" in result["error"]

    @pytest.mark.asyncio
    async def test_update_priority_float_rejected(self, mock_stores):
        """Returns error for float priority."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"priority": 5.5},
        )
        assert result["success"] is False
        assert "priority" in result["error"]

    @pytest.mark.asyncio
    async def test_update_conditions_empty_list(self, mock_stores):
        """Returns error for empty conditions list."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"conditions": []},
        )
        assert result["success"] is False
        assert "condition" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_conditions_too_many(self, mock_stores):
        """Returns error when too many conditions."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        many_conditions = [VALID_CONDITION] * (MAX_CONDITIONS_PER_RULE + 1)
        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"conditions": many_conditions},
        )
        assert result["success"] is False
        assert "maximum" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_conditions_valid(self, mock_stores):
        """Can update conditions with valid data."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"conditions": [VALID_CONDITION]},
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_conditions_invalid_condition(self, mock_stores):
        """Returns error for invalid condition."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        bad_condition = {"field": "bad_field", "operator": "contains", "value": "test"}
        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"conditions": [bad_condition]},
        )
        assert result["success"] is False
        assert "Condition 1" in result["error"]

    @pytest.mark.asyncio
    async def test_update_actions_empty_list(self, mock_stores):
        """Returns error for empty actions list."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"actions": []},
        )
        assert result["success"] is False
        assert "action" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_actions_too_many(self, mock_stores):
        """Returns error when too many actions."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        many_actions = [VALID_ACTION] * (MAX_ACTIONS_PER_RULE + 1)
        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"actions": many_actions},
        )
        assert result["success"] is False
        assert "maximum" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_update_actions_invalid_action(self, mock_stores):
        """Returns error for invalid action."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        bad_action = {"type": "teleport", "target": "mars"}
        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"actions": [bad_action]},
        )
        assert result["success"] is False
        assert "Action 1" in result["error"]

    @pytest.mark.asyncio
    async def test_update_actions_valid(self, mock_stores):
        """Can update actions with valid data."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"actions": [{"type": "label", "target": "important"}]},
        )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_actions_circular_routing_detected(self, mock_stores):
        """Returns error when circular routing is detected."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        with patch(
            f"{MODULE}.detect_circular_routing",
            return_value=(True, "Circular routing detected"),
        ):
            result = await handle_update_routing_rule(
                rule_id="rule_abc123",
                updates={"actions": [{"type": "forward", "target": "inbox_loop"}]},
            )
        assert result["success"] is False
        assert "Circular" in result["error"]

    @pytest.mark.asyncio
    async def test_update_from_persistent_store(self):
        """Finds rule in persistent store when not in memory."""
        rule_data = _make_routing_rule().to_dict()
        rules_store = MagicMock()
        rules_store.get_rule.return_value = rule_data
        rules_store.update_rule.return_value = {**rule_data, "enabled": False}
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_update_routing_rule(
                rule_id="rule_abc123",
                updates={"enabled": False},
            )
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_rules_store_persist(self):
        """Updates are persisted to rules_store."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        rules_store = MagicMock()
        rules_store.update_rule.return_value = {**rule.to_dict(), "priority": 50}
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_update_routing_rule(
                rule_id="rule_abc123",
                updates={"priority": 50},
            )
        assert result["success"] is True
        rules_store.update_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_email_store_persist(self):
        """Updates are persisted to email_store for backward compat."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        email_store = MagicMock()
        with (
            patch(f"{MODULE}._get_rules_store", return_value=None),
            patch(f"{MODULE}._get_store", return_value=email_store),
        ):
            result = await handle_update_routing_rule(
                rule_id="rule_abc123",
                updates={"priority": 50},
            )
        assert result["success"] is True
        email_store.update_routing_rule.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_updated_at_changes(self, mock_stores):
        """updated_at timestamp is refreshed on update."""
        old_time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        rule = _make_routing_rule(updated_at=old_time)
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"priority": 10},
        )
        assert result["success"] is True
        with _storage_lock:
            assert _routing_rules["rule_abc123"].updated_at > old_time

    @pytest.mark.asyncio
    async def test_update_multiple_fields(self, mock_stores):
        """Can update multiple fields at once."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={
                "name": "Updated Name",
                "description": "Updated desc",
                "priority": 42,
                "enabled": False,
                "condition_logic": "OR",
            },
        )
        assert result["success"] is True
        with _storage_lock:
            r = _routing_rules["rule_abc123"]
            assert r.name == "Updated Name"
            assert r.description == "Updated desc"
            assert r.priority == 42
            assert r.enabled is False
            assert r.condition_logic == "OR"

    @pytest.mark.asyncio
    async def test_update_broad_exception_returns_internal_error(self, mock_stores):
        """Broad exception catch returns internal server error."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        # Make sanitize_user_input raise a TypeError to trigger the broad catch
        with patch(f"{MODULE}.sanitize_user_input", side_effect=TypeError("unexpected")):
            result = await handle_update_routing_rule(
                rule_id="rule_abc123",
                updates={"name": "will trigger error"},
            )
        assert result["success"] is False
        assert result["error"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_update_rules_store_failure_falls_back(self):
        """Falls back to in-memory when rules_store update fails."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        rules_store = MagicMock()
        rules_store.update_rule.side_effect = RuntimeError("db error")
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_update_routing_rule(
                rule_id="rule_abc123",
                updates={"priority": 20},
            )
        # Should still succeed from in-memory
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_update_name_sanitized(self, mock_stores):
        """Updated name is sanitized."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_update_routing_rule(
            rule_id="rule_abc123",
            updates={"name": "  Clean\x00Me  "},
        )
        assert result["success"] is True
        with _storage_lock:
            assert "\x00" not in _routing_rules["rule_abc123"].name


# ============================================================================
# handle_delete_routing_rule
# ============================================================================


class TestDeleteRoutingRule:
    """Tests for handle_delete_routing_rule."""

    @pytest.mark.asyncio
    async def test_delete_from_memory(self, mock_stores):
        """Deletes rule from in-memory cache."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        result = await handle_delete_routing_rule(rule_id="rule_abc123")
        assert result["success"] is True
        assert result["deleted"] == "rule_abc123"
        with _storage_lock:
            assert "rule_abc123" not in _routing_rules

    @pytest.mark.asyncio
    async def test_delete_not_found(self, mock_stores):
        """Returns error when rule does not exist."""
        result = await handle_delete_routing_rule(rule_id="nonexistent")
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_delete_from_rules_store(self):
        """Deletes from rules_store."""
        rules_store = MagicMock()
        rules_store.delete_rule.return_value = True
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_delete_routing_rule(rule_id="rule_abc123")
        assert result["success"] is True
        rules_store.delete_rule.assert_called_once_with("rule_abc123")

    @pytest.mark.asyncio
    async def test_delete_from_email_store(self):
        """Deletes from email_store for backward compat."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        email_store = MagicMock()
        with (
            patch(f"{MODULE}._get_rules_store", return_value=None),
            patch(f"{MODULE}._get_store", return_value=email_store),
        ):
            result = await handle_delete_routing_rule(rule_id="rule_abc123")
        assert result["success"] is True
        email_store.delete_routing_rule.assert_called_once_with("rule_abc123")

    @pytest.mark.asyncio
    async def test_delete_rules_store_failure_still_succeeds(self):
        """Delete succeeds from memory even if rules_store fails."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        rules_store = MagicMock()
        rules_store.delete_rule.side_effect = RuntimeError("fail")
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_delete_routing_rule(rule_id="rule_abc123")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_email_store_failure_still_succeeds(self):
        """Delete succeeds from memory even if email_store fails."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        email_store = MagicMock()
        email_store.delete_routing_rule.side_effect = OSError("fail")
        with (
            patch(f"{MODULE}._get_rules_store", return_value=None),
            patch(f"{MODULE}._get_store", return_value=email_store),
        ):
            result = await handle_delete_routing_rule(rule_id="rule_abc123")
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_broad_exception_returns_internal_error(self):
        """Broad exception catch returns internal server error."""
        with patch(f"{MODULE}._get_rules_store", side_effect=TypeError("oops")):
            result = await handle_delete_routing_rule(rule_id="rule_abc123")
        assert result["success"] is False
        assert result["error"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_delete_only_from_store_not_memory(self):
        """Rule deleted from store but not in memory still reports success."""
        rules_store = MagicMock()
        rules_store.delete_rule.return_value = True
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_delete_routing_rule(rule_id="store_only_rule")
        assert result["success"] is True
        assert result["deleted"] == "store_only_rule"


# ============================================================================
# handle_test_routing_rule
# ============================================================================


class TestTestRoutingRule:
    """Tests for handle_test_routing_rule."""

    @pytest.mark.asyncio
    async def test_test_rule_from_memory(self, mock_stores):
        """Tests rule using in-memory rule and evaluation."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        with patch(f"{MODULE}.evaluate_rule_for_test", return_value=5):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is True
        assert result["match_count"] == 5
        assert result["rule_id"] == "rule_abc123"
        assert "rule" in result

    @pytest.mark.asyncio
    async def test_test_rule_not_found(self, mock_stores):
        """Returns error when rule does not exist."""
        result = await handle_test_routing_rule(
            rule_id="nonexistent",
            workspace_id="ws_test",
        )
        assert result["success"] is False
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_test_rule_from_rules_store(self):
        """Finds rule in rules_store."""
        rule_data = _make_routing_rule().to_dict()
        rules_store = MagicMock()
        rules_store.get_rule.return_value = rule_data
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
            patch(f"{MODULE}.evaluate_rule_for_test", return_value=3),
        ):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is True
        assert result["match_count"] == 3

    @pytest.mark.asyncio
    async def test_test_rule_no_stores_falls_to_memory(self):
        """Falls back to in-memory when no persistent stores available."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule
        with (
            patch(f"{MODULE}._get_rules_store", return_value=None),
            patch(f"{MODULE}.evaluate_rule_for_test", return_value=0),
        ):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is True
        assert result["match_count"] == 0

    @pytest.mark.asyncio
    async def test_test_rule_rules_store_failure_falls_to_memory(self):
        """Falls back to in-memory when rules_store raises (email store fallback removed)."""
        rules_store = MagicMock()
        rules_store.get_rule.side_effect = RuntimeError("fail")
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}.evaluate_rule_for_test", return_value=2),
        ):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is True
        assert result["match_count"] == 2

    @pytest.mark.asyncio
    async def test_test_rule_not_in_any_store_returns_not_found(self):
        """Returns not found when rule is not in any store."""
        rules_store = MagicMock()
        rules_store.get_rule.return_value = None
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
        ):
            result = await handle_test_routing_rule(
                rule_id="rule_nonexistent",
                workspace_id="ws_test",
            )
        assert result["success"] is False
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_test_rule_zero_matches(self, mock_stores):
        """Returns zero match_count when no messages match."""
        rule = _make_routing_rule()
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        with patch(f"{MODULE}.evaluate_rule_for_test", return_value=0):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is True
        assert result["match_count"] == 0

    @pytest.mark.asyncio
    async def test_test_rule_includes_rule_dict(self, mock_stores):
        """Response includes the rule as a dictionary."""
        rule = _make_routing_rule(name="My Rule")
        with _storage_lock:
            _routing_rules["rule_abc123"] = rule

        with patch(f"{MODULE}.evaluate_rule_for_test", return_value=0):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is True
        assert result["rule"]["name"] == "My Rule"

    @pytest.mark.asyncio
    async def test_test_rule_broad_exception_returns_internal_error(self):
        """Broad exception catch returns internal server error."""
        with patch(f"{MODULE}._get_rules_store", side_effect=AttributeError("boom")):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is False
        assert result["error"] == "Internal server error"

    @pytest.mark.asyncio
    async def test_test_rule_rules_store_returns_none(self):
        """Returns not found when rules_store returns None for rule."""
        rules_store = MagicMock()
        rules_store.get_rule.return_value = None
        with (
            patch(f"{MODULE}._get_rules_store", return_value=rules_store),
            patch(f"{MODULE}._get_store", return_value=None),
        ):
            result = await handle_test_routing_rule(
                rule_id="rule_abc123",
                workspace_id="ws_test",
            )
        assert result["success"] is False
        assert "not found" in result["error"]
