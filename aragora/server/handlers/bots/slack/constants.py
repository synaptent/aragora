"""
Slack Bot Handler Constants and Validation.

This module contains shared constants, RBAC permissions, and input validation
utilities used across the Slack integration.
"""

import logging
import os
import re
from typing import Any
from collections.abc import Callable

logger = logging.getLogger(__name__)

# =============================================================================
# RBAC Permission Constants for Slack Bot
# =============================================================================
# Granular permissions for Slack bot operations
PERM_SLACK_COMMANDS_READ = "slack.commands.read"
PERM_SLACK_COMMANDS_EXECUTE = "slack.commands.execute"
PERM_SLACK_DEBATES_CREATE = "slack.debates.create"
PERM_SLACK_VOTES_RECORD = "slack.votes.record"
PERM_SLACK_INTERACTIVE = "slack.interactive.respond"
PERM_SLACK_ADMIN = "slack.admin"

# =============================================================================
# RBAC Imports - Optional dependency for graceful degradation
# =============================================================================
# Declare module-level types for optional RBAC components
check_permission: Callable[..., Any] | None
AuthorizationContext: type[Any] | None
AuthorizationDecision: type[Any] | None

try:
    from aragora.rbac.checker import check_permission as _check_perm
    from aragora.rbac.models import AuthorizationContext as _AuthCtx
    from aragora.rbac.models import AuthorizationDecision as _AuthDecision

    check_permission = _check_perm
    AuthorizationContext = _AuthCtx
    AuthorizationDecision = _AuthDecision
    RBAC_AVAILABLE = True
except (ImportError, AttributeError):
    RBAC_AVAILABLE = False
    check_permission = None
    AuthorizationContext = None
    AuthorizationDecision = None

# =============================================================================
# Input Validation Patterns for Security
# =============================================================================
# Patterns to detect potential injection attacks
_DANGEROUS_PATTERNS = [
    re.compile(r"['\";]"),  # SQL injection characters
    re.compile(r"<[^>]*script", re.IGNORECASE),  # XSS script tags
    re.compile(r"\$\{.*\}"),  # Template injection
    re.compile(r"{{.*}}"),  # Template injection (Jinja/Mustache)
    re.compile(r"[`|&;$]"),  # Shell command injection
    re.compile(r"\\x[0-9a-fA-F]{2}"),  # Hex escapes
    re.compile(r"\\u[0-9a-fA-F]{4}"),  # Unicode escapes
]

# Maximum input lengths for different fields
MAX_TOPIC_LENGTH = 2000
MAX_COMMAND_LENGTH = 500
MAX_USER_ID_LENGTH = 100
MAX_CHANNEL_ID_LENGTH = 100

# Command patterns for parsing Slack slash commands
# Matches: /aragora <command> [arguments]
COMMAND_PATTERN = re.compile(r"^/aragora\s+(\w+)(?:\s+(.*))?$", re.IGNORECASE)

# Topic patterns for parsing debate topics
# Matches quoted or unquoted topics
TOPIC_PATTERN = re.compile(r'^["\']?([^"\']+)["\']?$')

# Environment variables for Slack configuration - None defaults make misconfiguration explicit
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")
SLACK_BOT_TOKEN = os.environ.get("SLACK_BOT_TOKEN")

# Log at debug level for unconfigured optional integrations
if not SLACK_SIGNING_SECRET:
    logger.debug("SLACK_SIGNING_SECRET not configured - signature verification disabled")
if not SLACK_BOT_TOKEN:
    logger.debug("SLACK_BOT_TOKEN not configured - Slack bot responses disabled")

# Agent display name mapping
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "claude": "Claude",
    "gpt4": "GPT-4",
    "gemini": "Gemini",
    "mistral": "Mistral",
    "deepseek": "DeepSeek",
    "grok": "Grok",
    "qwen": "Qwen",
    "kimi": "Kimi",
    "anthropic-api": "Claude",
    "openai-api": "GPT-4",
}


# =============================================================================
# Input Validation Functions
# =============================================================================


