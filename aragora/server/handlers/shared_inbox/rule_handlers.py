"""
HTTP handlers for routing rule management.

Handles rule creation, listing, updating, deletion, and testing.
"""

from __future__ import annotations

import logging
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

from aragora.server.validation.security import sanitize_user_input
from aragora.server.handlers.utils.decorators import require_permission

from .models import (
    RuleAction,
    RuleCondition,
    RoutingRule,
)
from .storage import (
    _get_email_store as _get_email_store_impl,
    _get_rules_store as _get_rules_store_impl,
    _get_store as _get_store_impl,
    _routing_rules,
    _storage_lock,
)
from .validators import (
    MAX_RULE_NAME_LENGTH,
    MAX_RULE_DESCRIPTION_LENGTH,
    MAX_CONDITIONS_PER_RULE,
    MAX_ACTIONS_PER_RULE,
    MAX_RULES_PER_WORKSPACE,
    get_rule_rate_limiter,
    validate_rule_condition,
    validate_rule_action,
    detect_circular_routing,
    validate_routing_rule,
)
from .rules_engine import evaluate_rule_for_test

logger = logging.getLogger(__name__)


# =============================================================================
# Store shims for test compatibility
# Tests patch aragora.server.handlers._shared_inbox_handler._get_store
# =============================================================================


def _get_store() -> Any:
    """Get store with test patch support."""
    module = sys.modules.get("aragora.server.handlers._shared_inbox_handler")
    if module is not None:
        patched = getattr(module, "_get_store", None)
        if patched is not None and patched is not _get_store:
            return patched()
    return _get_store_impl()


def _get_rules_store() -> Any:
    """Get rules store with test patch support."""
    module = sys.modules.get("aragora.server.handlers._shared_inbox_handler")
    if module is not None:
        patched = getattr(module, "_get_rules_store", None)
        if patched is not None and patched is not _get_rules_store:
            return patched()
    return _get_rules_store_impl()


def _get_email_store() -> Any:
    """Get email store with test patch support."""
    module = sys.modules.get("aragora.server.handlers._shared_inbox_handler")
    if module is not None:
        patched = getattr(module, "_get_email_store", None)
        if patched is not None and patched is not _get_email_store:
            return patched()
    return _get_email_store_impl()


