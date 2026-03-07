"""
Entity ID validation for path segments.

Provides consistent security validation for path segments like debate IDs,
agent names, and other entity identifiers. Prevents path traversal attacks
and injection vulnerabilities.
"""

import re

# Safe string patterns for different entity types
SAFE_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SAFE_ID_PATTERN_WITH_DOTS = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
SAFE_SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")
SAFE_AGENT_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")

# Plugin manifest patterns (stricter for submission)
SAFE_PLUGIN_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,62}[a-z0-9]?$")  # 1-64 chars, lowercase
SAFE_ENTRY_POINT_PATTERN = re.compile(
    r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)*:[a-zA-Z_][a-zA-Z0-9_]*$"
)  # module.path:function
SAFE_SEMVER_PATTERN = re.compile(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?(\+[a-zA-Z0-9.]+)?$")

# Specific patterns for structured IDs
SAFE_GAUNTLET_ID_PATTERN = re.compile(r"^gauntlet-\d{14}-[a-f0-9]{6}$")
SAFE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
SAFE_BATCH_ID_PATTERN = re.compile(r"^batch_[a-zA-Z0-9]{6,32}$")
SAFE_SHARE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{16,32}$")
SAFE_SESSION_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,64}$")


def validate_path_segment(
    value: str,
    name: str,
    pattern: re.Pattern[str] | None = None,
) -> tuple[bool, str | None]:
    """Validate a path segment against a pattern.

    This is the primary function for validating user-provided path segments
    like IDs, names, and slugs. It ensures values conform to safe patterns
    and prevents path traversal or injection attacks.

    Args:
        value: The value to validate
        name: Name of the segment for error messages
        pattern: Regex pattern to match against (defaults to SAFE_ID_PATTERN)

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        >>> is_valid, err = validate_path_segment("my-debate-123", "debate_id")
        >>> if not is_valid:
        ...     return error_response(400, err)
    """
    if pattern is None:
        pattern = SAFE_ID_PATTERN

    if not value:
        return False, f"Missing {name}"
    if not pattern.match(value):
        return False, f"Invalid {name}: must match pattern {pattern.pattern}"
    return True, None


def validate_id(value: str, name: str = "ID") -> tuple[bool, str | None]:
    """Validate a generic ID (alphanumeric with hyphens/underscores, 1-64 chars).

    Args:
        value: ID to validate
        name: Name for error messages

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(value, name, SAFE_ID_PATTERN)


def validate_agent_name(agent: str) -> tuple[bool, str | None]:
    """Validate an agent name (alphanumeric with hyphens/underscores, 1-32 chars).

    Args:
        agent: Agent name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(agent, "agent name", SAFE_AGENT_PATTERN)


def validate_debate_id(debate_id: str) -> tuple[bool, str | None]:
    """Validate a debate ID (alphanumeric with hyphens/underscores, 1-128 chars).

    Args:
        debate_id: Debate ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(debate_id, "debate ID", SAFE_SLUG_PATTERN)


def validate_gauntlet_id(gauntlet_id: str) -> tuple[bool, str | None]:
    """Validate a gauntlet ID (prefixed with gauntlet-).

    Accepts both strict format (gauntlet-YYYYMMDDHHMMSS-xxxxxx) and
    legacy format (gauntlet-*) for backwards compatibility.

    Args:
        gauntlet_id: Gauntlet ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not gauntlet_id or not gauntlet_id.startswith("gauntlet-"):
        return False, "Invalid gauntlet ID: must start with 'gauntlet-'"
    # Accept strict format or legacy format
    if SAFE_GAUNTLET_ID_PATTERN.match(gauntlet_id):
        return True, None
    return validate_path_segment(gauntlet_id, "gauntlet ID", SAFE_SLUG_PATTERN)


def validate_share_token(token: str) -> tuple[bool, str | None]:
    """Validate a share token.

    Share tokens are URL-safe base64 strings, 16-32 characters.

    Args:
        token: Share token to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(token, "share token", SAFE_SHARE_TOKEN_PATTERN)


def validate_batch_id(batch_id: str) -> tuple[bool, str | None]:
    """Validate a batch ID (prefixed with batch_).

    Args:
        batch_id: Batch ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    if not batch_id or not batch_id.startswith("batch_"):
        return False, "Invalid batch ID: must start with 'batch_'"
    return validate_path_segment(batch_id, "batch ID", SAFE_BATCH_ID_PATTERN)


def validate_session_id(session_id: str) -> tuple[bool, str | None]:
    """Validate a session ID.

    Args:
        session_id: Session ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(session_id, "session ID", SAFE_SESSION_ID_PATTERN)


def validate_plugin_name(plugin_name: str) -> tuple[bool, str | None]:
    """Validate a plugin name.

    Args:
        plugin_name: Plugin name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(plugin_name, "plugin name", SAFE_ID_PATTERN)


def validate_loop_id(loop_id: str) -> tuple[bool, str | None]:
    """Validate a nomic loop ID.

    Args:
        loop_id: Loop ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(loop_id, "loop ID", SAFE_ID_PATTERN)


def validate_replay_id(replay_id: str) -> tuple[bool, str | None]:
    """Validate a replay ID.

    Args:
        replay_id: Replay ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(replay_id, "replay ID", SAFE_ID_PATTERN)


def validate_genome_id(genome_id: str) -> tuple[bool, str | None]:
    """Validate a genome ID (supports dots for versioning).

    Args:
        genome_id: Genome ID to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(genome_id, "genome ID", SAFE_ID_PATTERN_WITH_DOTS)


def validate_agent_name_with_version(agent: str) -> tuple[bool, str | None]:
    """Validate an agent name that may include version dots (e.g., claude-3.5-sonnet).

    Args:
        agent: Agent name to validate

    Returns:
        Tuple of (is_valid, error_message)
    """
    return validate_path_segment(agent, "agent name", SAFE_ID_PATTERN_WITH_DOTS)


def validate_no_path_traversal(path: str) -> tuple[bool, str | None]:
    """Check that a path does not contain path traversal sequences.

    Blocks attempts to escape the intended directory via '..' sequences.

    Args:
        path: URL path or file path to validate

    Returns:
        Tuple of (is_valid, error_message)

    Example:
        # Before (repeated 3+ times):
        if '..' in path:
            return error_response("Invalid path", 400)

        # After:
        is_valid, err = validate_no_path_traversal(path)
        if not is_valid:
            return error_response(err, 400)
    """
    if ".." in path:
        return False, "Path traversal not allowed"
    return True, None


def sanitize_id(value: str) -> str | None:
    """Sanitize an ID string.

    Args:
        value: ID string to sanitize

    Returns:
        Sanitized ID or None if invalid
    """
    if not isinstance(value, str):
        return None
    value = value.strip()
    if SAFE_ID_PATTERN.match(value):
        return value
    return None
