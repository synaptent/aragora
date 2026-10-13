"""
Spam Classifier Integration for Content Moderation.

Integrates the ML spam classifier with the content moderation pipeline
to filter debate inputs and flag suspicious content before processing.

Features:
- Configurable block/review thresholds
- Integration with existing SpamClassifier
- Async-first design for non-blocking checks
- Caching for repeated content checks
- Environment variable configuration
- Metrics tracking for moderation actions

Usage:
    from aragora.moderation import get_spam_moderation, check_debate_content

    # Quick check for debate content
    result = await check_debate_content("My debate proposal", context="Additional context")
    if result.should_block:
        raise ContentModerationError("Content blocked as spam")

    # Or use the integration class directly
    moderation = get_spam_moderation()
    result = await moderation.check_debate_input(proposal, context)
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from threading import Lock
from typing import Any, TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from aragora.moderation.spam import SpamClassificationResult, SpamClassifier

logger = logging.getLogger(__name__)


class SpamVerdict(str, Enum):
    """Verdict from spam content check."""

    CLEAN = "clean"
    SUSPICIOUS = "suspicious"
    SPAM = "spam"


class ContentModerationError(Exception):
    """Raised when content is blocked by moderation."""

    def __init__(
        self,
        message: str,
        verdict: SpamVerdict = SpamVerdict.SPAM,
        confidence: float = 0.0,
        reasons: list[str] | None = None,
    ):
        super().__init__(message)
        self.verdict = verdict
        self.confidence = confidence
        self.reasons = reasons or []


@dataclass
class SpamCheckResult:
    """Result of a spam content check."""

    verdict: SpamVerdict
    confidence: float  # 0.0 to 1.0
    reasons: list[str] = field(default_factory=list)
    should_block: bool = False
    should_flag_for_review: bool = False

    # Additional metadata
    spam_score: float = 0.0
    check_duration_ms: float = 0.0
    content_hash: str = ""
    checked_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Breakdown scores (optional, for debugging)
    content_score: float = 0.0
    sender_score: float = 0.0
    pattern_score: float = 0.0
    url_score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "verdict": self.verdict.value,
            "confidence": self.confidence,
            "reasons": self.reasons,
            "should_block": self.should_block,
            "should_flag_for_review": self.should_flag_for_review,
            "spam_score": self.spam_score,
            "check_duration_ms": self.check_duration_ms,
            "content_hash": self.content_hash,
            "checked_at": self.checked_at.isoformat(),
            "scores": {
                "content": self.content_score,
                "sender": self.sender_score,
                "pattern": self.pattern_score,
                "url": self.url_score,
            },
        }


@dataclass
class ModerationQueueItem:
    """Queued moderation item for manual review."""

    id: str
    content: str
    content_hash: str
    result: SpamCheckResult
    queued_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "content": self.content,
            "content_hash": self.content_hash,
            "result": self.result.to_dict(),
            "queued_at": self.queued_at.isoformat(),
            "context": self.context,
        }


@dataclass
class SpamModerationConfig:
    """Configuration for spam moderation."""

    # Enable/disable spam checking
    enabled: bool = True

    # Thresholds
    block_threshold: float = 0.9  # Score above this = block
    review_threshold: float = 0.7  # Score above this = flag for review

    # Caching
    cache_enabled: bool = True
    cache_ttl_seconds: int = 300  # 5 minutes
    cache_max_size: int = 1000

    # Behavior
    fail_open: bool = True  # Allow content if classifier fails
    log_all_checks: bool = False  # Log every check (verbose)

    @classmethod
    def from_env(cls) -> SpamModerationConfig:
        """Load configuration from environment variables."""
        return cls(
            enabled=os.getenv("ARAGORA_SPAM_CHECK_ENABLED", "true").lower() == "true",
            block_threshold=float(os.getenv("ARAGORA_SPAM_BLOCK_THRESHOLD", "0.9")),
            review_threshold=float(os.getenv("ARAGORA_SPAM_REVIEW_THRESHOLD", "0.7")),
            cache_enabled=os.getenv("ARAGORA_SPAM_CACHE_ENABLED", "true").lower() == "true",
            cache_ttl_seconds=int(os.getenv("ARAGORA_SPAM_CACHE_TTL", "300")),
            cache_max_size=int(os.getenv("ARAGORA_SPAM_CACHE_SIZE", "1000")),
            fail_open=os.getenv("ARAGORA_SPAM_FAIL_OPEN", "true").lower() == "true",
            log_all_checks=os.getenv("ARAGORA_SPAM_LOG_ALL", "false").lower() == "true",
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize config to dict for API responses."""
        return {
            "enabled": self.enabled,
            "block_threshold": self.block_threshold,
            "review_threshold": self.review_threshold,
            "cache_enabled": self.cache_enabled,
            "cache_ttl_seconds": self.cache_ttl_seconds,
            "cache_max_size": self.cache_max_size,
            "fail_open": self.fail_open,
            "log_all_checks": self.log_all_checks,
        }

    def apply_updates(self, updates: dict[str, Any]) -> None:
        """Apply config updates with basic validation."""
        if "enabled" in updates:
            self.enabled = bool(updates["enabled"])
        if "block_threshold" in updates:
            self.block_threshold = float(updates["block_threshold"])
        if "review_threshold" in updates:
            self.review_threshold = float(updates["review_threshold"])
        if "cache_enabled" in updates:
            self.cache_enabled = bool(updates["cache_enabled"])
        if "cache_ttl_seconds" in updates:
            self.cache_ttl_seconds = max(0, int(updates["cache_ttl_seconds"]))
        if "cache_max_size" in updates:
            self.cache_max_size = max(0, int(updates["cache_max_size"]))
        if "fail_open" in updates:
            self.fail_open = bool(updates["fail_open"])
        if "log_all_checks" in updates:
            self.log_all_checks = bool(updates["log_all_checks"])

        # Ensure thresholds remain sane
        self.block_threshold = min(max(self.block_threshold, 0.0), 1.0)
        self.review_threshold = min(max(self.review_threshold, 0.0), 1.0)
        if self.review_threshold > self.block_threshold:
            self.review_threshold = self.block_threshold


