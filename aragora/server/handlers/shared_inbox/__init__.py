"""
Shared Inbox Handler Package.

This package contains modular components for shared inbox management:
- models.py: Data models (MessageStatus, RoutingRule, SharedInbox, etc.)
- storage.py: Storage utilities and in-memory caches
- validators.py: Input validation and rate limiting
- rules_engine.py: Routing rule evaluation logic
- handler.py: HTTP handlers and SharedInboxHandler class

All public APIs are re-exported from this package for backward compatibility.

Additional modules (import directly, without expanding eager package exports):
_shared_inbox_handler.
"""

from __future__ import annotations

# Import models from the dedicated models module
from aragora.server.handlers.shared_inbox.models import (
    MessageStatus,
    RuleAction,
    RuleActionType,
    RuleCondition,
    RuleConditionField,
    RuleConditionOperator,
    RoutingRule,
    SharedInbox,
    SharedInboxMessage,
)

# Import storage utilities
from aragora.server.handlers.shared_inbox.storage import (
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
)

# Import validators
from aragora.server.handlers.shared_inbox.validators import (
    # Constants
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
    # Classes
    RateLimitEntry,
    RuleRateLimiter,
    RuleValidationResult,
    # Functions
    get_rule_rate_limiter,
    validate_safe_regex,
    validate_rule_condition_field,
    validate_rule_condition,
    validate_rule_action,
    detect_circular_routing,
    validate_routing_rule,
    validate_inbox_input,
    validate_tag,
)

# Import rules engine
from aragora.server.handlers.shared_inbox.rules_engine import (
    MessageLike,
    get_matching_rules_for_email,
    apply_routing_rules_to_message,
    evaluate_rule_for_test,
)

# Import handler class
from aragora.server.handlers.shared_inbox.handler import SharedInboxHandler

# Import inbox handler functions
from aragora.server.handlers.shared_inbox.inbox_handlers import (
    handle_create_shared_inbox,
    handle_list_shared_inboxes,
    handle_get_shared_inbox,
    handle_get_inbox_messages,
    handle_assign_message,
    handle_update_message_status,
    handle_add_message_tag,
    handle_add_message_to_inbox,
)

# Import rule handler functions
from aragora.server.handlers.shared_inbox.rule_handlers import (
    handle_create_routing_rule,
    handle_list_routing_rules,
    handle_update_routing_rule,
    handle_delete_routing_rule,
    handle_test_routing_rule,
)


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
