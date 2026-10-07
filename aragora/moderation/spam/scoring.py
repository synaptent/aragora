"""
Rule-based spam scoring functions.

Provides scoring functions for each email component (content, sender,
headers, patterns, URLs, attachments, subject) as well as category
determination and phishing detection.
"""

from __future__ import annotations

import re

from aragora.moderation.spam.models import EmailFeatures, SpamCategory, SpamClassifierConfig


def score_content(content: str, features: EmailFeatures) -> float:
    """Score content for spam likelihood (0-1)."""
    score = 0.0

    # Spam word density
    if features.word_count > 0:
        spam_density = features.spam_word_count / features.word_count
        score += min(spam_density * 10, 0.3)

    # Urgency indicators
    urgency_score = min(features.urgency_word_count / 5, 0.2)
    score += urgency_score

    # Money indicators
    money_score = min(features.money_word_count / 5, 0.15)
    score += money_score

    # Formatting issues
    if features.uppercase_ratio > 0.3:
        score += 0.15
    if features.exclamation_count > 5:
        score += 0.1
    if features.all_caps_word_count > 5:
        score += 0.1

    return min(score, 1.0)


def score_sender(sender: str, features: EmailFeatures) -> float:
    """Score sender for spam likelihood (0-1)."""
    score = 0.0

    if features.sender_domain_suspicious:
        score += 0.4

    # Check for suspicious sender patterns
    if sender:
        sender_lower = sender.lower()
        if re.search(r"noreply|no-reply|donotreply", sender_lower):
            score += 0.1
        if re.search(r"\d{4,}", sender_lower):
            score += 0.15
        if not features.sender_has_display_name:
            score += 0.05

    if features.sender_previously_contacted:
        score -= 0.3

    return max(0.0, min(score, 1.0))


def score_headers(headers: dict[str, str], features: EmailFeatures) -> float:
    """Score headers for spam likelihood (0-1)."""
    score = 0.0

    # Missing authentication
    if not features.has_spf:
        score += 0.15
    if not features.has_dkim:
        score += 0.15
    if not features.has_dmarc:
        score += 0.1

    # Too many hops
    if features.received_hop_count > 8:
        score += 0.2

    # Suspicious headers
    if features.has_suspicious_headers:
        score += 0.2

    return min(score, 1.0)


def score_patterns(content: str, compiled_promotional: list[re.Pattern[str]]) -> float:
    """Score for known spam/promotional patterns (0-1)."""
    score = 0.0
    promotional_matches = 0

    for pattern in compiled_promotional:
        if pattern.search(content):
            promotional_matches += 1

    # High promotional content
    if promotional_matches >= 3:
        score += 0.3
    elif promotional_matches >= 1:
        score += 0.15

    # Common spam phrases
    spam_phrases = [
        r"act\s+now",
        r"limited\s+time",
        r"click\s+here\s+now",
        r"congratulations.*won",
        r"you\s+have\s+been\s+selected",
        r"100%\s+free",
        r"no\s+credit\s+card",
        r"risk[\s-]free",
        r"double\s+your",
        r"earn\s+\$?\d+",
    ]

    phrase_matches = sum(1 for phrase in spam_phrases if re.search(phrase, content, re.IGNORECASE))
    score += min(phrase_matches * 0.15, 0.5)

    return min(score, 1.0)


def score_urls(features: EmailFeatures) -> float:
    """Score URL-based spam indicators (0-1)."""
    score = 0.0

    # Shortened URLs are suspicious
    if features.shortened_url_count > 0:
        score += min(features.shortened_url_count * 0.15, 0.3)

    # Suspicious domain URLs
    if len(features.suspicious_domain_urls) > 0:
        score += min(len(features.suspicious_domain_urls) * 0.2, 0.4)

    # IP address URLs (very suspicious)
    if features.ip_address_urls > 0:
        score += min(features.ip_address_urls * 0.25, 0.4)

    # Mismatched anchor URLs (phishing indicator)
    if features.mismatched_anchor_urls > 0:
        score += min(features.mismatched_anchor_urls * 0.3, 0.5)

    # Data URIs can hide content
    if features.data_uri_count > 0:
        score += min(features.data_uri_count * 0.1, 0.2)

    # Too many links relative to content
    if features.word_count > 0 and features.link_count > 0:
        link_density = features.link_count / (features.word_count / 100)
        if link_density > 5:  # More than 5 links per 100 words
            score += 0.15

    return min(score, 1.0)