# =============================================================================
# Moderation Review Queue (in-memory)
# =============================================================================

_REVIEW_QUEUE: OrderedDict[str, ModerationQueueItem] = OrderedDict()
_REVIEW_QUEUE_LOCK = Lock()
_REVIEW_QUEUE_MAX = int(os.getenv("ARAGORA_MODERATION_QUEUE_MAX", "1000"))


def queue_for_review(
    content: str,
    result: SpamCheckResult,
    context: dict[str, Any] | None = None,
) -> ModerationQueueItem:
    """Queue content for manual review."""
    ctx = context or {}
    content_hash = result.content_hash or hashlib.sha256(content.encode()).hexdigest()
    item = ModerationQueueItem(
        id=f"mod_{uuid4().hex}",
        content=content,
        content_hash=content_hash,
        result=result,
        context=ctx,
    )

    with _REVIEW_QUEUE_LOCK:
        if _REVIEW_QUEUE_MAX > 0 and len(_REVIEW_QUEUE) >= _REVIEW_QUEUE_MAX:
            _REVIEW_QUEUE.popitem(last=False)
        _REVIEW_QUEUE[item.id] = item

    return item


def list_review_queue(limit: int = 100, offset: int = 0) -> list[ModerationQueueItem]:
    """List queued moderation items, newest first."""
    with _REVIEW_QUEUE_LOCK:
        items = list(_REVIEW_QUEUE.values())
    items = list(reversed(items))
    if offset < 0:
        offset = 0
    if limit <= 0:
        return items[offset:]
    return items[offset : offset + limit]


def pop_review_item(item_id: str) -> ModerationQueueItem | None:
    """Remove and return a queued moderation item."""
    with _REVIEW_QUEUE_LOCK:
        return _REVIEW_QUEUE.pop(item_id, None)


