"""
Feature extraction engine for spam classification.

Extracts comprehensive features from email content, headers,
sender information, URLs, and attachments for use in both
ML-based and rule-based classification.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from aragora.moderation.spam.models import EmailFeatures
from aragora.moderation.spam.patterns import (
    DANGEROUS_EXTENSIONS,
    FREE_EMAIL_PROVIDERS,
    KNOWN_SPAM_DOMAINS,
    MONEY_WORDS,
    REQUIRED_HEADERS,
    SPAM_WORDS,
    SUSPICIOUS_TLDS,
    URGENCY_WORDS,
    URL_SHORTENERS,
)

if TYPE_CHECKING:
    from aragora.services.sender_history import SenderHistoryService


class SpamFeatures:
    """
    Feature extraction engine for spam classification.

    Extracts comprehensive features from email content, headers,
    sender information, URLs, and attachments.
    """

    def __init__(
        self,
        sender_history_service: SenderHistoryService | None = None,
        user_id: str | None = None,
    ):
        """
        Initialize feature extractor.

        Args:
            sender_history_service: Optional service for sender reputation
            user_id: User ID for sender history lookups
        """
        self.sender_history = sender_history_service
        self.user_id = user_id

        # Compile regex patterns
        self._url_pattern = re.compile(r'https?://[^\s<>"{}|\\^`\[\]]+', re.IGNORECASE)
        self._email_pattern = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
        self._ip_url_pattern = re.compile(r"https?://\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}")
        self._anchor_pattern = re.compile(
            r'<a[^>]*href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', re.IGNORECASE
        )
        self._form_pattern = re.compile(r"<form[^>]*>", re.IGNORECASE)
        self._hidden_text_pattern = re.compile(
            r"(?:color:\s*(?:white|#fff|#ffffff|transparent)|" r"font-size:\s*0|display:\s*none)",
            re.IGNORECASE,
        )
        self._data_uri_pattern = re.compile(r"data:[^;]+;base64,", re.IGNORECASE)

    def extract(
        self,
        subject: str,
        body: str,
        sender: str,
        headers: dict[str, str] | None = None,
        attachments: list[str] | None = None,
    ) -> EmailFeatures:
        """
        Extract all features from an email.

        Args:
            subject: Email subject
            body: Email body (plain text or HTML)
            sender: Sender email address
            headers: Optional email headers dict
            attachments: Optional list of attachment filenames

        Returns:
            EmailFeatures with all extracted features
        """
        features = EmailFeatures()
        headers = headers or {}
        attachments = attachments or []

        # Extract features from each component
        self._extract_content_features(features, subject, body)
        self._extract_subject_features(features, subject)
        self._extract_sender_features(features, sender)
        self._extract_header_features(features, headers)
        self._extract_url_features(features, body)
        self._extract_attachment_features(features, attachments)
        self._extract_ngrams(features, f"{subject} {body}")

        return features

    def _extract_content_features(
        self,
        features: EmailFeatures,
        subject: str,
        body: str,
    ) -> None:
        """Extract content-based features."""
        content = f"{subject}\n\n{body}"
        features.char_count = len(content)

        words = content.split()
        features.word_count = len(words)

        if features.char_count > 0:
            features.uppercase_ratio = sum(1 for c in content if c.isupper()) / features.char_count
            features.digit_ratio = sum(1 for c in content if c.isdigit()) / features.char_count
            features.special_char_ratio = (
                sum(1 for c in content if not c.isalnum() and not c.isspace()) / features.char_count
            )

        # Count various patterns
        content_lower = content.lower()
        features.spam_word_count = sum(1 for word in SPAM_WORDS if word in content_lower)
        features.urgency_word_count = sum(1 for word in URGENCY_WORDS if word in content_lower)
        features.money_word_count = sum(1 for word in MONEY_WORDS if word in content_lower)
        features.exclamation_count = content.count("!")
        features.question_count = content.count("?")
        features.all_caps_word_count = sum(1 for word in words if word.isupper() and len(word) > 2)

        # HTML analysis
        html_count = content.count("<") + content.count(">")
        text_content = re.sub(r"<[^>]+>", "", content)
        if len(text_content) > 0:
            features.html_text_ratio = min(html_count / len(text_content), 1.0)

        features.has_images = "<img" in content.lower() or "image" in content.lower()
        features.image_only_email = (
            features.has_images and features.word_count < 50 and "<img" in content.lower()
        )
        features.has_unsubscribe = "unsubscribe" in content_lower
        features.has_tracking_pixels = bool(
            re.search(
                r"<img[^>]*(?:1x1|pixel|track|beacon|width=[\"']?1|height=[\"']?1)[^>]*>",
                content,
                re.IGNORECASE,
            )
        )
        features.has_hidden_text = bool(self._hidden_text_pattern.search(content))
        features.has_form_elements = bool(self._form_pattern.search(content))

    def _extract_subject_features(self, features: EmailFeatures, subject: str) -> None:
        """Extract subject line specific features."""
        features.subject_length = len(subject)

        # Check if subject is all caps (excluding short subjects)
        if len(subject) > 5:
            alpha_chars = [c for c in subject if c.isalpha()]
            if alpha_chars:
                caps_ratio = sum(1 for c in alpha_chars if c.isupper()) / len(alpha_chars)
                features.subject_all_caps = caps_ratio > 0.8

        # Check for excessive punctuation
        punct_count = sum(1 for c in subject if c in "!?$*#@")
        if len(subject) > 0:
            features.subject_excessive_punctuation = punct_count / len(subject) > 0.1

        # Count spam words in subject
        subject_lower = subject.lower()
        features.subject_spam_words = sum(1 for word in SPAM_WORDS if word in subject_lower)

        # Check for Re:/Fw: patterns (legitimate replies/forwards)
        features.subject_has_re_fw = bool(re.match(r"^(re|fw|fwd):\s*", subject, re.IGNORECASE))

    def _extract_sender_features(self, features: EmailFeatures, sender: str) -> None:
        """Extract sender-related features."""
        if not sender:
            return

        features.sender_has_display_name = "<" in sender

        # Extract domain
        match = self._email_pattern.search(sender)
        if match:
            email = match.group(0).lower()
            domain = email.split("@")[-1]

            # Check various domain characteristics
            features.sender_domain_is_free_email = domain in FREE_EMAIL_PROVIDERS
            features.sender_is_known_spam_domain = domain in KNOWN_SPAM_DOMAINS
            features.sender_domain_suspicious = any(domain.endswith(tld) for tld in SUSPICIOUS_TLDS)

            # Check for suspicious sender patterns
            if re.search(r"noreply|no-reply|donotreply", email):
                pass  # Not necessarily spam, but tracked
            if re.search(r"\d{4,}", email):
                features.sender_domain_suspicious = True

    def _extract_header_features(
        self,
        features: EmailFeatures,
        headers: dict[str, str],
    ) -> None:
        """Extract header-based features."""
        if not headers:
            return

        # Normalize header names to lowercase for comparison
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Check for missing required headers
        features.missing_required_headers = [h for h in REQUIRED_HEADERS if h not in headers_lower]

        # Authentication checks
        auth_results = headers_lower.get("authentication-results", "").lower()
        features.has_spf = "spf=pass" in auth_results
        features.has_dkim = "dkim=pass" in auth_results
        features.has_dmarc = "dmarc=pass" in auth_results

        # Count received headers (hop count)
        features.received_hop_count = sum(1 for h in headers.keys() if h.lower() == "received")

        # Check for suspicious headers
        features.has_suspicious_headers = (
            "x-mailer" in headers_lower and "bulk" in headers_lower.get("precedence", "").lower()
        )

        # Check for suspicious routing
        received_headers = [v for k, v in headers.items() if k.lower() == "received"]
        if len(received_headers) > 8:
            features.has_suspicious_routing = True

        # Check for potentially forged headers
        if "x-originating-ip" in headers_lower:
            # Verify IP matches other routing information
            pass  # Advanced forgery detection would go here

    def _extract_url_features(self, features: EmailFeatures, body: str) -> None:
        """Extract URL-based features."""
        urls = self._url_pattern.findall(body)
        features.link_count = len(urls)

        for url in urls:
            try:
                parsed = urlparse(url)
                domain = parsed.netloc.lower()

                # Check for URL shorteners
                if domain in URL_SHORTENERS or any(
                    domain.endswith(f".{s}") for s in URL_SHORTENERS
                ):
                    features.shortened_url_count += 1

                # Check for suspicious TLDs
                if any(domain.endswith(tld) for tld in SUSPICIOUS_TLDS):
                    features.suspicious_link_count += 1
                    features.suspicious_domain_urls.append(url)

                # Check for IP address URLs
                if self._ip_url_pattern.match(url):
                    features.ip_address_urls += 1
                    features.suspicious_domain_urls.append(url)

            except (ValueError, AttributeError):
                # Skip malformed URLs
                continue

        # Check for mismatched anchor URLs (phishing indicator)
        anchors = self._anchor_pattern.findall(body)
        for href, text in anchors:
            # If anchor text looks like a URL but doesn't match href
            if re.match(r"https?://", text.strip()):
                text_domain = urlparse(text.strip()).netloc.lower()
                href_domain = urlparse(href).netloc.lower()
                if text_domain and href_domain and text_domain != href_domain:
                    features.mismatched_anchor_urls += 1

        # Count data URIs
        features.data_uri_count = len(self._data_uri_pattern.findall(body))

    def _extract_attachment_features(
        self,
        features: EmailFeatures,
        attachments: list[str],
    ) -> None:
        """Extract attachment-based features."""
        features.attachment_count = len(attachments)

        for attachment in attachments:
            attachment_lower = attachment.lower()

            # Check for dangerous extensions
            for ext in DANGEROUS_EXTENSIONS:
                if attachment_lower.endswith(ext):
                    features.dangerous_extension_count += 1
                    features.dangerous_attachments.append(attachment)
                    break

            # Check for double extensions (e.g., "document.pdf.exe")
            parts = attachment.split(".")
            if len(parts) >= 3:
                # Check if final extension is dangerous and preceded by benign extension
                if any(attachment_lower.endswith(ext) for ext in DANGEROUS_EXTENSIONS):
                    benign_extensions = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".jpg"}
                    second_to_last = f".{parts[-2].lower()}"
                    if second_to_last in benign_extensions:
                        features.double_extension_count += 1

            # Check for archives that might contain executables
            archive_extensions = {".zip", ".rar", ".7z", ".tar", ".gz"}
            if any(attachment_lower.endswith(ext) for ext in archive_extensions):
                # Flag as potential concern (would need to scan content for certainty)
                pass

    def _extract_ngrams(self, features: EmailFeatures, text: str, n_top: int = 20) -> None:
        """Extract unigram and bigram features."""
        # Tokenize
        words = re.findall(r"\b[a-z]{2,15}\b", text.lower())

        # Unigrams
        unigram_counts = Counter(words)
        features.top_unigrams = unigram_counts.most_common(n_top)

        # Bigrams
        bigrams = [f"{words[i]} {words[i + 1]}" for i in range(len(words) - 1)]
        bigram_counts = Counter(bigrams)
        features.top_bigrams = bigram_counts.most_common(n_top)
