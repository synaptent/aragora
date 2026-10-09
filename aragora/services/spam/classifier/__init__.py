"""Compatibility re-export of :mod:`aragora.moderation.spam.classifier`."""

from __future__ import annotations

from aragora.moderation.spam.classifier import (
    SpamClassifier,
    classify_email,
    classify_email_spam,
    classify_emails_batch,
)

# The old module also exposed these names, imported from its sibling spam modules.
from aragora.moderation.spam.classifier import (
    PROMOTIONAL_PATTERNS,
    NaiveBayesClassifier,
    SpamCategory,
    SpamClassificationResult,
    SpamClassifierConfig,
    SpamFeatures,
    determine_category,
    score_attachments,
    score_content,
    score_headers,
    score_patterns,
    score_sender,
    score_subject,
    score_urls,
)

__all__ = [
    "SpamClassifier",
    "classify_email",
    "classify_email_spam",
    "classify_emails_batch",
    "NaiveBayesClassifier",
    "PROMOTIONAL_PATTERNS",
    "SpamCategory",
    "SpamClassificationResult",
    "SpamClassifierConfig",
    "SpamFeatures",
    "determine_category",
    "score_attachments",
    "score_content",
    "score_headers",
    "score_patterns",
    "score_sender",
    "score_subject",
    "score_urls",
]
