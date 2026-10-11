"""Compatibility re-export of :mod:`aragora.moderation.spam.patterns`."""

from __future__ import annotations

from aragora.moderation.spam.patterns import (
    DANGEROUS_EXTENSIONS,
    FREE_EMAIL_PROVIDERS,
    KNOWN_SPAM_DOMAINS,
    MONEY_WORDS,
    PROMOTIONAL_PATTERNS,
    REQUIRED_HEADERS,
    SPAM_WORDS,
    SUSPICIOUS_TLDS,
    URGENCY_WORDS,
    URL_SHORTENERS,
)

__all__ = [
    "DANGEROUS_EXTENSIONS",
    "FREE_EMAIL_PROVIDERS",
    "KNOWN_SPAM_DOMAINS",
    "MONEY_WORDS",
    "PROMOTIONAL_PATTERNS",
    "REQUIRED_HEADERS",
    "SPAM_WORDS",
    "SUSPICIOUS_TLDS",
    "URGENCY_WORDS",
    "URL_SHORTENERS",
]