@require_permission("inbox:write")
async def handle_create_routing_rule(
    workspace_id: str,
    name: str,
    conditions: list[dict[str, Any]],
    actions: list[dict[str, Any]],
    condition_logic: str = "AND",
    priority: int = 5,
    enabled: bool = True,
    description: str | None = None,
    created_by: str | None = None,
    inbox_id: str | None = None,
) -> dict[str, Any]:
    """
    Create a routing rule with comprehensive input validation.

    POST /api/v1/inbox/routing/rules
    {
        "workspace_id": "ws_123",
        "name": "Urgent Customer Issues",
        "conditions": [
            {"field": "subject", "operator": "contains", "value": "urgent"}
        ],
        "condition_logic": "AND",
        "actions": [
            {"type": "assign", "target": "support-team"},
            {"type": "label", "target": "urgent"}
        ],
        "priority": 1
    }

    Security validations performed:
    - Rate limiting per workspace (10 rules/minute)
    - Rule name and description length limits
    - Condition field whitelist validation
    - ReDoS protection for regex patterns in MATCHES operator
    - Circular routing detection for forward actions
    - Maximum conditions/actions per rule limits
    """
    try:
        rate_limiter = get_rule_rate_limiter()

        # Rate limiting check
        is_allowed, remaining = rate_limiter.is_allowed(workspace_id)
        if not is_allowed:
            retry_after = rate_limiter.get_retry_after(workspace_id)
            logger.warning(
                f"[SharedInbox] Rate limit exceeded for workspace {workspace_id}. "
                f"Retry after {retry_after:.1f}s"
            )
            return {
                "success": False,
                "error": f"Rate limit exceeded. Try again in {int(retry_after) + 1} seconds.",
                "retry_after": int(retry_after) + 1,
            }

        # Check workspace rule count limit
        with _storage_lock:
            workspace_rule_count = sum(
                1 for r in _routing_rules.values() if r.workspace_id == workspace_id
            )
        if workspace_rule_count >= MAX_RULES_PER_WORKSPACE:
            return {
                "success": False,
                "error": f"Maximum number of rules ({MAX_RULES_PER_WORKSPACE}) reached for this workspace",
            }

        # Validate condition_logic
        if condition_logic not in ("AND", "OR"):
            return {
                "success": False,
                "error": "condition_logic must be 'AND' or 'OR'",
            }

        # Validate priority
        if not isinstance(priority, int) or priority < 0 or priority > 100:
            return {
                "success": False,
                "error": "priority must be an integer between 0 and 100",
            }

        # Get existing rules for circular routing detection
        with _storage_lock:
            existing_rules = list(_routing_rules.values())

        # Comprehensive input validation
        validation_result = validate_routing_rule(
            name=name,
            conditions=conditions,
            actions=actions,
            workspace_id=workspace_id,
            description=description,
            existing_rules=existing_rules,
            check_circular=True,
        )

        if not validation_result.is_valid:
            logger.warning(
                "[SharedInbox] Rule validation failed for workspace %s: %s",
                workspace_id,
                validation_result.error,
            )
            return {
                "success": False,
                "error": validation_result.error,
            }

        # Use sanitized conditions and actions
        validated_conditions = validation_result.sanitized_conditions
        validated_actions = validation_result.sanitized_actions

        # Record the rate limit request (after validation passes)
        rate_limiter.record_request(workspace_id)

        rule_id = f"rule_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # Sanitize name and description
        sanitized_name = sanitize_user_input(name, max_length=MAX_RULE_NAME_LENGTH)
        sanitized_description = None
        if description:
            sanitized_description = sanitize_user_input(
                description, max_length=MAX_RULE_DESCRIPTION_LENGTH
            )

        # Prepare rule data for persistent storage
        rule_data = {
            "id": rule_id,
            "name": sanitized_name,
            "workspace_id": workspace_id,
            "inbox_id": inbox_id,
            "conditions": validated_conditions,
            "condition_logic": condition_logic,
            "actions": validated_actions,
            "priority": priority,
            "enabled": enabled,
            "description": sanitized_description,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "created_by": created_by,
            "stats": {"total_matches": 0, "matched": 0, "applied": 0},
        }

        # Use RulesStore for persistent storage (primary)
        rules_store = _get_rules_store()
        if rules_store:
            try:
                rules_store.create_rule(rule_data)
                logger.info(
                    "[SharedInbox] Created routing rule %s: %s (persistent)",
                    rule_id,
                    sanitized_name,
                )
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to persist rule to RulesStore: %s", e)
                # Fall through to in-memory storage

        # Also persist to email store for backward compatibility
        email_store = _get_email_store()
        if email_store:
            try:
                email_store.create_routing_rule(
                    rule_id=rule_id,
                    workspace_id=workspace_id,
                    name=sanitized_name,
                    conditions=validated_conditions,
                    actions=validated_actions,
                    priority=priority,
                    enabled=enabled,
                    description=sanitized_description,
                    inbox_id=inbox_id,
                )
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to persist rule to email store: %s", e)

        # Build in-memory RoutingRule object for cache
        rule = RoutingRule(
            id=rule_id,
            workspace_id=workspace_id,
            name=sanitized_name,
            conditions=[RuleCondition.from_dict(c) for c in validated_conditions],
            condition_logic=condition_logic,
            actions=[RuleAction.from_dict(a) for a in validated_actions],
            priority=priority,
            enabled=enabled,
            description=sanitized_description,
            created_at=now,
            updated_at=now,
            created_by=created_by,
            stats={"total_matches": 0},
        )

        # Keep in-memory cache for fast reads
        with _storage_lock:
            _routing_rules[rule_id] = rule

        logger.info(
            "[SharedInbox] Created routing rule %s for workspace %s (remaining rate limit: %s)",
            rule_id,
            workspace_id,
            remaining - 1,
        )

        return {
            "success": True,
            "rule": rule.to_dict(),
        }

    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OSError,
        RuntimeError,
    ) as e:  # broad catch: last-resort handler
        logger.exception("Failed to create routing rule: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:read")
