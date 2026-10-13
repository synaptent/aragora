"""
Privacy filter for Supermemory content.

Removes sensitive data before syncing to external memory service:
- API keys and tokens
- Passwords and credentials
- Configurable PII patterns
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class PrivacyFilterConfig:
    """Configuration for privacy filtering.

    Attributes:
        filter_api_keys: Remove API key patterns
        filter_tokens: Remove bearer/auth tokens
        filter_passwords: Remove password patterns
        filter_emails: Remove email addresses
        filter_phone_numbers: Remove phone numbers
        custom_patterns: Additional regex patterns to filter
        redaction_text: Text to replace filtered content with
    """

    filter_api_keys: bool = True
    filter_tokens: bool = True
    filter_passwords: bool = True
    filter_emails: bool = False  # Opt-in for PII
    filter_phone_numbers: bool = False  # Opt-in for PII
    custom_patterns: list[tuple[str, str]] = field(default_factory=list)
    redaction_text: str = "[REDACTED]"


class PrivacyFilter:
    """Filters sensitive data from content before external sync.

    Usage:
        filter = PrivacyFilter()
        safe_content = filter.filter(content)

        # With custom config
        config = PrivacyFilterConfig(filter_emails=True)
        filter = PrivacyFilter(config)
    """

    # Standard patterns for sensitive data
    PATTERNS: list[tuple[str, str, str]] = [
        # API keys (various formats)
        (r"sk-[a-zA-Z0-9]{32,}", "api_key", "[REDACTED_SK_KEY]"),
        (r"sk-proj-[a-zA-Z0-9\-_]{32,}", "api_key", "[REDACTED_SK_KEY]"),
        (r"sm_[a-zA-Z0-9_\-]{32,}", "api_key", "[REDACTED_SM_KEY]"),
        (
            r"api[_-]?key['\"]?\s*[:=]\s*['\"]?[a-zA-Z0-9\-_]{16,}['\"]?",
            "api_key",
            "[REDACTED_API_KEY]",
        ),
        (r"ANTHROPIC_API_KEY=[^\s]+", "api_key", "ANTHROPIC_API_KEY=[REDACTED]"),
        (r"OPENAI_API_KEY=[^\s]+", "api_key", "OPENAI_API_KEY=[REDACTED]"),
        # Tokens
        (r"Bearer\s+[a-zA-Z0-9\-_\.]+", "token", "Bearer [REDACTED_TOKEN]"),
        (r"token['\"]?\s*[:=]\s*['\"]?[a-zA-Z0-9\-_\.]{20,}['\"]?", "token", "token=[REDACTED]"),
        (r"ghp_[a-zA-Z0-9]{36}", "token", "[REDACTED_GH_TOKEN]"),
        (r"gho_[a-zA-Z0-9]{36}", "token", "[REDACTED_GH_TOKEN]"),
        # Passwords
        (r"password['\"]?\s*[:=]\s*['\"][^'\"]+['\"]", "password", "password=[REDACTED]"),
        (r"passwd['\"]?\s*[:=]\s*['\"][^'\"]+['\"]", "password", "passwd=[REDACTED]"),
        (r"secret['\"]?\s*[:=]\s*['\"][^'\"]+['\"]", "password", "secret=[REDACTED]"),
        # Connection strings
        (r"postgres://[^\s]+", "connection", "[REDACTED_DB_URL]"),
        (r"mysql://[^\s]+", "connection", "[REDACTED_DB_URL]"),
        (r"mongodb://[^\s]+", "connection", "[REDACTED_DB_URL]"),
        (r"redis://[^\s]+", "connection", "[REDACTED_DB_URL]"),
    ]

    # PII patterns (opt-in)
    PII_PATTERNS: list[tuple[str, str, str]] = [
        # Email addresses
        (r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", "email", "[REDACTED_EMAIL]"),
        # Phone numbers (various formats)
        (r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "phone", "[REDACTED_PHONE]"),
        (r"\+\d{1,3}[-.\s]?\d{1,14}", "phone", "[REDACTED_PHONE]"),
    ]

    def __init__(self, config: PrivacyFilterConfig | None = None):
        """Initialize the privacy filter.

        Args:
            config: Filter configuration. Uses defaults if None.
        """
        self.config = config or PrivacyFilterConfig()
        self._compiled_patterns: list[tuple[re.Pattern, str]] = []
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns based on config."""
        patterns: list[tuple[str, str, str]] = []

        # Add standard patterns based on config
        for pattern, category, replacement in self.PATTERNS:
            if category == "api_key" and self.config.filter_api_keys:
                patterns.append((pattern, category, replacement))
            elif category == "token" and self.config.filter_tokens:
                patterns.append((pattern, category, replacement))
            elif category == "password" and self.config.filter_passwords:
                patterns.append((pattern, category, replacement))
            elif category == "connection" and self.config.filter_passwords:
                patterns.append((pattern, category, replacement))

        # Add PII patterns if enabled
        for pattern, category, replacement in self.PII_PATTERNS:
            if category == "email" and self.config.filter_emails:
                patterns.append((pattern, category, replacement))
            elif category == "phone" and self.config.filter_phone_numbers:
                patterns.append((pattern, category, replacement))

        # Add custom patterns
        for custom_pattern, replacement in self.config.custom_patterns:
            patterns.append((custom_pattern, "custom", replacement))

        # Compile all patterns
        self._compiled_patterns = [
            (re.compile(pattern, re.IGNORECASE), replacement)
            for pattern, _, replacement in patterns
        ]

    def filter(self, content: str) -> str:
        """Filter sensitive data from content.

        Args:
            content: Raw content that may contain sensitive data

        Returns:
            Filtered content with sensitive data redacted
        """
        if not content:
            return content

        result = content
        for pattern, replacement in self._compiled_patterns:
            result = pattern.sub(replacement, result)

        return result

    def filter_metadata(self, metadata: dict[str, Any]) -> dict[str, Any]:
        """Filter sensitive data from metadata dictionary.

        Args:
            metadata: Metadata dict that may contain sensitive values

        Returns:
            Filtered metadata with sensitive values redacted
        """
        if not metadata:
            return metadata

        result: dict[str, Any] = {}
        for key, value in metadata.items():
            # Check if key itself suggests sensitive data
            key_lower = key.lower()
            if any(
                word in key_lower for word in ["key", "token", "password", "secret", "credential"]
            ):
                result[key] = self.config.redaction_text
            elif isinstance(value, str):
                result[key] = self.filter(value)
            elif isinstance(value, dict):
                # Recursive filtering for nested dicts
                result[key] = self.filter_metadata(value)
            elif isinstance(value, list):
                # Filter string items in lists
                result[key] = [self.filter(v) if isinstance(v, str) else v for v in value]
            else:
                result[key] = value

        return result

    def is_safe(self, content: str) -> bool:
        """Check if content is safe to sync (no sensitive data).

        Args:
            content: Content to check

        Returns:
            True if no sensitive patterns found
        """
        for pattern, _ in self._compiled_patterns:
            if pattern.search(content):
                return False
        return True
