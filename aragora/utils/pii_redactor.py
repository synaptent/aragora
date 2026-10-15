"""
PII Redaction Service.

Sanitizes text content by detecting and redacting Personally Identifiable Information (PII)
before sending to LLMs for analysis. Supports:

- Email addresses
- Phone numbers (US, international)
- Social Security Numbers (SSN)
- Credit card numbers
- IP addresses
- Physical addresses (partial)
- Names (when context available)
- Dates of birth

Usage:
    from aragora.utils.pii_redactor import PIIRedactor

    redactor = PIIRedactor()
    sanitized_text = redactor.redact(text)
    sanitized_email = redactor.redact_email(email_message)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from re import Pattern

logger = logging.getLogger(__name__)


class PIIType(str, Enum):
    """Types of PII that can be detected and redacted."""

    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    ADDRESS = "address"
    DATE_OF_BIRTH = "dob"
    PASSPORT = "passport"
    DRIVERS_LICENSE = "drivers_license"
    BANK_ACCOUNT = "bank_account"
    MEDICAL_ID = "medical_id"


@dataclass
class PIIMatch:
    """A detected PII match in text."""

    pii_type: PIIType
    original: str
    redacted: str
    start: int
    end: int
    confidence: float = 1.0


@dataclass
class RedactionResult:
    """Result of PII redaction."""

    original_text: str
    redacted_text: str
    matches: list[PIIMatch] = field(default_factory=list)
    pii_types_found: list[PIIType] = field(default_factory=list)

    @property
    def has_pii(self) -> bool:
        """Whether any PII was detected."""
        return len(self.matches) > 0

    @property
    def match_count(self) -> int:
        """Number of PII matches found."""
        return len(self.matches)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/audit."""
        return {
            "has_pii": self.has_pii,
            "match_count": self.match_count,
            "pii_types": [t.value for t in self.pii_types_found],
            "matches": [
                {
                    "type": m.pii_type.value,
                    "redacted_to": m.redacted,
                    "confidence": m.confidence,
                }
                for m in self.matches
            ],
        }