async def handle_list_routing_rules(
    workspace_id: str,
    enabled_only: bool = False,
    limit: int = 100,
    offset: int = 0,
    inbox_id: str | None = None,
) -> dict[str, Any]:
    """
    List routing rules for a workspace.

    GET /api/v1/inbox/routing/rules?workspace_id=ws_123
    """
    try:
        # Try RulesStore first (primary persistent storage)
        rules_store = _get_rules_store()
        if rules_store:
            try:
                rules = rules_store.list_rules(
                    workspace_id=workspace_id,
                    inbox_id=inbox_id,
                    enabled_only=enabled_only,
                    limit=limit,
                    offset=offset,
                )
                total = rules_store.count_rules(
                    workspace_id=workspace_id,
                    inbox_id=inbox_id,
                    enabled_only=enabled_only,
                )
                return {
                    "success": True,
                    "rules": rules,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                }
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.error("[SharedInbox] Failed to load rules from RulesStore: %s", e)
                return {
                    "success": False,
                    "error": "Storage operation failed",
                }

        # No persistent store available -- use in-memory
        with _storage_lock:
            all_rules = [
                rule.to_dict()
                for rule in sorted(_routing_rules.values(), key=lambda r: r.priority)
                if rule.workspace_id == workspace_id
            ]
            if inbox_id:
                all_rules = [
                    r
                    for r in all_rules
                    if r.get("inbox_id") == inbox_id or r.get("inbox_id") is None
                ]
            if enabled_only:
                all_rules = [r for r in all_rules if r.get("enabled", True)]
            total = len(all_rules)
            rules = all_rules[offset : offset + limit]

        return {
            "success": True,
            "rules": rules,
            "total": total,
            "limit": limit,
            "offset": offset,
        }

    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OSError,
        RuntimeError,
    ) as e:  # broad catch: last-resort handler
        logger.exception("Failed to list routing rules: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:write")
