"""
Sensitivity Classifier.

Classifies documents and data by sensitivity level.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SensitivityLevel(str, Enum):
    """Data sensitivity levels."""

    PUBLIC = "public"  # Can be shared publicly
    INTERNAL = "internal"  # Internal use only
    CONFIDENTIAL = "confidential"  # Restricted access
    RESTRICTED = "restricted"  # Highly restricted
    TOP_SECRET = "top_secret"  # noqa: S105 -- enum value (maximum restriction)


@dataclass
class SensitivityIndicator:
    """An indicator that suggests a sensitivity level."""

    name: str
    pattern: str  # Regex pattern
    level: SensitivityLevel
    confidence: float = 0.8
    description: str = ""


@dataclass
class ClassificationConfig:
    """Configuration for sensitivity classification."""

    # Default level when no indicators found
    default_level: SensitivityLevel = SensitivityLevel.INTERNAL

    # Minimum confidence for classification
    min_confidence: float = 0.6

    # Use LLM for enhanced classification
    use_llm: bool = False
    llm_model: str = "claude-opus-5"

    # Custom indicators
    custom_indicators: list[SensitivityIndicator] = field(default_factory=list)


@dataclass
class IndicatorMatch:
    """A matched sensitivity indicator."""

    indicator: SensitivityIndicator
    match_text: str
    position: int
    confidence: float


@dataclass
class ClassificationResult:
    """Result of sensitivity classification."""

    level: SensitivityLevel
    confidence: float
    classified_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Supporting evidence
    indicators_found: list[IndicatorMatch] = field(default_factory=list)
    pii_detected: bool = False
    secrets_detected: bool = False

    # Metadata
    document_id: str = ""
    content_length: int = 0
    classification_method: str = "rule_based"

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "level": self.level.value,
            "confidence": self.confidence,
            "classified_at": self.classified_at.isoformat(),
            "pii_detected": self.pii_detected,
            "secrets_detected": self.secrets_detected,
            "indicators_found": len(self.indicators_found),
            "classification_method": self.classification_method,
        }


class SensitivityClassifier:
    """
    Classifies documents and data by sensitivity level.

    Uses a combination of:
    - Pattern matching for known sensitive data
    - PII detection
    - Secrets detection
    - Optional LLM-based classification
    """

    # Default indicators for each sensitivity level
    DEFAULT_INDICATORS = [
        # TOP SECRET indicators
        SensitivityIndicator(
            name="national_security",
            pattern=r"\b(classified|top\s+secret|national\s+security|NOFORN)\b",
            level=SensitivityLevel.TOP_SECRET,
            confidence=0.95,
            description="National security classification markers",
        ),
        # RESTRICTED indicators
        SensitivityIndicator(
            name="api_keys",
            pattern=r"(?i)(api[_-]?key|secret[_-]?key|access[_-]?token)\s*[=:]\s*['\"][a-zA-Z0-9_-]{20,}['\"]",
            level=SensitivityLevel.RESTRICTED,
            confidence=0.9,
            description="API keys and secrets",
        ),
        SensitivityIndicator(
            name="private_keys",
            pattern=r"-----BEGIN (RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
            level=SensitivityLevel.RESTRICTED,
            confidence=0.95,
            description="Private cryptographic keys",
        ),
        SensitivityIndicator(
            name="database_credentials",
            pattern=r"(?i)(password|passwd|pwd)\s*[=:]\s*['\"][^'\"]+['\"]",
            level=SensitivityLevel.RESTRICTED,
            confidence=0.85,
            description="Database passwords",
        ),
        # CONFIDENTIAL indicators
        SensitivityIndicator(
            name="ssn",
            pattern=r"\b\d{3}-\d{2}-\d{4}\b",
            level=SensitivityLevel.CONFIDENTIAL,
            confidence=0.9,
            description="Social Security Numbers",
        ),
        SensitivityIndicator(
            name="credit_card",
            pattern=r"\b(?:\d{4}[- ]?){3}\d{4}\b",
            level=SensitivityLevel.CONFIDENTIAL,
            confidence=0.85,
            description="Credit card numbers",
        ),
        SensitivityIndicator(
            name="medical_record",
            pattern=r"(?i)\b(diagnosis|patient|medical\s+record|hipaa|phi)\b",
            level=SensitivityLevel.CONFIDENTIAL,
            confidence=0.75,
            description="Medical/health information",
        ),
        SensitivityIndicator(
            name="financial_data",
            pattern=r"(?i)\b(bank\s+account|routing\s+number|iban|swift|bic)\b",
            level=SensitivityLevel.CONFIDENTIAL,
            confidence=0.8,
            description="Financial account information",
        ),
        # INTERNAL indicators
        SensitivityIndicator(
            name="email_addresses",
            pattern=r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
            level=SensitivityLevel.INTERNAL,
            confidence=0.6,
            description="Email addresses",
        ),
        SensitivityIndicator(
            name="internal_only",
            pattern=r"(?i)\b(internal\s+only|confidential|proprietary|do\s+not\s+distribute)\b",
            level=SensitivityLevel.INTERNAL,
            confidence=0.7,
            description="Internal use markers",
        ),
        # PII patterns
        SensitivityIndicator(
            name="phone_number",
            pattern=r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b",
            level=SensitivityLevel.INTERNAL,
            confidence=0.65,
            description="Phone numbers",
        ),
        SensitivityIndicator(
            name="date_of_birth",
            pattern=r"(?i)(date\s+of\s+birth|dob|birthday)\s*[:\s]+\d{1,2}[/-]\d{1,2}[/-]\d{2,4}",
            level=SensitivityLevel.CONFIDENTIAL,
            confidence=0.75,
            description="Date of birth",
        ),
    ]

    def __init__(self, config: ClassificationConfig | None = None):
        self.config = config or ClassificationConfig()
        self._indicators = self.DEFAULT_INDICATORS + self.config.custom_indicators
        self._compiled_patterns: dict[str, re.Pattern[str]] = {}
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Pre-compile regex patterns."""
        for indicator in self._indicators:
            try:
                self._compiled_patterns[indicator.name] = re.compile(
                    indicator.pattern, re.IGNORECASE | re.MULTILINE
                )
            except re.error as e:
                logger.warning("Invalid pattern for %s: %s", indicator.name, e)

    async def classify(
        self,
        content: str,
        document_id: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> ClassificationResult:
        """
        Classify content sensitivity.

        Args:
            content: Text content to classify
            document_id: Optional document identifier
            metadata: Optional metadata that may influence classification

        Returns:
            Classification result with level and confidence
        """
        matches: list[IndicatorMatch] = []
        level_votes: dict[SensitivityLevel, float] = {level: 0.0 for level in SensitivityLevel}

        # Check each indicator
        for indicator in self._indicators:
            pattern = self._compiled_patterns.get(indicator.name)
            if not pattern:
                continue

            for match in pattern.finditer(content):
                indicator_match = IndicatorMatch(
                    indicator=indicator,
                    match_text=match.group()[:100],  # Truncate for safety
                    position=match.start(),
                    confidence=indicator.confidence,
                )
                matches.append(indicator_match)

                # Vote for this level
                level_votes[indicator.level] += indicator.confidence

        # Determine classification
        pii_detected = any(
            m.indicator.name in ("ssn", "credit_card", "phone_number", "date_of_birth")
            for m in matches
        )
        secrets_detected = any(
            m.indicator.name in ("api_keys", "private_keys", "database_credentials")
            for m in matches
        )

        # Find highest voted level
        if matches:
            # Take the highest sensitivity level among confident matches
            confident_matches = [m for m in matches if m.confidence >= self.config.min_confidence]
            if confident_matches:
                # Sort by sensitivity level (top_secret > restricted > confidential > internal > public)
                level_order = list(SensitivityLevel)
                max_level = max(
                    confident_matches,
                    key=lambda m: level_order.index(m.indicator.level),
                )
                level = max_level.indicator.level
                confidence = max_level.confidence
            else:
                level = self.config.default_level
                confidence = 0.5
        else:
            level = self.config.default_level
            confidence = 0.5

        # Optional LLM enhancement
        classification_method = "rule_based"
        if self.config.use_llm and (not matches or confidence < 0.7):
            llm_result = await self._classify_with_llm(content)
            if llm_result:
                level, confidence = llm_result
                classification_method = "llm_enhanced"

        return ClassificationResult(
            level=level,
            confidence=confidence,
            indicators_found=matches,
            pii_detected=pii_detected,
            secrets_detected=secrets_detected,
            document_id=document_id,
            content_length=len(content),
            classification_method=classification_method,
        )

    async def classify_document(
        self,
        document: dict[str, Any],
    ) -> ClassificationResult:
        """
        Classify a document's sensitivity.

        Args:
            document: Document with 'content' and optionally 'id', 'metadata'

        Returns:
            Classification result
        """
        content = document.get("content", "")
        doc_id = document.get("id", "")
        metadata = document.get("metadata", {})

        return await self.classify(content, doc_id, metadata)

    async def batch_classify(
        self,
        documents: list[dict[str, Any]],
    ) -> list[ClassificationResult]:
        """Classify multiple documents."""
        results = []
        for doc in documents:
            result = await self.classify_document(doc)
            results.append(result)
        return results

    async def _classify_with_llm(
        self,
        content: str,
    ) -> tuple[SensitivityLevel, float] | None:
        """Use LLM for classification enhancement."""
        try:
            # Truncate content for LLM
            truncated = content[:4000]

            _prompt = f"""Classify the sensitivity level of this content.  # noqa: F841

Levels (from most to least sensitive):
- top_secret: National security, highest classification
- restricted: Contains secrets, credentials, or highly sensitive data
- confidential: Contains PII, financial data, or protected information
- internal: Internal use only, not for public distribution
- public: Can be shared publicly

Content to classify:
{truncated}

Respond with exactly: LEVEL:confidence
Example: confidential:0.85"""

            # Would call LLM here
            # For now, return None to indicate no LLM result
            return None

        except (RuntimeError, ValueError, TypeError, OSError) as e:
            logger.warning("LLM classification failed: %s", e)
            return None

    def add_indicator(self, indicator: SensitivityIndicator) -> None:
        """Add a custom indicator."""
        self._indicators.append(indicator)
        try:
            self._compiled_patterns[indicator.name] = re.compile(
                indicator.pattern, re.IGNORECASE | re.MULTILINE
            )
        except re.error as e:
            logger.warning("Invalid pattern for %s: %s", indicator.name, e)

    def remove_indicator(self, name: str) -> None:
        """Remove an indicator by name."""
        self._indicators = [i for i in self._indicators if i.name != name]
        self._compiled_patterns.pop(name, None)

    def get_level_policy(self, level: SensitivityLevel) -> dict[str, Any]:
        """
        Get recommended policy for a sensitivity level.

        Args:
            level: Sensitivity level

        Returns:
            Recommended policy settings
        """
        policies: dict[SensitivityLevel, dict[str, Any]] = {
            SensitivityLevel.PUBLIC: {
                "encryption_required": False,
                "access_logging": False,
                "retention_days": None,  # No limit
                "sharing_allowed": True,
                "export_allowed": True,
            },
            SensitivityLevel.INTERNAL: {
                "encryption_required": False,
                "access_logging": True,
                "retention_days": 365,
                "sharing_allowed": True,
                "export_allowed": True,
            },
            SensitivityLevel.CONFIDENTIAL: {
                "encryption_required": True,
                "access_logging": True,
                "retention_days": 90,
                "sharing_allowed": False,
                "export_allowed": False,
            },
            SensitivityLevel.RESTRICTED: {
                "encryption_required": True,
                "access_logging": True,
                "retention_days": 30,
                "sharing_allowed": False,
                "export_allowed": False,
                "approval_required": True,
            },
            SensitivityLevel.TOP_SECRET: {
                "encryption_required": True,
                "access_logging": True,
                "retention_days": 7,
                "sharing_allowed": False,
                "export_allowed": False,
                "approval_required": True,
                "mfa_required": True,
            },
        }
        return policies.get(level, policies[SensitivityLevel.INTERNAL])


# Global instance
_classifier: SensitivityClassifier | None = None


def get_classifier(config: ClassificationConfig | None = None) -> SensitivityClassifier:
    """Get or create the global sensitivity classifier."""
    global _classifier
    if _classifier is None:
        _classifier = SensitivityClassifier(config)
    return _classifier


__all__ = [
    "SensitivityClassifier",
    "SensitivityLevel",
    "ClassificationResult",
    "ClassificationConfig",
    "SensitivityIndicator",
    "IndicatorMatch",
    "get_classifier",
]