class PIIRedactor:
    """
    Service for detecting and redacting PII from text.

    Designed for email content sanitization before LLM analysis.
    """

    # Redaction placeholders
    PLACEHOLDERS = {
        PIIType.EMAIL: "[EMAIL_REDACTED]",
        PIIType.PHONE: "[PHONE_REDACTED]",
        PIIType.SSN: "[SSN_REDACTED]",
        PIIType.CREDIT_CARD: "[CARD_REDACTED]",
        PIIType.IP_ADDRESS: "[IP_REDACTED]",
        PIIType.ADDRESS: "[ADDRESS_REDACTED]",
        PIIType.DATE_OF_BIRTH: "[DOB_REDACTED]",
        PIIType.PASSPORT: "[PASSPORT_REDACTED]",
        PIIType.DRIVERS_LICENSE: "[LICENSE_REDACTED]",
        PIIType.BANK_ACCOUNT: "[ACCOUNT_REDACTED]",
        PIIType.MEDICAL_ID: "[MEDICAL_ID_REDACTED]",
    }

    def __init__(
        self,
        enabled_types: list[PIIType] | None = None,
        preserve_domains: list[str] | None = None,
        log_redactions: bool = True,
    ):
        """
        Initialize PII redactor.

        Args:
            enabled_types: Types of PII to redact. If None, all types enabled.
            preserve_domains: Email domains to NOT redact (e.g., company domains)
            log_redactions: Whether to log redaction events
        """
        self.enabled_types = enabled_types or list(PIIType)
        self.preserve_domains = [d.lower() for d in (preserve_domains or [])]
        self.log_redactions = log_redactions

        # Compile regex patterns
        self._patterns: dict[PIIType, list[tuple[Pattern[str], float]]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for PII detection."""

        # Email addresses
        self._patterns[PIIType.EMAIL] = [
            (
                re.compile(
                    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
                    re.IGNORECASE,
                ),
                1.0,
            ),
        ]

        # Phone numbers (various formats)
        self._patterns[PIIType.PHONE] = [
            # US formats: (123) 456-7890, 123-456-7890, 123.456.7890
            (re.compile(r"\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"), 0.9),
            # International: +1 123 456 7890
            (re.compile(r"\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}\b"), 0.9),
            # Simple 10-digit
            (re.compile(r"\b\d{10}\b"), 0.7),
        ]

        # SSN: 123-45-6789 or 123456789
        self._patterns[PIIType.SSN] = [
            (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), 1.0),
            (re.compile(r"\b\d{9}\b"), 0.5),  # Lower confidence without dashes
        ]

        # Credit card numbers (basic patterns)
        self._patterns[PIIType.CREDIT_CARD] = [
            # With separators
            (re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"), 0.95),
            # Visa, MC, Amex patterns
            (re.compile(r"\b(?:4\d{15}|5[1-5]\d{14}|3[47]\d{13})\b"), 0.9),
        ]

        # IP addresses
        self._patterns[PIIType.IP_ADDRESS] = [
            # IPv4
            (
                re.compile(
                    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}"
                    r"(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
                ),
                1.0,
            ),
        ]

        # Date of birth patterns
        self._patterns[PIIType.DATE_OF_BIRTH] = [
            # DOB: MM/DD/YYYY or MM-DD-YYYY with context
            (
                re.compile(
                    r"(?:DOB|date\s*of\s*birth|born|birthday)[:\s]*"
                    r"(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})",
                    re.IGNORECASE,
                ),
                1.0,
            ),
        ]

        # Bank account numbers (with context)
        self._patterns[PIIType.BANK_ACCOUNT] = [
            (
                re.compile(r"(?:account|acct|routing)[:\s#]*(\d{8,17})", re.IGNORECASE),
                0.9,
            ),
        ]

        # Medical IDs (with context)
        self._patterns[PIIType.MEDICAL_ID] = [
            (
                re.compile(
                    r"(?:MRN|patient\s*id|medical\s*record)[:\s#]*(\w{5,15})",
                    re.IGNORECASE,
                ),
                0.9,
            ),
        ]

        # Passport numbers (with context)
        self._patterns[PIIType.PASSPORT] = [
            (
                re.compile(r"(?:passport)[:\s#]*([A-Z0-9]{6,9})", re.IGNORECASE),
                0.9,
            ),
        ]

        # Driver's license (with context)
        self._patterns[PIIType.DRIVERS_LICENSE] = [
            (
                re.compile(
                    r"(?:driver'?s?\s*license|DL)[:\s#]*([A-Z0-9]{5,15})",
                    re.IGNORECASE,
                ),
                0.9,
            ),
        ]

        # Address patterns (basic street address)
        self._patterns[PIIType.ADDRESS] = [
            (
                re.compile(
                    r"\b\d{1,5}\s+[A-Za-z]+(?:\s+[A-Za-z]+)*"
                    r"\s+(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Drive|Dr|"
                    r"Lane|Ln|Way|Court|Ct|Circle|Cir|Place|Pl)\b",
                    re.IGNORECASE,
                ),
                0.8,
            ),
        ]

    def redact(self, text: str) -> RedactionResult:
        """
        Detect and redact PII from text.

        Args:
            text: Input text to scan for PII

        Returns:
            RedactionResult with redacted text and match details
        """
        if not text:
            return RedactionResult(original_text="", redacted_text="", matches=[])

        matches: list[PIIMatch] = []
        redacted_text = text

        for pii_type in self.enabled_types:
            if pii_type not in self._patterns:
                continue

            for pattern, confidence in self._patterns[pii_type]:
                for match in pattern.finditer(text):
                    original = match.group(0)

                    # Check if this is an email we should preserve
                    if pii_type == PIIType.EMAIL:
                        domain = original.split("@")[-1].lower()
                        if domain in self.preserve_domains:
                            continue

                    placeholder = self.PLACEHOLDERS[pii_type]
                    pii_match = PIIMatch(
                        pii_type=pii_type,
                        original=original,
                        redacted=placeholder,
                        start=match.start(),
                        end=match.end(),
                        confidence=confidence,
                    )
                    matches.append(pii_match)

        # Sort matches by position (reverse) to replace from end to start
        matches.sort(key=lambda m: m.start, reverse=True)

        # Apply redactions
        for pii_match in matches:
            redacted_text = (
                redacted_text[: pii_match.start]
                + pii_match.redacted
                + redacted_text[pii_match.end :]
            )

        # Get unique PII types found
        pii_types_found = list(set(m.pii_type for m in matches))

        result = RedactionResult(
            original_text=text,
            redacted_text=redacted_text,
            matches=matches,
            pii_types_found=pii_types_found,
        )

        if self.log_redactions and result.has_pii:
            logger.info(
                "[PIIRedactor] Redacted %s PII items: %s",
                result.match_count,
                [t.value for t in pii_types_found],
            )

        return result

    def redact_email(
        self,
        email_message: Any,
        redact_subject: bool = True,
        redact_body: bool = True,
        redact_sender: bool = False,
    ) -> tuple[Any, dict[str, RedactionResult]]:
        """
        Redact PII from an email message.

        Args:
            email_message: EmailMessage object with subject, body_text, from_address
            redact_subject: Whether to redact PII in subject
            redact_body: Whether to redact PII in body
            redact_sender: Whether to redact sender email

        Returns:
            Tuple of (modified_email, dict of field -> RedactionResult)
        """
        results: dict[str, RedactionResult] = {}

        if redact_subject and hasattr(email_message, "subject"):
            result = self.redact(email_message.subject or "")
            if result.has_pii:
                email_message.subject = result.redacted_text
            results["subject"] = result

        if redact_body and hasattr(email_message, "body_text"):
            result = self.redact(email_message.body_text or "")
            if result.has_pii:
                email_message.body_text = result.redacted_text
            results["body"] = result

        if redact_sender and hasattr(email_message, "from_address"):
            result = self.redact(email_message.from_address or "")
            if result.has_pii:
                email_message.from_address = result.redacted_text
            results["sender"] = result

        return email_message, results

    def redact_dict(
        self,
        data: dict[str, Any],
        fields_to_redact: list[str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, RedactionResult]]:
        """
        Redact PII from dictionary fields.

        Args:
            data: Dictionary with string values to redact
            fields_to_redact: Specific fields to redact. If None, redacts all string fields.

        Returns:
            Tuple of (modified_dict, dict of field -> RedactionResult)
        """
        results: dict[str, RedactionResult] = {}
        modified_data = data.copy()

        for key, value in data.items():
            if not isinstance(value, str):
                continue

            if fields_to_redact and key not in fields_to_redact:
                continue

            result = self.redact(value)
            if result.has_pii:
                modified_data[key] = result.redacted_text
            results[key] = result

        return modified_data, results


# Singleton instance for convenience
_default_redactor: PIIRedactor | None = None


def get_pii_redactor(
    preserve_domains: list[str] | None = None,
) -> PIIRedactor:
    """Get or create the default PII redactor."""
    global _default_redactor
    if _default_redactor is None:
        _default_redactor = PIIRedactor(preserve_domains=preserve_domains)
    return _default_redactor


def redact_text(text: str) -> str:
    """Convenience function to redact PII from text."""
    redactor = get_pii_redactor()
    result = redactor.redact(text)
    return result.redacted_text