async def handle_update_routing_rule(
    rule_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """
    Update a routing rule with input validation.

    PATCH /api/v1/inbox/routing/rules/:id
    {
        "enabled": false,
        "priority": 2
    }

    Security validations performed:
    - Name and description length limits
    - Condition field whitelist validation
    - ReDoS protection for regex patterns
    - Circular routing detection for forward actions
    - Priority range validation
    - Condition logic validation
    """
    try:
        # Get existing rule to validate updates against
        existing_rule = None
        workspace_id = None

        with _storage_lock:
            existing_rule = _routing_rules.get(rule_id)
            if existing_rule:
                workspace_id = existing_rule.workspace_id

        # If not in memory, try persistent stores
        if not existing_rule:
            rules_store = _get_rules_store()
            if rules_store:
                try:
                    rule_data = rules_store.get_rule(rule_id)
                    if rule_data:
                        existing_rule = RoutingRule.from_dict(rule_data)
                        workspace_id = existing_rule.workspace_id
                except (OSError, RuntimeError, ValueError, KeyError) as e:
                    logger.debug("Failed to get rule %s from store: %s", rule_id, e)

        if not existing_rule:
            return {"success": False, "error": "Rule not found"}

        # Validate name if being updated
        if "name" in updates:
            name = updates["name"]
            if not name:
                return {"success": False, "error": "Rule name cannot be empty"}
            if len(name) > MAX_RULE_NAME_LENGTH:
                return {
                    "success": False,
                    "error": f"Rule name exceeds maximum length of {MAX_RULE_NAME_LENGTH}",
                }
            updates["name"] = sanitize_user_input(name, max_length=MAX_RULE_NAME_LENGTH)

        # Validate description if being updated
        if "description" in updates:
            description = updates["description"]
            if description and len(description) > MAX_RULE_DESCRIPTION_LENGTH:
                return {
                    "success": False,
                    "error": f"Description exceeds maximum length of {MAX_RULE_DESCRIPTION_LENGTH}",
                }
            if description:
                updates["description"] = sanitize_user_input(
                    description, max_length=MAX_RULE_DESCRIPTION_LENGTH
                )

        # Validate condition_logic if being updated
        if "condition_logic" in updates:
            if updates["condition_logic"] not in ("AND", "OR"):
                return {
                    "success": False,
                    "error": "condition_logic must be 'AND' or 'OR'",
                }

        # Validate priority if being updated
        if "priority" in updates:
            priority = updates["priority"]
            if not isinstance(priority, int) or priority < 0 or priority > 100:
                return {
                    "success": False,
                    "error": "priority must be an integer between 0 and 100",
                }

        # Validate conditions if being updated
        validated_conditions = None
        if "conditions" in updates:
            conditions = updates["conditions"]
            if not conditions:
                return {"success": False, "error": "At least one condition is required"}

            if len(conditions) > MAX_CONDITIONS_PER_RULE:
                return {
                    "success": False,
                    "error": f"Number of conditions ({len(conditions)}) exceeds maximum of {MAX_CONDITIONS_PER_RULE}",
                }

            validated_conditions = []
            for i, condition in enumerate(conditions):
                is_valid, error, sanitized = validate_rule_condition(condition)
                if not is_valid:
                    return {
                        "success": False,
                        "error": f"Condition {i + 1}: {error}",
                    }
                validated_conditions.append(sanitized)
            updates["conditions"] = validated_conditions

        # Validate actions if being updated
        validated_actions = None
        if "actions" in updates:
            actions = updates["actions"]
            if not actions:
                return {"success": False, "error": "At least one action is required"}

            if len(actions) > MAX_ACTIONS_PER_RULE:
                return {
                    "success": False,
                    "error": f"Number of actions ({len(actions)}) exceeds maximum of {MAX_ACTIONS_PER_RULE}",
                }

            validated_actions = []
            for i, action in enumerate(actions):
                is_valid, error, sanitized = validate_rule_action(action)
                if not is_valid:
                    return {
                        "success": False,
                        "error": f"Action {i + 1}: {error}",
                    }
                validated_actions.append(sanitized)

            # Check for circular routing with the new actions
            with _storage_lock:
                # Exclude the current rule from existing rules for circular check
                existing_rules = [r for r in _routing_rules.values() if r.id != rule_id]

            has_circular, circular_error = detect_circular_routing(
                validated_actions,
                existing_rules,
                workspace_id,
            )
            if has_circular:
                return {"success": False, "error": circular_error}

            updates["actions"] = validated_actions

        updated_rule_data = None

        # Update in RulesStore first (primary persistent storage)
        rules_store = _get_rules_store()
        if rules_store:
            try:
                updated_rule_data = rules_store.update_rule(rule_id, updates)
                if updated_rule_data:
                    logger.info("[SharedInbox] Updated routing rule %s in RulesStore", rule_id)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to update rule in RulesStore: %s", e)

        # Also update in email store for backward compatibility
        email_store = _get_store()
        if email_store:
            try:
                email_store.update_routing_rule(rule_id, **updates)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to update rule in email store: %s", e)

        # Update in-memory cache
        with _storage_lock:
            rule = _routing_rules.get(rule_id)
            if rule:
                # Update fields with validated data
                if "name" in updates:
                    rule.name = updates["name"]
                if "description" in updates:
                    rule.description = updates["description"]
                if "conditions" in updates:
                    rule.conditions = [RuleCondition.from_dict(c) for c in updates["conditions"]]
                if "condition_logic" in updates:
                    rule.condition_logic = updates["condition_logic"]
                if "actions" in updates:
                    rule.actions = [RuleAction.from_dict(a) for a in updates["actions"]]
                if "priority" in updates:
                    rule.priority = updates["priority"]
                if "enabled" in updates:
                    rule.enabled = updates["enabled"]

                rule.updated_at = datetime.now(timezone.utc)

        # Return data from persistent storage if available
        if updated_rule_data:
            return {
                "success": True,
                "rule": updated_rule_data,
            }

        # Fallback: try to get from RulesStore
        if rules_store:
            try:
                rule_data = rules_store.get_rule(rule_id)
                if rule_data:
                    return {
                        "success": True,
                        "rule": rule_data,
                    }
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.debug("Failed to get rule %s from store: %s", rule_id, e)

        # Return from in-memory cache if available
        with _storage_lock:
            rule = _routing_rules.get(rule_id)
            if rule:
                return {
                    "success": True,
                    "rule": rule.to_dict(),
                }

        return {"success": False, "error": "Rule not found"}

    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OSError,
        RuntimeError,
    ) as e:  # broad catch: last-resort handler
        logger.exception("Failed to update routing rule: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:delete")