def score_attachments(features: EmailFeatures) -> float:
    """Score attachment-based spam/malware indicators (0-1)."""
    score = 0.0

    # Dangerous extensions
    if features.dangerous_extension_count > 0:
        score += min(features.dangerous_extension_count * 0.4, 0.8)

    # Double extensions (high risk)
    if features.double_extension_count > 0:
        score += min(features.double_extension_count * 0.5, 0.8)

    # Archive with executable (high risk)
    if features.archive_with_executable:
        score += 0.6

    return min(score, 1.0)


def score_subject(features: EmailFeatures) -> float:
    """Score subject line spam indicators (0-1)."""
    score = 0.0

    # ALL CAPS subject
    if features.subject_all_caps:
        score += 0.3

    # Excessive punctuation
    if features.subject_excessive_punctuation:
        score += 0.2

    # Spam words in subject
    if features.subject_spam_words > 0:
        score += min(features.subject_spam_words * 0.15, 0.4)

    # Very short subject (often spam)
    if features.subject_length < 5 and features.subject_length > 0:
        score += 0.1

    # Legitimate reply/forward patterns reduce score
    if features.subject_has_re_fw:
        score = max(0, score - 0.2)

    return min(score, 1.0)


def determine_category(
    spam_score: float,
    content: str,
    features: EmailFeatures,
    reasons: list[str],
    config: SpamClassifierConfig,
) -> tuple[SpamCategory, float]:
    """Determine spam category and confidence."""
    # Check for phishing indicators
    phishing_score = check_phishing(content, features)
    if phishing_score > 0.7:
        reasons.append("High phishing indicators")
        return SpamCategory.PHISHING, phishing_score

    # High spam score
    if spam_score >= config.spam_threshold:
        reasons.append(f"High spam score: {spam_score:.2f}")
        confidence = min(spam_score * 1.2, 1.0)
        return SpamCategory.SPAM, confidence

    # Promotional content
    if spam_score >= config.promotional_threshold and features.has_unsubscribe:
        reasons.append("Promotional email with unsubscribe link")
        return SpamCategory.PROMOTIONAL, spam_score * 0.9

    # Suspicious but not definitive
    if spam_score >= config.suspicious_threshold:
        reasons.append(f"Suspicious patterns: {spam_score:.2f}")
        return SpamCategory.SUSPICIOUS, spam_score

    # Ham (not spam)
    confidence = 1.0 - spam_score
    return SpamCategory.HAM, confidence


def check_phishing(content: str, features: EmailFeatures) -> float:
    """Check for phishing indicators."""
    score = 0.0

    # Suspicious links
    if features.suspicious_link_count > 0:
        score += 0.3

    # Mismatched anchor URLs (strong phishing indicator)
    if features.mismatched_anchor_urls > 0:
        score += 0.4

    # IP address URLs (very suspicious)
    if features.ip_address_urls > 0:
        score += 0.3

    # Urgency + action required
    if features.urgency_word_count >= 2:
        score += 0.2

    # Form elements in email (credential harvesting)
    if features.has_form_elements:
        score += 0.4

    # Known spam domain sender
    if features.sender_is_known_spam_domain:
        score += 0.3

    # Common phishing phrases
    phishing_phrases = [
        r"verify\s+your\s+account",
        r"confirm\s+your\s+identity",
        r"update\s+your\s+payment",
        r"account\s+(suspended|disabled|locked)",
        r"unusual\s+activity",
        r"security\s+alert",
        r"password\s+expir",
        r"click\s+.*\s+verify",
        r"within\s+24\s+hours",
        r"your\s+account\s+will\s+be",
        r"immediately\s+verify",
        r"confirm\s+your\s+bank",
        r"ssn|social\s+security",
        r"credit\s+card\s+number",
    ]

    matches = sum(1 for phrase in phishing_phrases if re.search(phrase, content, re.IGNORECASE))
    score += min(matches * 0.15, 0.5)

    return min(score, 1.0)
