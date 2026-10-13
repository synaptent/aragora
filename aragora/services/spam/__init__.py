"""
ML-Enhanced Spam Classification Service (compatibility re-export).

The implementation moved to :mod:`aragora.moderation.spam`; every name below is
the identical object.

Provides machine learning-based spam detection with online learning
from user feedback. Falls back to rule-based classification when
model confidence is low.

Features:
- Feature extraction from email content, headers, and sender patterns
- Domain reputation scoring (known spam domains, free email providers)
- Subject line analysis (spam keywords, excessive punctuation, ALL CAPS ratio)
- Content n-grams (unigrams, bigrams) for statistical classification
- Header analysis (missing headers, suspicious routing, authentication)
- URL analysis (shortened URLs, suspicious domains, redirect detection)
- Attachment analysis (dangerous extensions, executable files)
- Online learning from user actions (mark as spam, not spam)
- Confidence scoring with fallback to heuristics
- Persistent model storage
- Batch classification support
- Integration with EmailPrioritizer for inbox scoring

Usage:
    from aragora.moderation.spam import SpamClassifier

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

# Models and data types
from aragora.moderation.spam.models import (
    EmailFeatures,
    SpamCategory,
    SpamClassificationResult,
    SpamClassifierConfig,
    SpamFeedback,
)

# Pattern constants
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

# Feature extraction
from aragora.moderation.spam.features import SpamFeatures

# ML model
from aragora.moderation.spam.model import NaiveBayesClassifier

# Classifier and convenience functions
from aragora.moderation.spam.classifier import (
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
