"""Compatibility re-export of :mod:`aragora.moderation.spam.classifier`."""

from __future__ import annotations

from aragora.moderation.spam.classifier import (
    SpamClassifier,
    classify_email,
    classify_email_spam,
    classify_emails_batch,
)

__all__ = [
    "SpamClassifier",
    "classify_email",
    "classify_email_spam",
    "classify_emails_batch",
]
