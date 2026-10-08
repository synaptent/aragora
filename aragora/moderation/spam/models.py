"""
Spam classification data models and configuration.

Contains all dataclasses, enums, and configuration types used
across the spam classification system.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class SpamCategory(Enum):
    """Spam classification categories."""

    HAM = "ham"  # Not spam
    SPAM = "spam"  # Definitely spam
    PROMOTIONAL = "promotional"  # Marketing/promotional
    SUSPICIOUS = "suspicious"  # Possibly spam
    PHISHING = "phishing"  # Phishing attempt


@dataclass
class SpamClassificationResult:
    """Result of spam classification."""

    email_id: str
    is_spam: bool
    category: SpamCategory
    confidence: float  # 0.0 to 1.0
    spam_score: float  # 0.0 to 1.0 (higher = more spammy)

    # Feature contributions
    content_score: float = 0.0
    sender_score: float = 0.0
    header_score: float = 0.0
    pattern_score: float = 0.0
    url_score: float = 0.0
    attachment_score: float = 0.0
    subject_score: float = 0.0

    # Reasoning
    reasons: list[str] = field(default_factory=list)
    model_used: str = "rule_based"

    # Detected threats
    suspicious_urls: list[str] = field(default_factory=list)
    dangerous_attachments: list[str] = field(default_factory=list)

    # Metadata
    classified_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "email_id": self.email_id,
            "is_spam": self.is_spam,
            "category": self.category.value,
            "confidence": self.confidence,
            "spam_score": self.spam_score,
            "scores": {
                "content": self.content_score,
                "sender": self.sender_score,
                "header": self.header_score,
                "pattern": self.pattern_score,
                "url": self.url_score,
                "attachment": self.attachment_score,
                "subject": self.subject_score,
            },
            "reasons": self.reasons,
            "model_used": self.model_used,
            "suspicious_urls": self.suspicious_urls,
            "dangerous_attachments": self.dangerous_attachments,
            "classified_at": self.classified_at.isoformat(),
        }

    def get_priority_penalty(self) -> float:
        """
        Get priority penalty for email prioritization integration.

        Returns a value between 0 and 1 that can be used to reduce
        email priority based on spam likelihood.

        Returns:
            Priority penalty (0 = no penalty, 1 = maximum penalty)
        """
        if self.is_spam:
            return 1.0
        if self.category == SpamCategory.PHISHING:
            return 0.9  # High penalty but keep visible for review
        if self.category == SpamCategory.SUSPICIOUS:
            return 0.5
        if self.category == SpamCategory.PROMOTIONAL:
            return 0.3
        return 0.0


@dataclass
class EmailFeatures:
    """Extracted features from an email for classification."""

    # Content features
    word_count: int = 0
    char_count: int = 0
    uppercase_ratio: float = 0.0
    digit_ratio: float = 0.0
    special_char_ratio: float = 0.0
    link_count: int = 0
    suspicious_link_count: int = 0
    attachment_count: int = 0

    # Text patterns
    spam_word_count: int = 0
    urgency_word_count: int = 0
    money_word_count: int = 0
    exclamation_count: int = 0
    question_count: int = 0
    all_caps_word_count: int = 0

    # Subject line features
    subject_all_caps: bool = False
    subject_excessive_punctuation: bool = False
    subject_spam_words: int = 0
    subject_length: int = 0
    subject_has_re_fw: bool = False

    # Sender features
    sender_domain_age_days: int = -1  # -1 = unknown
    sender_has_display_name: bool = False
    sender_domain_suspicious: bool = False
    sender_in_reply_chain: bool = False
    sender_previously_contacted: bool = False
    sender_domain_is_free_email: bool = False
    sender_domain_reputation: float = 0.5  # 0-1, 0.5 = neutral
    sender_is_known_spam_domain: bool = False

    # Header features
    has_spf: bool = False
    has_dkim: bool = False
    has_dmarc: bool = False
    received_hop_count: int = 0
    has_suspicious_headers: bool = False
    missing_required_headers: list[str] = field(default_factory=list)
    has_suspicious_routing: bool = False
    has_forged_headers: bool = False

    # URL features
    shortened_url_count: int = 0
    suspicious_domain_urls: list[str] = field(default_factory=list)
    mismatched_anchor_urls: int = 0  # <a href="X">Y</a> where X != Y
    ip_address_urls: int = 0  # URLs with IP addresses instead of domains
    data_uri_count: int = 0  # data: URIs (can hide content)

    # Attachment features
    dangerous_extension_count: int = 0
    dangerous_attachments: list[str] = field(default_factory=list)
    double_extension_count: int = 0  # e.g., "document.pdf.exe"
    archive_with_executable: bool = False

    # Structure features
    html_text_ratio: float = 0.0
    has_images: bool = False
    image_only_email: bool = False
    has_unsubscribe: bool = False
    has_tracking_pixels: bool = False
    has_hidden_text: bool = False  # White text on white background, etc.
    has_form_elements: bool = False  # Forms in email (phishing indicator)

    # N-gram features (populated during extraction)
    top_unigrams: list[tuple[str, int]] = field(default_factory=list)
    top_bigrams: list[tuple[str, int]] = field(default_factory=list)

    def to_vector(self) -> list[float]:
        """Convert to feature vector for ML model."""
        return [
            self.word_count / 1000,  # Normalize
            self.char_count / 10000,
            self.uppercase_ratio,
            self.digit_ratio,
            self.special_char_ratio,
            self.link_count / 10,
            self.suspicious_link_count / 5,
            self.attachment_count / 3,
            self.spam_word_count / 10,
            self.urgency_word_count / 5,
            self.money_word_count / 5,
            self.exclamation_count / 10,
            self.question_count / 10,
            self.all_caps_word_count / 10,
            # Subject features
            1.0 if self.subject_all_caps else 0.0,
            1.0 if self.subject_excessive_punctuation else 0.0,
            self.subject_spam_words / 5,
            min(self.subject_length / 100, 1.0),
            # Sender features
            1.0 if self.sender_domain_suspicious else 0.0,
            1.0 if self.sender_has_display_name else 0.0,
            1.0 if self.sender_previously_contacted else 0.0,
            1.0 if self.sender_domain_is_free_email else 0.0,
            self.sender_domain_reputation,
            1.0 if self.sender_is_known_spam_domain else 0.0,
            # Header features
            1.0 if self.has_spf else 0.0,
            1.0 if self.has_dkim else 0.0,
            1.0 if self.has_dmarc else 0.0,
            min(self.received_hop_count / 10, 1.0),
            1.0 if self.has_suspicious_headers else 0.0,
            min(len(self.missing_required_headers) / 5, 1.0),
            1.0 if self.has_suspicious_routing else 0.0,
            1.0 if self.has_forged_headers else 0.0,
            # URL features
            min(self.shortened_url_count / 5, 1.0),
            min(len(self.suspicious_domain_urls) / 5, 1.0),
            min(self.mismatched_anchor_urls / 5, 1.0),
            min(self.ip_address_urls / 3, 1.0),
            min(self.data_uri_count / 3, 1.0),
            # Attachment features
            min(self.dangerous_extension_count / 3, 1.0),
            min(self.double_extension_count / 2, 1.0),
            1.0 if self.archive_with_executable else 0.0,
            # Structure features
            self.html_text_ratio,
            1.0 if self.image_only_email else 0.0,
            1.0 if self.has_unsubscribe else 0.0,
            1.0 if self.has_tracking_pixels else 0.0,
            1.0 if self.has_hidden_text else 0.0,
            1.0 if self.has_form_elements else 0.0,
        ]

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for storage/logging."""
        return {
            "word_count": self.word_count,
            "char_count": self.char_count,
            "uppercase_ratio": self.uppercase_ratio,
            "link_count": self.link_count,
            "suspicious_link_count": self.suspicious_link_count,
            "spam_word_count": self.spam_word_count,
            "subject_all_caps": self.subject_all_caps,
            "subject_excessive_punctuation": self.subject_excessive_punctuation,
            "sender_domain_suspicious": self.sender_domain_suspicious,
            "sender_is_known_spam_domain": self.sender_is_known_spam_domain,
            "has_spf": self.has_spf,
            "has_dkim": self.has_dkim,
            "shortened_url_count": self.shortened_url_count,
            "dangerous_extension_count": self.dangerous_extension_count,
            "dangerous_attachments": self.dangerous_attachments,
            "top_unigrams": self.top_unigrams[:10],
            "top_bigrams": self.top_bigrams[:10],
        }