async def handle_delete_routing_rule(
    rule_id: str,
) -> dict[str, Any]:
    """
    Delete a routing rule.

    DELETE /api/v1/inbox/routing/rules/:id
    """
    try:
        deleted = False

        # Delete from RulesStore (primary persistent storage)
        rules_store = _get_rules_store()
        if rules_store:
            try:
                deleted = rules_store.delete_rule(rule_id)
                if deleted:
                    logger.info("[SharedInbox] Deleted routing rule %s from RulesStore", rule_id)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to delete rule from RulesStore: %s", e)

        # Also delete from email store for backward compatibility
        email_store = _get_store()
        if email_store:
            try:
                email_store.delete_routing_rule(rule_id)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to delete rule from email store: %s", e)

        # Delete from in-memory cache
        with _storage_lock:
            if rule_id in _routing_rules:
                del _routing_rules[rule_id]
                deleted = True

        if deleted:
            return {
                "success": True,
                "deleted": rule_id,
            }
        else:
            return {
                "success": False,
                "error": "Rule not found",
            }

    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OSError,
        RuntimeError,
    ) as e:  # broad catch: last-resort handler
        logger.exception("Failed to delete routing rule: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


@require_permission("inbox:read")
async def handle_test_routing_rule(
    rule_id: str,
    workspace_id: str,
) -> dict[str, Any]:
    """
    Test a routing rule against existing messages.

    POST /api/v1/inbox/routing/rules/:id/test
    {
        "workspace_id": "ws_123"
    }
    """
    try:
        rule = None
        rule_data = None

        # Try RulesStore first (primary persistent storage)
        rules_store = _get_rules_store()
        if rules_store:
            try:
                rule_data = rules_store.get_rule(rule_id)
                if rule_data:
                    rule = RoutingRule.from_dict(rule_data)
            except (OSError, RuntimeError, ValueError, KeyError) as e:
                logger.warning("[SharedInbox] Failed to load rule from RulesStore: %s", e)

        # Fallback to in-memory
        if not rule:
            with _storage_lock:
                rule = _routing_rules.get(rule_id)
                if not rule:
                    return {"success": False, "error": "Rule not found"}

        # Count matching messages
        match_count = evaluate_rule_for_test(rule, workspace_id)

        return {
            "success": True,
            "rule_id": rule_id,
            "match_count": match_count,
            "rule": rule.to_dict(),
        }

    except (
        KeyError,
        ValueError,
        TypeError,
        AttributeError,
        OSError,
        RuntimeError,
    ) as e:  # broad catch: last-resort handler
        logger.exception("Failed to test routing rule: %s", e)
        return {
            "success": False,
            "error": "Internal server error",
        }


# =============================================================================
# Handler Class
# =============================================================================
