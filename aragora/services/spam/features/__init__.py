"""Compatibility re-export of :mod:`aragora.moderation.spam.features`."""

from __future__ import annotations

from aragora.moderation.spam.features import (
    SpamFeatures,
)

# The old module also exposed these names, imported from its sibling spam modules.
from aragora.moderation.spam.features import (
    DANGEROUS_EXTENSIONS,
    FREE_EMAIL_PROVIDERS,
    KNOWN_SPAM_DOMAINS,
    MONEY_WORDS,
    REQUIRED_HEADERS,
    SPAM_WORDS,
    SUSPICIOUS_TLDS,
    URGENCY_WORDS,
    URL_SHORTENERS,
    EmailFeatures,
)

__all__ = [
    "SpamFeatures",
    "DANGEROUS_EXTENSIONS",
    "EmailFeatures",
    "FREE_EMAIL_PROVIDERS",
    "KNOWN_SPAM_DOMAINS",
    "MONEY_WORDS",
    "REQUIRED_HEADERS",
    "SPAM_WORDS",
    "SUSPICIOUS_TLDS",
    "URGENCY_WORDS",
    "URL_SHORTENERS",
]
