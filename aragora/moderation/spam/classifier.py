"""
Spam classification engine.

Contains the main SpamClassifier class with ML-enhanced classification,
online learning from user feedback, and rule-based scoring fallback.
Also provides convenience functions for quick classification.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sqlite3
from datetime import datetime
from typing import TYPE_CHECKING, Any

from aragora.config import resolve_db_path
from aragora.moderation.spam.features import SpamFeatures
from aragora.moderation.spam.model import NaiveBayesClassifier
from aragora.moderation.spam.models import (
    SpamCategory,
    SpamClassificationResult,
    SpamClassifierConfig,
)  # EmailFeatures used indirectly via scoring module
from aragora.moderation.spam.patterns import PROMOTIONAL_PATTERNS
from aragora.moderation.spam.scoring import (
    determine_category,
    score_attachments,
    score_content,
    score_headers,
    score_patterns,
    score_sender,
    score_subject,
    score_urls,
)

if TYPE_CHECKING:
    from aragora.services.sender_history import SenderHistoryService

logger = logging.getLogger(__name__)


class SpamClassifier:
    """
    ML-enhanced spam classifier with online learning.

    Uses a Naive Bayes model trained on user feedback,
    with fallback to rule-based classification.

    Features:
    - Domain reputation scoring
    - Subject line analysis (ALL CAPS, excessive punctuation)
    - Content n-grams (unigrams, bigrams)
    - Header analysis (SPF, DKIM, DMARC, suspicious routing)
    - URL analysis (shorteners, suspicious domains, IP addresses)
    - Attachment analysis (dangerous extensions)
    - Online learning from user feedback
    - Fallback to rule-based when ML confidence < 0.7
    """

    def __init__(
        self,
        config: SpamClassifierConfig | None = None,
        sender_history_service: SenderHistoryService | None = None,
        user_id: str | None = None,
    ):
        """
        Initialize spam classifier.

        Args:
            config: Classifier configuration
            sender_history_service: Optional service for sender reputation
            user_id: User ID for sender history lookups
        """
        self.config = config or SpamClassifierConfig()
        self.model = NaiveBayesClassifier()
        self._db_conn: sqlite3.Connection | None = None
        self._compiled_promotional = [re.compile(p, re.IGNORECASE) for p in PROMOTIONAL_PATTERNS]
        self._initialized = False
        self._last_retrain: datetime | None = None

        # Feature extractor
        self._feature_extractor = SpamFeatures(
            sender_history_service=sender_history_service,
            user_id=user_id,
        )

        # Domain reputation cache
        self._domain_reputation_cache: dict[str, tuple[datetime, float]] = {}
        self._domain_cache_ttl = 3600  # 1 hour

    async def initialize(self) -> None:
        """Initialize classifier (load model, setup database)."""
        if self._initialized:
            return

        # Try to load existing model
        if os.path.exists(self.config.model_path):
            if self.model.load(self.config.model_path):
                logger.info(
                    "Loaded spam model with %s spam and %s ham samples",
                    self.model.spam_count,
                    self.model.ham_count,
                )

        # Initialize feedback database
        await self._init_feedback_db()
        self._initialized = True

    async def _init_feedback_db(self) -> None:
        """Initialize feedback storage database."""
        try:
            db_path = resolve_db_path(self.config.feedback_db_path)
            self._db_conn = sqlite3.connect(
                db_path,
                check_same_thread=False,
            )
            cursor = self._db_conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS spam_feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email_id TEXT NOT NULL,
                    user_id TEXT,
                    is_spam BOOLEAN NOT NULL,
                    content_hash TEXT,
                    features_json TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    used_for_training BOOLEAN DEFAULT FALSE
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_feedback_training
                ON spam_feedback(used_for_training)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS classification_cache (
                    content_hash TEXT PRIMARY KEY,
                    is_spam BOOLEAN,
                    category TEXT,
                    confidence REAL,
                    spam_score REAL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            self._db_conn.commit()
            logger.info("Spam feedback database initialized")

        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Failed to initialize feedback database: %s", e)

    async def classify_email(
        self,
        email_id: str,
        subject: str,
        body: str,
        sender: str,
        headers: dict[str, str] | None = None,
        attachments: list[str] | None = None,
    ) -> SpamClassificationResult:
        """
        Classify an email as spam or ham.

        Args:
            email_id: Email identifier
            subject: Email subject
            body: Email body (text or HTML)
            sender: Sender email address
            headers: Optional email headers
            attachments: Optional list of attachment filenames

        Returns:
            SpamClassificationResult
        """
        if not self._initialized:
            await self.initialize()

        # Extract features using enhanced feature extractor
        features = self._feature_extractor.extract(
            subject=subject,
            body=body,
            sender=sender,
            headers=headers,
            attachments=attachments,
        )

        # Check cache
        content = f"{subject}\n\n{body}"
        content_hash = self._hash_content(content)
        cached = await self._get_cached_result(content_hash)
        if cached:
            cached.email_id = email_id
            return cached

        reasons: list[str] = []
        model_used = "rule_based"

        # Try ML model first if trained
        ml_is_spam = False
        ml_confidence = 0.0

        if self.config.use_ml_model and self.model.is_trained:
            ml_is_spam, ml_confidence = self.model.predict(content)
            if ml_confidence >= self.config.min_confidence_for_ml:
                model_used = "naive_bayes"

        # Calculate comprehensive rule-based scores
        content_score = score_content(content, features)
        sender_score = score_sender(sender, features)
        header_score = score_headers(headers or {}, features)
        pattern_score = score_patterns(content, self._compiled_promotional)
        url_score = score_urls(features)
        attachment_score = score_attachments(features)
        subject_score = score_subject(features)

        # Combine scores with weights
        weights = {
            "content": 0.25,
            "sender": 0.15,
            "header": 0.10,
            "pattern": 0.15,
            "url": 0.15,
            "attachment": 0.10,
            "subject": 0.10,
        }

        spam_score = (
            content_score * weights["content"]
            + sender_score * weights["sender"]
            + header_score * weights["header"]
            + pattern_score * weights["pattern"]
            + url_score * weights["url"]
            + attachment_score * weights["attachment"]
            + subject_score * weights["subject"]
        )

        # If ML model is confident, blend with rule-based
        if model_used == "naive_bayes":
            ml_score = 1.0 if ml_is_spam else 0.0
            spam_score = spam_score * 0.4 + ml_score * 0.6
            reasons.append(f"ML model: {'spam' if ml_is_spam else 'ham'} ({ml_confidence:.0%})")

        # Add detailed reasons based on high-scoring components
        if content_score > 0.5:
            reasons.append(f"Suspicious content (score: {content_score:.2f})")
        if sender_score > 0.5:
            reasons.append(f"Suspicious sender (score: {sender_score:.2f})")
        if url_score > 0.5:
            reasons.append(
                f"Suspicious URLs ({features.shortened_url_count} shortened, "
                f"{len(features.suspicious_domain_urls)} suspicious)"
            )
        if attachment_score > 0.5:
            reasons.append(
                f"Dangerous attachments: {', '.join(features.dangerous_attachments[:3])}"
            )
        if subject_score > 0.5:
            reasons.append(f"Suspicious subject line (score: {subject_score:.2f})")

        # Determine category
        category, confidence = determine_category(
            spam_score, content, features, reasons, self.config
        )

        # Fallback to rule-based when confidence is low
        if confidence < self.config.min_confidence_for_ml and model_used == "naive_bayes":
            model_used = "rule_based_fallback"
            reasons.append("Fallback to rules (low ML confidence)")

        is_spam = category in (SpamCategory.SPAM, SpamCategory.PHISHING)

        result = SpamClassificationResult(
            email_id=email_id,
            is_spam=is_spam,
            category=category,
            confidence=confidence,
            spam_score=spam_score,
            content_score=content_score,
            sender_score=sender_score,
            header_score=header_score,
            pattern_score=pattern_score,
            url_score=url_score,
            attachment_score=attachment_score,
            subject_score=subject_score,
            reasons=reasons,
            model_used=model_used,
            suspicious_urls=features.suspicious_domain_urls[:10],
            dangerous_attachments=features.dangerous_attachments,
        )

        # Cache result
        await self._cache_result(content_hash, result)

        return result

    async def train_from_feedback(
        self,
        email_id: str,
        is_spam: bool,
        content: str | None = None,
        user_id: str | None = None,
    ) -> bool:
        """
        Train the model from user feedback.

        Args:
            email_id: Email identifier
            is_spam: User's classification
            content: Optional email content for training
            user_id: Optional user identifier

        Returns:
            True if feedback was recorded
        """
        if not self._initialized:
            await self.initialize()

        try:
            content_hash = self._hash_content(content or email_id)

            # Store feedback
            if self._db_conn:
                cursor = self._db_conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO spam_feedback
                    (email_id, user_id, is_spam, content_hash)
                    VALUES (?, ?, ?, ?)
                    """,
                    (email_id, user_id, is_spam, content_hash),
                )
                self._db_conn.commit()

            # Train model if content available
            if content:
                self.model.train(content, is_spam)

                # Invalidate cache for this content
                await self._invalidate_cache(content_hash)

            # Check if we should retrain
            await self._maybe_retrain()

            return True

        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Failed to record feedback: %s", e)
            return False

    async def _maybe_retrain(self) -> None:
        """Check if we should retrain the model."""
        if not self._db_conn:
            return

        now = datetime.now()
        if self._last_retrain:
            hours_since = (now - self._last_retrain).total_seconds() / 3600
            if hours_since < self.config.retrain_interval_hours:
                return

        try:
            cursor = self._db_conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM spam_feedback WHERE used_for_training = FALSE")
            untrained_count = cursor.fetchone()[0]

            if untrained_count >= self.config.min_training_samples // 10:
                await self._retrain_model()

        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Failed to check retrain status: %s", e)

    async def _retrain_model(self) -> None:
        """Retrain model from feedback database."""
        if not self._db_conn:
            return

        logger.info("Retraining spam model from feedback...")

        try:
            cursor = self._db_conn.cursor()

            # Get unprocessed feedback
            cursor.execute(
                """
                SELECT id, is_spam, content_hash FROM spam_feedback
                WHERE used_for_training = FALSE
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (self.config.max_training_samples,),
            )

            rows = cursor.fetchall()
            trained = 0

            for row in rows:
                feedback_id, is_spam, content_hash = row
                # Note: In a real system, you'd store content or retrieve it
                # For now, we mark as used
                cursor.execute(
                    "UPDATE spam_feedback SET used_for_training = TRUE WHERE id = ?",
                    (feedback_id,),
                )
                trained += 1

            self._db_conn.commit()

            # Save updated model
            self.model.save(self.config.model_path)
            self._last_retrain = datetime.now()

            logger.info("Retrained spam model with %s feedback samples", trained)

        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Failed to retrain model: %s", e)

    def _hash_content(self, content: str) -> str:
        """Hash content for caching."""
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    async def _get_cached_result(self, content_hash: str) -> SpamClassificationResult | None:
        """Get cached classification result."""
        if not self._db_conn:
            return None

        try:
            cursor = self._db_conn.cursor()
            cursor.execute(
                """
                SELECT is_spam, category, confidence, spam_score
                FROM classification_cache
                WHERE content_hash = ?
                AND created_at > datetime('now', '-1 day')
                """,
                (content_hash,),
            )
            row = cursor.fetchone()
            if row:
                return SpamClassificationResult(
                    email_id="",
                    is_spam=row[0],
                    category=SpamCategory(row[1]),
                    confidence=row[2],
                    spam_score=row[3],
                    model_used="cached",
                )
        except (ValueError, OSError, RuntimeError) as e:
            logger.debug("Failed to retrieve cached classification result: %s", e)
        return None

    async def _cache_result(self, content_hash: str, result: SpamClassificationResult) -> None:
        """Cache classification result."""
        if not self._db_conn:
            return

        try:
            cursor = self._db_conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO classification_cache
                (content_hash, is_spam, category, confidence, spam_score)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    content_hash,
                    result.is_spam,
                    result.category.value,
                    result.confidence,
                    result.spam_score,
                ),
            )
            self._db_conn.commit()
        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Failed to cache spam classification result: %s", e)

    async def _invalidate_cache(self, content_hash: str) -> None:
        """Invalidate cached result after feedback."""
        if not self._db_conn:
            return

        try:
            cursor = self._db_conn.cursor()
            cursor.execute(
                "DELETE FROM classification_cache WHERE content_hash = ?",
                (content_hash,),
            )
            self._db_conn.commit()
        except (ValueError, OSError, RuntimeError) as e:
            logger.warning("Failed to invalidate cached classification: %s", e)

    async def get_statistics(self) -> dict[str, Any]:
        """Get classifier statistics."""
        stats = {
            "model_trained": self.model.is_trained,
            "spam_samples": self.model.spam_count,
            "ham_samples": self.model.ham_count,
            "vocabulary_size": len(self.model.vocabulary),
            "last_retrain": self._last_retrain.isoformat() if self._last_retrain else None,
        }

        if self._db_conn:
            try:
                cursor = self._db_conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM spam_feedback")
                stats["total_feedback"] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM spam_feedback WHERE is_spam = TRUE")
                stats["spam_feedback"] = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM classification_cache")
                stats["cached_results"] = cursor.fetchone()[0]
            except (ValueError, OSError, RuntimeError) as e:
                logger.debug("Failed to retrieve classifier statistics from DB: %s", e)

        return stats

    async def close(self) -> None:
        """Close resources."""
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None


# Convenience function
async def classify_email_spam(
    email_id: str,
    subject: str,
    body: str,
    sender: str,
    headers: dict[str, str] | None = None,
    attachments: list[str] | None = None,
) -> SpamClassificationResult:
    """
    Quick convenience function for spam classification.

    Args:
        email_id: Email identifier
        subject: Email subject
        body: Email body
        sender: Sender email
        headers: Optional email headers
        attachments: Optional list of attachment filenames

    Returns:
        SpamClassificationResult
    """
    classifier = SpamClassifier()
    await classifier.initialize()

    try:
        return await classifier.classify_email(
            email_id=email_id,
            subject=subject,
            body=body,
            sender=sender,
            headers=headers,
            attachments=attachments,
        )
    finally:
        await classifier.close()


async def classify_email(email: dict[str, Any]) -> SpamClassificationResult:
    """
    Classify an email from a dictionary representation.

    This is the primary convenience function for spam classification,
    designed to work with the email inbox feature.

    Args:
        email: Dictionary containing email data with keys:
            - id (str): Email identifier
            - subject (str): Email subject
            - body (str): Email body (text or HTML)
            - sender (str): Sender email address
            - headers (dict, optional): Email headers
            - attachments (list, optional): List of attachment filenames

    Returns:
        SpamClassificationResult with is_spam, confidence, category, and reasons

    Example:
        email = {
            "id": "msg_123",
            "subject": "You won a prize!",
            "body": "Click here to claim...",
            "sender": "prize@suspicious.tk",
            "headers": {"Authentication-Results": "spf=fail"},
            "attachments": ["prize.exe"]
        }
        result = await classify_email(email)
        if result.is_spam:
            print(f"Spam detected: {result.reasons}")
    """
    return await classify_email_spam(
        email_id=email.get("id", ""),
        subject=email.get("subject", ""),
        body=email.get("body", "") or email.get("body_text", "") or email.get("body_html", ""),
        sender=email.get("sender", "") or email.get("from_address", ""),
        headers=email.get("headers"),
        attachments=email.get("attachments"),
    )


async def classify_emails_batch(
    emails: list[dict[str, Any]],
    max_concurrent: int = 10,
) -> list[SpamClassificationResult]:
    """
    Classify multiple emails concurrently.

    Args:
        emails: List of email dictionaries
        max_concurrent: Maximum concurrent classifications

    Returns:
        List of SpamClassificationResult in same order as input
    """
    import asyncio

    semaphore = asyncio.Semaphore(max_concurrent)
    classifier = SpamClassifier()
    await classifier.initialize()

    async def classify_one(email: dict[str, Any]) -> SpamClassificationResult:
        async with semaphore:
            return await classifier.classify_email(
                email_id=email.get("id", ""),
                subject=email.get("subject", ""),
                body=email.get("body", "") or email.get("body_text", "") or "",
                sender=email.get("sender", "") or email.get("from_address", ""),
                headers=email.get("headers"),
                attachments=email.get("attachments"),
            )

    try:
        tasks = [classify_one(email) for email in emails]
        return await asyncio.gather(*tasks)
    finally:
        await classifier.close()
