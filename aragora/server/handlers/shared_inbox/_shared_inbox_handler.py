"""
HTTP API Handlers for Shared Inbox Management.

This module is a thin re-export layer for backward compatibility.
All functionality has been moved to the shared_inbox/ package:
- shared_inbox/models.py: Data models
- shared_inbox/storage.py: Storage utilities
- shared_inbox/validators.py: Input validation
- shared_inbox/rules_engine.py: Rule evaluation
- shared_inbox/handler.py: HTTP handlers

Import from aragora.server.handlers.shared_inbox for new code.
"""
# mypy: disable-error-code="assignment,attr-defined,index"
# RuleAction/RuleConditionOperator type handling is dynamic

from __future__ import annotations

# Re-export everything from the shared_inbox package for backward compatibility
from aragora.server.handlers.shared_inbox import (
    # Models
    MessageStatus,
    RuleAction,
    RuleActionType,
    RuleCondition,
    RuleConditionField,
    RuleConditionOperator,
    RoutingRule,
    SharedInbox,
    SharedInboxMessage,
    # Storage
    USE_PERSISTENT_STORAGE,
    _get_email_store,
    _get_rules_store,
    _get_activity_store,
    _get_store,
    _log_activity,
    _shared_inboxes,
    _inbox_messages,
    _routing_rules,
    _storage_lock,
    # Validators - Constants
    ALLOWED_RULE_CONDITION_FIELDS,
    REGEX_OPERATORS,
    MAX_RULE_NAME_LENGTH,
    MAX_RULE_DESCRIPTION_LENGTH,
    MAX_CONDITION_VALUE_LENGTH,
    MAX_REGEX_PATTERN_LENGTH,
    MAX_TAG_LENGTH,
    MAX_INBOX_NAME_LENGTH,
    MAX_INBOX_DESCRIPTION_LENGTH,
    MAX_CONDITIONS_PER_RULE,
    MAX_ACTIONS_PER_RULE,
    MAX_RULES_PER_WORKSPACE,
    RULE_RATE_LIMIT_WINDOW_SECONDS,
    RULE_RATE_LIMIT_MAX_REQUESTS,
    # Validators - Classes
    RateLimitEntry,
    RuleRateLimiter,
    RuleValidationResult,
    # Validators - Functions
    get_rule_rate_limiter,
    validate_safe_regex,
    validate_rule_condition_field,
    validate_rule_condition,
    validate_rule_action,
    detect_circular_routing,
    validate_routing_rule,
    validate_inbox_input,
    validate_tag,
    # Rules Engine
    MessageLike,
    get_matching_rules_for_email,
    apply_routing_rules_to_message,
    evaluate_rule_for_test,
    # Handler Class
    SharedInboxHandler,
    # Handler Functions
    handle_create_shared_inbox,
    handle_list_shared_inboxes,
    handle_get_shared_inbox,
    handle_get_inbox_messages,
    handle_assign_message,
    handle_update_message_status,
    handle_add_message_tag,
    handle_add_message_to_inbox,
    handle_create_routing_rule,
    handle_list_routing_rules,
    handle_update_routing_rule,
    handle_delete_routing_rule,
    handle_test_routing_rule,
)
from aragora.server.handlers.shared_inbox.rules_engine import _evaluate_rule as _evaluate_rule_impl

# Backward compatibility: expose the rate limiter instance
_rule_rate_limiter = get_rule_rate_limiter()
_evaluate_rule = _evaluate_rule_impl

__all__ = [
    # Models
    "MessageStatus",
    "RuleConditionField",
    "RuleConditionOperator",
    "RuleActionType",
    "RuleCondition",
    "RuleAction",
    "RoutingRule",
    "SharedInboxMessage",
    "SharedInbox",
    # Storage
    "USE_PERSISTENT_STORAGE",
    "_get_email_store",
    "_get_rules_store",
    "_get_activity_store",
    "_get_store",
    "_log_activity",
    "_shared_inboxes",
    "_inbox_messages",
    "_routing_rules",
    "_storage_lock",
    # Validators - Constants
    "ALLOWED_RULE_CONDITION_FIELDS",
    "REGEX_OPERATORS",
    "MAX_RULE_NAME_LENGTH",
    "MAX_RULE_DESCRIPTION_LENGTH",
    "MAX_CONDITION_VALUE_LENGTH",
    "MAX_REGEX_PATTERN_LENGTH",
    "MAX_TAG_LENGTH",
    "MAX_INBOX_NAME_LENGTH",
    "MAX_INBOX_DESCRIPTION_LENGTH",
    "MAX_CONDITIONS_PER_RULE",
    "MAX_ACTIONS_PER_RULE",
    "MAX_RULES_PER_WORKSPACE",
    "RULE_RATE_LIMIT_WINDOW_SECONDS",
    "RULE_RATE_LIMIT_MAX_REQUESTS",
    # Validators - Classes
    "RateLimitEntry",
    "RuleRateLimiter",
    "RuleValidationResult",
    "_rule_rate_limiter",
    # Validators - Functions
    "get_rule_rate_limiter",
    "validate_safe_regex",
    "validate_rule_condition_field",
    "validate_rule_condition",
    "validate_rule_action",
    "detect_circular_routing",
    "validate_routing_rule",
    "validate_inbox_input",
    "validate_tag",
    # Rules Engine
    "MessageLike",
    "get_matching_rules_for_email",
    "apply_routing_rules_to_message",
    "evaluate_rule_for_test",
    "_evaluate_rule",
    # Handler Class
    "SharedInboxHandler",
    # Handler Functions
    "handle_create_shared_inbox",
    "handle_list_shared_inboxes",
    "handle_get_shared_inbox",
    "handle_get_inbox_messages",
    "handle_assign_message",
    "handle_update_message_status",
    "handle_add_message_tag",
    "handle_add_message_to_inbox",
    "handle_create_routing_rule",
    "handle_list_routing_rules",
    "handle_update_routing_rule",
    "handle_delete_routing_rule",
    "handle_test_routing_rule",
]
