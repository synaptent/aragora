"""
Request validation package for Aragora server.

Provides JSON schema validation, query parameter parsing, entity ID validation,
and validation decorators for handler methods.

Modules:
- core: ValidationResult, field validators, JSON body validation
- entities: Path segment validators (debate_id, agent_name, etc.)
- query_params: Query parameter parsing with bounds checking
- schema: Schema definitions and validate_against_schema
- decorators: Handler validation decorators

Usage:
    from aragora.server.validation import (
        # Core validation
        ValidationResult,
        validate_json_body,
        validate_content_type,
        validate_required_fields,

        # Entity validators
        validate_debate_id,
        validate_agent_name,
        SAFE_ID_PATTERN,

        # Query params
        safe_query_int,
        validate_sort_params,

        # Schema validation
        validate_against_schema,
        DEBATE_START_SCHEMA,

        # Decorators
        validate_request,
        validate_post_body,
    )
"""

# Core validation
from .core import (
    MAX_JSON_BODY_SIZE,
    ValidationResult,
    sanitize_string,
    validate_content_type,
    validate_enum_field,
    validate_float_field,
    validate_int_field,
    validate_json_body,
    validate_list_field,
    validate_required_fields,
    validate_string,
    validate_string_field,
)

# Decorators
from .decorators import (
    validate_post_body,
    validate_query_params,
    validate_request,
)

# Entity validators
from .entities import (
    SAFE_AGENT_PATTERN,
    SAFE_DEBATE_REF_PATTERN,
    SAFE_ID_PATTERN,
    SAFE_ID_PATTERN_WITH_DOTS,
    SAFE_SLUG_PATTERN,
    sanitize_id,
    validate_agent_name,
    validate_agent_name_with_version,
    validate_debate_id,
    validate_debate_ref,
    validate_genome_id,
    validate_id,
    validate_loop_id,
    validate_no_path_traversal,
    validate_path_segment,
    validate_plugin_name,
    validate_replay_id,
)

# Query parameter parsing
from .query_params import (
    ALLOWED_FILTER_OPERATORS,
    ALLOWED_SORT_COLUMNS,
    ALLOWED_SORT_DIRECTIONS,
    DEFAULT_QUERY_STRING_MAX_LENGTH,
    parse_bool_param,
    parse_float_param,
    parse_int_param,
    parse_string_param,
    safe_query_float,
    safe_query_int,
    safe_query_string,
    validate_filter_operator,
    validate_search_query,
    validate_sort_direction,
    validate_sort_param,
    validate_sort_params,
)

# Schema validation
from .schema import (
    AGENT_CONFIG_SCHEMA,
    BATCH_SUBMIT_SCHEMA,
    CHECKOUT_SESSION_SCHEMA,
    DEBATE_START_SCHEMA,
    DEBATE_UPDATE_SCHEMA,
    EMAIL_CONFIG_SCHEMA,
    FORK_REQUEST_SCHEMA,
    GAUNTLET_RUN_SCHEMA,
    MEMORY_CLEANUP_SCHEMA,
    NOTIFICATION_SEND_SCHEMA,
    ORG_CREATE_SCHEMA,
    ORG_INVITE_SCHEMA,
    PLUGIN_INSTALL_SCHEMA,
    PLUGIN_RUN_SCHEMA,
    PROBE_RUN_SCHEMA,
    SHARE_UPDATE_SCHEMA,
    SOCIAL_PUBLISH_SCHEMA,
    TELEGRAM_CONFIG_SCHEMA,
    USER_LOGIN_SCHEMA,
    USER_REGISTER_SCHEMA,
    VERIFICATION_SCHEMA,
    validate_against_schema,
)

