"""
ML-Enhanced Spam Classification Service.

This module is a backwards-compatibility shim that re-exports all public
APIs from the ``aragora.moderation.spam`` package.  The implementation has
been refactored into focused submodules:

- ``aragora.moderation.spam.models``    -- data classes and enums
- ``aragora.moderation.spam.patterns``  -- pattern constants and word lists
- ``aragora.moderation.spam.features``  -- feature extraction engine
- ``aragora.moderation.spam.model``     -- Naive Bayes ML classifier
- ``aragora.moderation.spam.classifier``-- main SpamClassifier and convenience functions

All names previously importable from ``aragora.services.spam_classifier``
remain importable from this module.

Usage (unchanged):
    from aragora.services.spam_classifier import SpamClassifier

    classifier = SpamClassifier()
    await classifier.initialize()

    # Classify an email
    result = await classifier.classify_email(email)
    print(f"Spam: {result.is_spam} (confidence: {result.confidence})")

    # Train from user feedback
    await classifier.train_from_feedback(email_id, is_spam=True)

    # Use with email dict
    email_dict = {
        "id": "msg_123",
        "subject": "You won!",
        "body": "Click here to claim...",
        "sender": "prize@suspicious.tk",
        "headers": {...},
        "attachments": ["prize.exe"]
    }
    result = await classify_email(email_dict)
"""

# Re-export everything from the spam package for backwards compatibility.
# All public APIs that were previously defined in this module are now
# implemented in aragora.moderation.spam submodules.

# Models and data types
from aragora.moderation.spam.models import (  # noqa: F401
    EmailFeatures,
    SpamCategory,
    SpamClassificationResult,
    SpamClassifierConfig,
    SpamFeedback,
)

# Pattern constants
from aragora.moderation.spam.patterns import (  # noqa: F401
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

# Feature extraction
from aragora.moderation.spam.features import SpamFeatures  # noqa: F401

# ML model
from aragora.moderation.spam.model import NaiveBayesClassifier  # noqa: F401

# Classifier and convenience functions
from aragora.moderation.spam.classifier import (  # noqa: F401
    SpamClassifier,
    classify_email,
    classify_email_spam,
    classify_emails_batch,
)

__all__ = [
    # Core classes
    "SpamClassifier",
    "SpamClassifierConfig",
    "SpamClassificationResult",
    "SpamCategory",
    # Feature extraction
    "SpamFeatures",
    "EmailFeatures",
    # ML model
    "NaiveBayesClassifier",
    # Feedback tracking
    "SpamFeedback",
    # Convenience functions
    "classify_email",
    "classify_email_spam",
    "classify_emails_batch",
    # Pattern sets (for extension)
    "SPAM_WORDS",
    "URGENCY_WORDS",
    "MONEY_WORDS",
    "SUSPICIOUS_TLDS",
    "KNOWN_SPAM_DOMAINS",
    "FREE_EMAIL_PROVIDERS",
    "URL_SHORTENERS",
    "DANGEROUS_EXTENSIONS",
    "PROMOTIONAL_PATTERNS",
    "REQUIRED_HEADERS",
]
