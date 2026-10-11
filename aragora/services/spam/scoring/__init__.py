"""Compatibility re-export of :mod:`aragora.moderation.spam.scoring`."""

from __future__ import annotations

from aragora.moderation.spam.scoring import (
    check_phishing,
    determine_category,
    score_attachments,
    score_content,
    score_headers,
    score_patterns,
    score_sender,
    score_subject,
    score_urls,
)

# The old module also exposed these names, imported from its sibling spam modules.
from aragora.moderation.spam.scoring import (
    EmailFeatures,
    SpamCategory,
    SpamClassifierConfig,
)

__all__ = [
    "check_phishing",
    "determine_category",
    "score_attachments",
    "score_content",
    "score_headers",
    "score_patterns",
    "score_sender",
    "score_subject",
    "score_urls",
    "EmailFeatures",
    "SpamCategory",
    "SpamClassifierConfig",
]