# Security validation
from .security import (
    # Constants
    MAX_AGENTS_PER_DEBATE,
    MAX_CONTEXT_LENGTH,
    MAX_DEBATE_TITLE_LENGTH,
    MAX_REGEX_PATTERN_LENGTH,
    MAX_SEARCH_QUERY_LENGTH,
    MAX_TASK_LENGTH,
    REGEX_TIMEOUT_SECONDS,
    # Classes
    SecurityValidationResult,
    ValidationError,
    # ReDoS protection
    execute_regex_with_timeout,
    is_safe_regex_pattern,
    validate_search_query_redos_safe,
    # Input validation
    validate_agent_count,
    validate_context_size,
    validate_debate_title,
    validate_task_content,
    # Sanitization
    sanitize_user_input,
)

__all__ = [
    # Core
    "MAX_JSON_BODY_SIZE",
    "ValidationResult",
    "validate_json_body",
    "validate_content_type",
    "validate_required_fields",
    "validate_string",
    "validate_string_field",
    "validate_int_field",
    "validate_float_field",
    "validate_list_field",
    "validate_enum_field",
    "sanitize_string",
    # Entities
    "SAFE_ID_PATTERN",
    "SAFE_ID_PATTERN_WITH_DOTS",
    "SAFE_SLUG_PATTERN",
    "SAFE_DEBATE_REF_PATTERN",
    "SAFE_AGENT_PATTERN",
    "validate_path_segment",
    "validate_id",
    "validate_agent_name",
    "validate_debate_id",
    "validate_debate_ref",
    "validate_plugin_name",
    "validate_loop_id",
    "validate_replay_id",
    "validate_genome_id",
    "validate_agent_name_with_version",
    "validate_no_path_traversal",
    "sanitize_id",
    # Query params
    "DEFAULT_QUERY_STRING_MAX_LENGTH",
    "ALLOWED_SORT_COLUMNS",
    "ALLOWED_SORT_DIRECTIONS",
    "ALLOWED_FILTER_OPERATORS",
    "parse_int_param",
    "parse_float_param",
    "parse_bool_param",
    "parse_string_param",
    "safe_query_int",
    "safe_query_float",
    "validate_sort_param",
    "validate_sort_direction",
    "validate_sort_params",
    "safe_query_string",
    "validate_filter_operator",
    "validate_search_query",
    # Schema
    "DEBATE_START_SCHEMA",
    "DEBATE_UPDATE_SCHEMA",
    "VERIFICATION_SCHEMA",
    "PROBE_RUN_SCHEMA",
    "FORK_REQUEST_SCHEMA",
    "MEMORY_CLEANUP_SCHEMA",
    "AGENT_CONFIG_SCHEMA",
    "BATCH_SUBMIT_SCHEMA",
    "USER_REGISTER_SCHEMA",
    "USER_LOGIN_SCHEMA",
    "ORG_CREATE_SCHEMA",
    "ORG_INVITE_SCHEMA",
    "GAUNTLET_RUN_SCHEMA",
    "CHECKOUT_SESSION_SCHEMA",
    "SOCIAL_PUBLISH_SCHEMA",
    "PLUGIN_RUN_SCHEMA",
    "PLUGIN_INSTALL_SCHEMA",
    "SHARE_UPDATE_SCHEMA",
    "EMAIL_CONFIG_SCHEMA",
    "TELEGRAM_CONFIG_SCHEMA",
    "NOTIFICATION_SEND_SCHEMA",
    "validate_against_schema",
    # Security
    "MAX_DEBATE_TITLE_LENGTH",
    "MAX_TASK_LENGTH",
    "MAX_CONTEXT_LENGTH",
    "MAX_SEARCH_QUERY_LENGTH",
    "MAX_REGEX_PATTERN_LENGTH",
    "MAX_AGENTS_PER_DEBATE",
    "REGEX_TIMEOUT_SECONDS",
    "ValidationError",
    "SecurityValidationResult",
    "is_safe_regex_pattern",
    "execute_regex_with_timeout",
    "validate_search_query_redos_safe",
    "validate_debate_title",
    "validate_task_content",
    "validate_context_size",
    "validate_agent_count",
    "sanitize_user_input",
    # Decorators
    "validate_request",
    "validate_post_body",
    "validate_query_params",
]