def validate_slack_input(
    value: str,
    field_name: str,
    max_length: int = MAX_COMMAND_LENGTH,
    allow_empty: bool = False,
) -> tuple[bool, str | None]:
    """Validate and sanitize Slack input for security.

    Args:
        value: Input string to validate
        field_name: Name of the field for error messages
        max_length: Maximum allowed length
        allow_empty: Whether empty values are allowed

    Returns:
        Tuple of (is_valid, error_message). error_message is None if valid.
    """
    if not value:
        if allow_empty:
            return True, None
        return False, f"{field_name} is required"

    if len(value) > max_length:
        return False, f"{field_name} exceeds maximum length of {max_length}"

    # Check for dangerous patterns
    for pattern in _DANGEROUS_PATTERNS:
        if pattern.search(value):
            logger.warning(
                "Potential injection attempt detected in %s: %s",
                field_name,
                value[:100],
            )
            return False, f"{field_name} contains invalid characters"

    return True, None


def validate_slack_user_id(user_id: str) -> tuple[bool, str | None]:
    """Validate Slack user ID format.

    Slack user IDs follow pattern: U followed by alphanumeric characters.
    """
    if not user_id:
        return False, "User ID is required"

    if len(user_id) > MAX_USER_ID_LENGTH:
        return False, "User ID too long"

    # Slack user IDs are alphanumeric, typically start with U, W, or B
    if not re.match(r"^[A-Z0-9]+$", user_id):
        return False, "Invalid user ID format"

    return True, None


def validate_slack_channel_id(channel_id: str) -> tuple[bool, str | None]:
    """Validate Slack channel ID format.

    Slack channel IDs follow pattern: C/D/G followed by alphanumeric characters.
    """
    if not channel_id:
        return False, "Channel ID is required"

    if len(channel_id) > MAX_CHANNEL_ID_LENGTH:
        return False, "Channel ID too long"

    # Slack channel IDs are alphanumeric, typically start with C, D, or G
    if not re.match(r"^[A-Z0-9]+$", channel_id):
        return False, "Invalid channel ID format"

    return True, None


def validate_slack_team_id(team_id: str) -> tuple[bool, str | None]:
    """Validate Slack team/workspace ID format.

    Slack team IDs follow pattern: T followed by alphanumeric characters.
    """
    if not team_id:
        return False, "Team ID is required"

    if len(team_id) > MAX_USER_ID_LENGTH:
        return False, "Team ID too long"

    # Slack team IDs are alphanumeric, typically start with T
    if not re.match(r"^T[A-Z0-9]+$", team_id):
        return False, "Invalid team ID format"

    return True, None


# Backward compatibility aliases (with underscore prefix as used internally)
_validate_slack_input = validate_slack_input
_validate_slack_user_id = validate_slack_user_id
_validate_slack_channel_id = validate_slack_channel_id
_validate_slack_team_id = validate_slack_team_id


__all__ = [
    # RBAC Permission constants
    "PERM_SLACK_COMMANDS_READ",
    "PERM_SLACK_COMMANDS_EXECUTE",
    "PERM_SLACK_DEBATES_CREATE",
    "PERM_SLACK_VOTES_RECORD",
    "PERM_SLACK_INTERACTIVE",
    "PERM_SLACK_ADMIN",
    # RBAC components
    "RBAC_AVAILABLE",
    "check_permission",
    "AuthorizationContext",
    "AuthorizationDecision",
    # Validation patterns
    "MAX_TOPIC_LENGTH",
    "MAX_COMMAND_LENGTH",
    "MAX_USER_ID_LENGTH",
    "MAX_CHANNEL_ID_LENGTH",
    "COMMAND_PATTERN",
    "TOPIC_PATTERN",
    # Environment config
    "SLACK_SIGNING_SECRET",
    "SLACK_BOT_TOKEN",
    # Agent display names
    "AGENT_DISPLAY_NAMES",
    # Validation functions
    "validate_slack_input",
    "validate_slack_user_id",
    "validate_slack_channel_id",
    "validate_slack_team_id",
    # Backward compatibility aliases
    "_validate_slack_input",
    "_validate_slack_user_id",
    "_validate_slack_channel_id",
    "_validate_slack_team_id",
]
