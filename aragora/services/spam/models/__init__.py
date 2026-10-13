"""Compatibility re-export of :mod:`aragora.moderation.spam.models`."""

from __future__ import annotations

from aragora.moderation.spam.models import (
    EmailFeatures,
    SpamCategory,
    SpamClassificationResult,
    SpamClassifierConfig,
    SpamFeedback,
)

__all__ = [
    "EmailFeatures",
    "SpamCategory",
    "SpamClassificationResult",
    "SpamClassifierConfig",
    "SpamFeedback",
]