def review_queue_size() -> int:
    """Return current queue size."""
    with _REVIEW_QUEUE_LOCK:
        return len(_REVIEW_QUEUE)


class SpamModerationIntegration:
    """
    Integrates spam classifier with content moderation pipeline.

    Provides async methods for checking content against the ML spam
    classifier, with configurable thresholds for blocking and flagging.

    Example:
        moderation = SpamModerationIntegration()
        await moderation.initialize()

        result = await moderation.check_content("Some content to check")
        if result.should_block:
            return error_response("Content blocked as spam", 400)
        if result.should_flag_for_review:
            await queue_for_review(content, result)
    """

    def __init__(
        self,
        classifier: SpamClassifier | None = None,
        config: SpamModerationConfig | None = None,
    ):
        """
        Initialize spam moderation integration.

        Args:
            classifier: Optional pre-configured SpamClassifier instance.
                        If None, one will be created on initialize().
            config: Configuration for moderation behavior.
                    If None, loads from environment variables.
        """
        self._classifier = classifier
        self._config = config or SpamModerationConfig.from_env()
        self._initialized = False
        self._cache: dict[str, tuple[SpamCheckResult, float]] = {}
        self._stats = {
            "checks": 0,
            "blocked": 0,
            "flagged": 0,
            "passed": 0,
            "cache_hits": 0,
            "errors": 0,
        }

    @property
    def config(self) -> SpamModerationConfig:
        """Get current configuration."""
        return self._config

    @property
    def enabled(self) -> bool:
        """Check if spam moderation is enabled."""
        return self._config.enabled

    @property
    def statistics(self) -> dict[str, int]:
        """Get moderation statistics."""
        return dict(self._stats)

    def update_config(self, updates: dict[str, Any]) -> SpamModerationConfig:
        """Update moderation config with validation."""
        prior_max = self._config.cache_max_size
        self._config.apply_updates(updates)
        if not self._config.cache_enabled or self._config.cache_max_size < prior_max:
            self._cache.clear()
        return self._config

    async def initialize(self) -> None:
        """
        Initialize the spam classifier.

        Creates a new SpamClassifier if one wasn't provided,
        and initializes it for use.
        """
        if self._initialized:
            return

        if not self._config.enabled:
            logger.info("Spam moderation is disabled")
            self._initialized = True
            return

        if self._classifier is None:
            try:
                from aragora.moderation.spam import SpamClassifier

                self._classifier = SpamClassifier()
                await self._classifier.initialize()
                logger.info("Spam classifier initialized for content moderation")
            except ImportError:
                logger.warning("SpamClassifier not available - spam moderation will be disabled")
                self._config.enabled = False
            except (RuntimeError, ValueError, TypeError, OSError, ConnectionError) as e:
                logger.error("Failed to initialize spam classifier: %s", e)
                if not self._config.fail_open:
                    raise
                self._config.enabled = False

        self._initialized = True

    async def check_content(
        self,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> SpamCheckResult:
        """
        Check content for spam.

        Args:
            content: The text content to check
            context: Optional context dict with metadata (sender, headers, etc.)

        Returns:
            SpamCheckResult with verdict and recommendations
        """
        start_time = time.time()
        context = context or {}

        # Return clean if disabled
        if not self._config.enabled or not self._classifier:
            return SpamCheckResult(
                verdict=SpamVerdict.CLEAN,
                confidence=0.0,
                reasons=["Spam check disabled"],
                should_block=False,
                should_flag_for_review=False,
            )

        # Check cache first
        content_hash = self._hash_content(content)
        if self._config.cache_enabled:
            cached = self._get_cached(content_hash)
            if cached:
                self._stats["cache_hits"] += 1
                if self._config.log_all_checks:
                    logger.debug("Spam check cache hit for hash %s", content_hash[:8])
                return cached

        self._stats["checks"] += 1

        try:
            # Initialize if needed
            if not self._initialized:
                await self.initialize()

            # Call the classifier
            classification = await self._classifier.classify_email(
                email_id=f"content_{content_hash[:16]}",
                subject="",  # No subject for general content
                body=content,
                sender=context.get("sender", ""),
                headers=context.get("headers"),
                attachments=context.get("attachments"),
            )

            # Convert to SpamCheckResult
            result = self._classification_to_result(classification, content_hash, start_time)

            # Update stats
            if result.should_block:
                self._stats["blocked"] += 1
            elif result.should_flag_for_review:
                self._stats["flagged"] += 1
            else:
                self._stats["passed"] += 1

            # Cache the result
            if self._config.cache_enabled:
                self._cache_result(content_hash, result)

            # Log if configured
            if self._config.log_all_checks or result.verdict != SpamVerdict.CLEAN:
                log_level = logging.WARNING if result.should_block else logging.DEBUG
                logger.log(
                    log_level,
                    f"Spam check: verdict={result.verdict.value}, "
                    f"confidence={result.confidence:.2f}, "
                    f"block={result.should_block}, "
                    f"duration={result.check_duration_ms:.1f}ms",
                )

            if result.should_flag_for_review:
                queue_for_review(content, result, context)

            return result

        except (RuntimeError, ValueError, TypeError, KeyError, OSError, ConnectionError) as e:
            self._stats["errors"] += 1
            logger.error("Spam check failed: %s", e)

            if self._config.fail_open:
                # Allow content through on error
                fail_result = SpamCheckResult(
                    verdict=SpamVerdict.CLEAN,
                    confidence=0.0,
                    reasons=["Check failed (fail-open): internal error"],
                    should_block=False,
                    should_flag_for_review=True,  # Flag for manual review
                    check_duration_ms=(time.time() - start_time) * 1000,
                    content_hash=content_hash,
                )
                queue_for_review(content, fail_result, context)
                return fail_result
            else:
                raise ContentModerationError(
                    "Spam check failed",
                    verdict=SpamVerdict.SUSPICIOUS,
                )

    async def check_debate_input(
        self,
        proposal: str,
        context: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SpamCheckResult:
        """
        Check debate proposal for spam before processing.

        This is the primary method for debate input validation.

        Args:
            proposal: The debate task/question/proposal text
            context: Optional additional context for the debate
            metadata: Optional metadata (user_id, org_id, etc.)

        Returns:
            SpamCheckResult with verdict and recommendations

        Example:
            result = await moderation.check_debate_input(
                proposal="Should we implement caching?",
                context="For the user authentication system",
                metadata={"user_id": "user_123"}
            )
            if result.should_block:
                raise ContentModerationError("Debate blocked as spam")
        """
        # Combine proposal and context for checking
        combined = proposal
        if context:
            combined = f"{proposal}\n\n{context}"

        # Build context dict for classifier
        check_context = metadata or {}

        return await self.check_content(combined, check_context)

    async def check_message(
        self,
        message: str,
        sender: str | None = None,
        debate_id: str | None = None,
    ) -> SpamCheckResult:
        """
        Check an individual debate message for spam.

        Can be used for real-time message filtering during debates.

        Args:
            message: The message text
            sender: Optional sender identifier
            debate_id: Optional debate ID for context

        Returns:
            SpamCheckResult
        """
        context = {}
        if sender:
            context["sender"] = sender
        if debate_id:
            context["debate_id"] = debate_id

        return await self.check_content(message, context)

    def _classification_to_result(
        self,
        classification: SpamClassificationResult,
        content_hash: str,
        start_time: float,
    ) -> SpamCheckResult:
        """Convert SpamClassificationResult to SpamCheckResult."""
        confidence = classification.confidence
        spam_score = classification.spam_score

        # Determine verdict based on thresholds
        if spam_score >= self._config.block_threshold:
            verdict = SpamVerdict.SPAM
        elif spam_score >= self._config.review_threshold:
            verdict = SpamVerdict.SUSPICIOUS
        else:
            verdict = SpamVerdict.CLEAN

        return SpamCheckResult(
            verdict=verdict,
            confidence=confidence,
            reasons=classification.reasons[:5],  # Top 5 reasons
            should_block=spam_score >= self._config.block_threshold,
            should_flag_for_review=spam_score >= self._config.review_threshold,
            spam_score=spam_score,
            check_duration_ms=(time.time() - start_time) * 1000,
            content_hash=content_hash,
            content_score=classification.content_score,
            sender_score=classification.sender_score,
            pattern_score=classification.pattern_score,
            url_score=classification.url_score,
        )

    def _hash_content(self, content: str) -> str:
        """Generate hash for content caching."""
        return hashlib.sha256(content.encode()).hexdigest()

    def _get_cached(self, content_hash: str) -> SpamCheckResult | None:
        """Get cached result if valid."""
        if content_hash not in self._cache:
            return None

        result, timestamp = self._cache[content_hash]
        if time.time() - timestamp > self._config.cache_ttl_seconds:
            del self._cache[content_hash]
            return None

        return result

    def _cache_result(self, content_hash: str, result: SpamCheckResult) -> None:
        """Cache a result with expiry."""
        # Evict oldest entries if cache is full
        if len(self._cache) >= self._config.cache_max_size:
            # Remove oldest 10% (at least 1 entry)
            evict_count = max(1, self._config.cache_max_size // 10)
            entries = sorted(self._cache.items(), key=lambda x: x[1][1])
            for key, _ in entries[:evict_count]:
                del self._cache[key]

        self._cache[content_hash] = (result, time.time())

    def clear_cache(self) -> int:
        """Clear the results cache. Returns number of entries cleared."""
        count = len(self._cache)
        self._cache.clear()
        return count

    def reset_statistics(self) -> dict[str, int]:
        """Reset and return current statistics."""
        old_stats = dict(self._stats)
        self._stats = {
            "checks": 0,
            "blocked": 0,
            "flagged": 0,
            "passed": 0,
            "cache_hits": 0,
            "errors": 0,
        }
        return old_stats

    async def close(self) -> None:
        """Close resources."""
        if self._classifier:
            try:
                await self._classifier.close()
            except (RuntimeError, OSError) as e:
                logger.warning("Error closing classifier: %s", e)
        self._initialized = False


# Global instance management
_global_moderation: SpamModerationIntegration | None = None


def get_spam_moderation() -> SpamModerationIntegration:
    """
    Get the global spam moderation instance.

    Creates a new instance if one doesn't exist.
    Thread-safe for most use cases.

    Returns:
        SpamModerationIntegration instance
    """
    global _global_moderation
    if _global_moderation is None:
        _global_moderation = SpamModerationIntegration()
    return _global_moderation


def set_spam_moderation(moderation: SpamModerationIntegration) -> None:
    """
    Set the global spam moderation instance.

    Useful for testing or custom configuration.
    """
    global _global_moderation
    _global_moderation = moderation


async def close_spam_moderation() -> None:
    """Close and clear the global spam moderation singleton."""
    global _global_moderation
    moderation = _global_moderation
    _global_moderation = None
    if moderation is not None:
        await moderation.close()


async def check_debate_content(
    proposal: str,
    context: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> SpamCheckResult:
    """
    Convenience function to check debate content for spam.

    This is the primary integration point for debate input validation.

    Args:
        proposal: The debate task/question text
        context: Optional additional context
        metadata: Optional metadata dict

    Returns:
        SpamCheckResult

    Raises:
        ContentModerationError: If configured to fail-closed and check fails

    Example:
        result = await check_debate_content("Design a caching layer")
        if result.should_block:
            return error_response("Content blocked", 400)
    """
    moderation = get_spam_moderation()
    if not moderation._initialized:
        await moderation.initialize()
    return await moderation.check_debate_input(proposal, context, metadata)


__all__ = [
    "SpamVerdict",
    "SpamCheckResult",
    "ModerationQueueItem",
    "SpamModerationConfig",
    "SpamModerationIntegration",
    "ContentModerationError",
    "get_spam_moderation",
    "close_spam_moderation",
    "set_spam_moderation",
    "check_debate_content",
    "queue_for_review",
    "list_review_queue",
    "pop_review_item",
    "review_queue_size",
]