@dataclass
class SpamClassifierConfig:
    """Configuration for spam classifier."""

    # Model settings
    model_path: str = "spam_model.pkl"
    use_ml_model: bool = True
    min_confidence_for_ml: float = 0.7

    # Training settings
    min_training_samples: int = 100
    retrain_interval_hours: int = 24
    max_training_samples: int = 10000

    # Feature extraction
    max_content_length: int = 50000

    # Classification thresholds
    spam_threshold: float = 0.6
    promotional_threshold: float = 0.4
    suspicious_threshold: float = 0.3

    # Storage
    feedback_db_path: str = "spam_feedback.db"


@dataclass
class SpamFeedback:
    """
    User feedback on spam classification.

    Used for online learning and model improvement.
    """

    email_id: str
    user_id: str
    is_spam: bool
    original_classification: SpamCategory
    original_confidence: float
    feedback_type: str = "explicit"  # "explicit" (user marked) or "implicit" (user action)
    content_hash: str | None = None
    features_json: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "email_id": self.email_id,
            "user_id": self.user_id,
            "is_spam": self.is_spam,
            "original_classification": self.original_classification.value,
            "original_confidence": self.original_confidence,
            "feedback_type": self.feedback_type,
            "content_hash": self.content_hash,
            "created_at": self.created_at.isoformat(),
        }
