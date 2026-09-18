"""
Autonomous Learning Handler for Aragora.

Provides REST API endpoints for autonomous learning operations:
- Training session management
- Model performance metrics
- Learning rate adjustments
- Knowledge extraction
- Pattern recognition results
- Feedback loop integration
- Cross-debate learning analytics

Endpoints:
    GET  /api/v2/learning/sessions                        - List training sessions
    POST /api/v2/learning/sessions                        - Start new training session
    GET  /api/v2/learning/sessions/:session_id            - Get session details
    POST /api/v2/learning/sessions/:session_id/stop       - Stop training session
    GET  /api/v2/learning/metrics                         - Get learning metrics
    GET  /api/v2/learning/metrics/:metric_type            - Get specific metric
    POST /api/v2/learning/feedback                        - Submit learning feedback
    GET  /api/v2/learning/patterns                        - List detected patterns
    POST /api/v2/learning/patterns/:pattern_id/validate   - Validate a pattern
    GET  /api/v2/learning/knowledge                       - Get extracted knowledge
    POST /api/v2/learning/knowledge/extract               - Trigger knowledge extraction
    GET  /api/v2/learning/recommendations                 - Get learning recommendations
    GET  /api/v2/learning/performance                     - Get model performance stats
    POST /api/v2/learning/calibrate                       - Trigger calibration

Stability: STABLE
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

import functools

from aragora.resilience import (
    CircuitBreaker,
    CircuitOpenError,
    get_circuit_breaker,
)
from aragora.server.handlers.base import (
    BaseHandler,
    HandlerResult,
    error_response,
    json_response,
    handle_errors,
)
from aragora.server.handlers.utils.decorators import require_permission
from aragora.server.handlers.utils.rate_limit import rate_limit
from aragora.server.validation.query_params import safe_query_int

logger = logging.getLogger(__name__)


# =============================================================================
# Constants and Configuration
# =============================================================================

# Circuit breaker configuration for learning operations
LEARNING_CB_NAME = "autonomous_learning"
LEARNING_CB_FAILURE_THRESHOLD = 5
LEARNING_CB_COOLDOWN_SECONDS = 30

# Maximum sessions per tenant
MAX_ACTIVE_SESSIONS = 10

# Pattern confidence threshold
MIN_PATTERN_CONFIDENCE = 0.5


def _ensure_wrapped(func: Any) -> Any:
    """Ensure decorated methods expose __wrapped__ even when RBAC is patched."""
    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def _async_wrapper(*args: Any, **kwargs: Any) -> Any:
            return await func(*args, **kwargs)

        return _async_wrapper

    @functools.wraps(func)
    def _sync_wrapper(*args: Any, **kwargs: Any) -> Any:
        return func(*args, **kwargs)

    return _sync_wrapper


_rbac_require_permission = require_permission


def require_permission(*args: Any, **kwargs: Any):  # type: ignore[no-redef]
    """Local wrapper to preserve __wrapped__ even if RBAC is bypassed in tests."""
    decorator = _rbac_require_permission(*args, **kwargs)

    def _decorator(func: Any):
        return _ensure_wrapped(decorator(func))

    return _decorator


class SessionStatus(str, Enum):
    """Training session status values."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class LearningMode(str, Enum):
    """Learning mode types."""

    SUPERVISED = "supervised"
    REINFORCEMENT = "reinforcement"
    SELF_SUPERVISED = "self_supervised"
    TRANSFER = "transfer"
    FEDERATED = "federated"


class MetricType(str, Enum):
    """Types of learning metrics."""

    ACCURACY = "accuracy"
    LOSS = "loss"
    PRECISION = "precision"
    RECALL = "recall"
    F1_SCORE = "f1_score"
    CALIBRATION = "calibration"
    CONVERGENCE = "convergence"


class PatternType(str, Enum):
    """Types of detected patterns."""

    CONSENSUS = "consensus"
    DISAGREEMENT = "disagreement"
    AGENT_PREFERENCE = "agent_preference"
    TOPIC_CLUSTER = "topic_cluster"
    TEMPORAL = "temporal"
    CROSS_DEBATE = "cross_debate"


class FeedbackType(str, Enum):
    """Types of learning feedback."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    CORRECTION = "correction"


@dataclass
class TrainingSession:
    """Represents an autonomous training session."""

    id: str
    name: str
    mode: LearningMode
    status: SessionStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    owner_id: str = "system"
    tenant_id: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    metrics: dict[str, float] = field(default_factory=dict)
    epochs_completed: int = 0
    total_epochs: int = 100
    current_loss: float = 0.0
    best_loss: float = float("inf")
    error_message: str | None = None

    @property
    def progress_percent(self) -> float:
        """Calculate training progress percentage."""
        if self.total_epochs == 0:
            return 0.0
        return (self.epochs_completed / self.total_epochs) * 100

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "owner_id": self.owner_id,
            "tenant_id": self.tenant_id,
            "config": self.config,
            "metrics": self.metrics,
            "epochs_completed": self.epochs_completed,
            "total_epochs": self.total_epochs,
            "current_loss": self.current_loss,
            "best_loss": self.best_loss if self.best_loss != float("inf") else None,
            "progress_percent": round(self.progress_percent, 2),
            "error_message": self.error_message,
        }


@dataclass
class LearningMetric:
    """Represents a learning metric measurement."""

    metric_type: MetricType
    value: float
    timestamp: datetime
    session_id: str | None = None
    agent_id: str | None = None
    debate_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "metric_type": self.metric_type.value,
            "value": round(self.value, 4),
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "debate_id": self.debate_id,
            "metadata": self.metadata,
        }


@dataclass
class DetectedPattern:
    """Represents a detected learning pattern."""

    id: str
    pattern_type: PatternType
    confidence: float
    description: str
    detected_at: datetime
    source_debates: list[str] = field(default_factory=list)
    agents_involved: list[str] = field(default_factory=list)
    frequency: int = 1
    is_validated: bool = False
    validated_by: str | None = None
    validated_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "pattern_type": self.pattern_type.value,
            "confidence": round(self.confidence, 4),
            "description": self.description,
            "detected_at": self.detected_at.isoformat(),
            "source_debates": self.source_debates,
            "agents_involved": self.agents_involved,
            "frequency": self.frequency,
            "is_validated": self.is_validated,
            "validated_by": self.validated_by,
            "validated_at": self.validated_at.isoformat() if self.validated_at else None,
            "metadata": self.metadata,
        }


@dataclass
class ExtractedKnowledge:
    """Represents knowledge extracted from debates."""

    id: str
    title: str
    content: str
    source_type: str
    source_debates: list[str]
    confidence: float
    extracted_at: datetime
    agent_id: str | None = None
    topics: list[str] = field(default_factory=list)
    is_verified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content,
            "source_type": self.source_type,
            "source_debates": self.source_debates,
            "confidence": round(self.confidence, 4),
            "extracted_at": self.extracted_at.isoformat(),
            "agent_id": self.agent_id,
            "topics": self.topics,
            "is_verified": self.is_verified,
            "metadata": self.metadata,
        }


@dataclass
class LearningFeedback:
    """Represents feedback on learning outcomes."""

    id: str
    feedback_type: FeedbackType
    target_type: str  # "session", "pattern", "knowledge"
    target_id: str
    comment: str
    submitted_by: str
    submitted_at: datetime
    rating: int | None = None  # 1-5 scale
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "feedback_type": self.feedback_type.value,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "comment": self.comment,
            "submitted_by": self.submitted_by,
            "submitted_at": self.submitted_at.isoformat(),
            "rating": self.rating,
            "metadata": self.metadata,
        }


@dataclass
class LearningRecommendation:
    """Represents a learning recommendation."""

    id: str
    title: str
    description: str
    priority: int  # 1-5, 1 being highest
    recommendation_type: str
    estimated_impact: float
    created_at: datetime
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "priority": self.priority,
            "recommendation_type": self.recommendation_type,
            "estimated_impact": round(self.estimated_impact, 4),
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata,
        }


@dataclass
class PerformanceStats:
    """Represents model performance statistics."""

    total_sessions: int
    successful_sessions: int
    failed_sessions: int
    average_accuracy: float
    average_loss: float
    total_epochs_trained: int
    total_training_time_hours: float
    patterns_detected: int
    knowledge_items_extracted: int
    feedback_received: int
    last_updated: datetime

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_sessions": self.total_sessions,
            "successful_sessions": self.successful_sessions,
            "failed_sessions": self.failed_sessions,
            "success_rate": round(self.successful_sessions / max(self.total_sessions, 1) * 100, 2),
            "average_accuracy": round(self.average_accuracy, 4),
            "average_loss": round(self.average_loss, 4),
            "total_epochs_trained": self.total_epochs_trained,
            "total_training_time_hours": round(self.total_training_time_hours, 2),
            "patterns_detected": self.patterns_detected,
            "knowledge_items_extracted": self.knowledge_items_extracted,
            "feedback_received": self.feedback_received,
            "last_updated": self.last_updated.isoformat(),
        }


class AutonomousLearningHandler(BaseHandler):
    """
    HTTP handler for autonomous learning operations.

    Provides REST API access to training sessions, metrics, patterns,
    and knowledge extraction with circuit breaker protection and rate limiting.

    Stability: STABLE
    """

    ROUTES = [
        "/api/v2/learning/sessions",
        "/api/v2/learning/sessions/*",
        "/api/v2/learning/metrics",
        "/api/v2/learning/metrics/*",
        "/api/v2/learning/feedback",
        "/api/v2/learning/patterns",
        "/api/v2/learning/patterns/*",
        "/api/v2/learning/knowledge",
        "/api/v2/learning/knowledge/*",
        "/api/v2/learning/recommendations",
        "/api/v2/learning/performance",
        "/api/v2/learning/calibrate",
        "/api/v1/learning/knowledge/extract",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._sessions: dict[str, TrainingSession] = {}
        self._metrics: list[LearningMetric] = []
        self._patterns: dict[str, DetectedPattern] = {}
        self._knowledge: dict[str, ExtractedKnowledge] = {}
        self._feedback: list[LearningFeedback] = []
        self._circuit_breaker: CircuitBreaker | None = None

    def _get_circuit_breaker(self) -> CircuitBreaker:
        """Get or create circuit breaker for learning operations."""
        if self._circuit_breaker is None:
            self._circuit_breaker = get_circuit_breaker(
                LEARNING_CB_NAME,
                failure_threshold=LEARNING_CB_FAILURE_THRESHOLD,
                cooldown_seconds=LEARNING_CB_COOLDOWN_SECONDS,
            )
        return self._circuit_breaker

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the request."""
        if path.startswith("/api/v2/learning/"):
            return method in ("GET", "POST", "DELETE")
        return False

    def _generate_session_id(self) -> str:
        """Generate a unique session ID."""
        return f"session_{uuid.uuid4().hex[:16]}"

    def _generate_pattern_id(self) -> str:
        """Generate a unique pattern ID."""
        return f"pattern_{uuid.uuid4().hex[:12]}"

    def _generate_knowledge_id(self) -> str:
        """Generate a unique knowledge ID."""
        return f"knowledge_{uuid.uuid4().hex[:12]}"

    def _generate_feedback_id(self) -> str:
        """Generate a unique feedback ID."""
        return f"feedback_{uuid.uuid4().hex[:12]}"

    @rate_limit(requests_per_minute=60)
    async def handle(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route GET requests to appropriate handler method."""
        method: str = getattr(handler, "command", "GET") if handler else "GET"
        if method != "GET":
            return None

        query_params = query_params or {}

        try:
            # Check circuit breaker
            cb = self._get_circuit_breaker()
            if not cb.can_proceed():
                logger.warning("Learning circuit breaker is open")
                return error_response(
                    "Learning service temporarily unavailable",
                    503,
                )

            # List sessions
            if path == "/api/v2/learning/sessions":
                return await self._list_sessions(query_params, handler)

            # Get performance stats
            if path == "/api/v2/learning/performance":
                return await self._get_performance(handler)

            # Get recommendations
            if path == "/api/v2/learning/recommendations":
                return await self._get_recommendations(query_params, handler)

            # List patterns
            if path == "/api/v2/learning/patterns":
                return await self._list_patterns(query_params, handler)

            # Get knowledge
            if path == "/api/v2/learning/knowledge":
                return await self._list_knowledge(query_params, handler)

            # Get metrics
            if path == "/api/v2/learning/metrics":
                return await self._get_metrics(query_params, handler)

            # Session-specific routes
            if path.startswith("/api/v2/learning/sessions/"):
                parts = path.split("/")
                # Path: /api/v2/learning/sessions/:session_id -> ["", "api", "v2", "learning", "sessions", session_id]
                if len(parts) < 6:
                    return error_response("Invalid session path", 400)
                session_id = parts[5]
                return await self._get_session(session_id, handler)

            # Metric-specific routes
            if path.startswith("/api/v2/learning/metrics/"):
                parts = path.split("/")
                # Path: /api/v2/learning/metrics/:metric_type -> ["", "api", "v2", "learning", "metrics", metric_type]
                if len(parts) < 6:
                    return error_response("Invalid metric path", 400)
                metric_type = parts[5]
                return await self._get_metric_by_type(metric_type, query_params, handler)

            # Pattern-specific routes
            if path.startswith("/api/v2/learning/patterns/"):
                parts = path.split("/")
                # Path: /api/v2/learning/patterns/:pattern_id -> ["", "api", "v2", "learning", "patterns", pattern_id]
                if len(parts) < 6:
                    return error_response("Invalid pattern path", 400)
                pattern_id = parts[5]
                return await self._get_pattern(pattern_id, handler)

            # Knowledge-specific routes
            if path.startswith("/api/v2/learning/knowledge/"):
                parts = path.split("/")
                # Path: /api/v2/learning/knowledge/:knowledge_id -> ["", "api", "v2", "learning", "knowledge", knowledge_id]
                if len(parts) < 6:
                    return error_response("Invalid knowledge path", 400)
                knowledge_id = parts[5]
                return await self._get_knowledge_item(knowledge_id, handler)

            return None

        except CircuitOpenError:
            logger.warning("Learning circuit breaker tripped")
            return error_response(
                "Learning service temporarily unavailable",
                503,
            )
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Error handling learning GET request: %s", e)
            cb = self._get_circuit_breaker()
            cb.record_failure()
            return error_response("Internal server error", 500)

    @handle_errors("autonomous learning creation")
    @rate_limit(requests_per_minute=30)
    @require_permission("debates:write")
    async def handle_post(
        self,
        path: str,
        query_params: dict[str, Any],
        handler: Any,
    ) -> HandlerResult | None:
        """Route POST requests to appropriate handler method."""
        query_params = query_params or {}

        try:
            # Check circuit breaker
            cb = self._get_circuit_breaker()
            if not cb.can_proceed():
                logger.warning("Learning circuit breaker is open")
                return error_response(
                    "Learning service temporarily unavailable",
                    503,
                )

            # Create session
            if path == "/api/v2/learning/sessions":
                body, error = self.read_json_object_or_error(handler)
                if error:
                    return error
                return await self._create_session(body, handler)

            # Submit feedback
            if path == "/api/v2/learning/feedback":
                body, error = self.read_json_object_or_error(handler)
                if error:
                    return error
                return await self._submit_feedback(body, handler)

            # Trigger knowledge extraction
            if path == "/api/v2/learning/knowledge/extract":
                body, error = self.read_json_object_or_error(handler)
                if error:
                    return error
                return await self._extract_knowledge(body, handler)

            # Trigger calibration
            if path == "/api/v2/learning/calibrate":
                body, error = self.read_json_object_or_error(handler)
                if error:
                    return error
                return await self._calibrate(body, handler)

            # Session-specific POST routes
            if path.startswith("/api/v2/learning/sessions/"):
                parts = path.split("/")
                # Path: /api/v2/learning/sessions/:session_id/stop -> ["", "api", "v2", "learning", "sessions", session_id, "stop"]
                if len(parts) < 6:
                    return error_response("Invalid session path", 400)

                session_id = parts[5]

                # Stop session
                if len(parts) > 6 and parts[6] == "stop":
                    return await self._stop_session(session_id, handler)

            # Pattern validation
            if path.startswith("/api/v2/learning/patterns/"):
                parts = path.split("/")
                # Path: /api/v2/learning/patterns/:pattern_id/validate -> ["", "api", "v2", "learning", "patterns", pattern_id, "validate"]
                if len(parts) < 7:
                    return error_response("Invalid pattern path", 400)

                pattern_id = parts[5]

                if parts[6] == "validate":
                    body, error = self.read_json_object_or_error(handler)
                    if error:
                        return error
                    return await self._validate_pattern(pattern_id, body, handler)

            return None

        except CircuitOpenError:
            logger.warning("Learning circuit breaker tripped")
            return error_response(
                "Learning service temporarily unavailable",
                503,
            )
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.exception("Error handling learning POST request: %s", e)
            cb = self._get_circuit_breaker()
            cb.record_failure()
            return error_response("Internal server error", 500)

    @require_permission("learning:read")
    async def _list_sessions(
        self,
        query_params: dict[str, str],
        handler: Any,
    ) -> HandlerResult:
        """List training sessions with filtering and pagination."""
        status_filter = query_params.get("status")
        mode_filter = query_params.get("mode")
        limit = safe_query_int(query_params, "limit", default=20, min_val=1, max_val=100)
        offset = safe_query_int(query_params, "offset", default=0, min_val=0, max_val=10000)

        sessions = list(self._sessions.values())

        # Apply filters
        if status_filter:
            try:
                status = SessionStatus(status_filter)
                sessions = [s for s in sessions if s.status == status]
            except ValueError:
                return error_response(f"Invalid status: {status_filter}", 400)

        if mode_filter:
            try:
                mode = LearningMode(mode_filter)
                sessions = [s for s in sessions if s.mode == mode]
            except ValueError:
                return error_response(f"Invalid mode: {mode_filter}", 400)

        # Sort by created_at descending
        sessions.sort(key=lambda s: s.created_at, reverse=True)

        total = len(sessions)
        sessions = sessions[offset : offset + limit]

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "sessions": [s.to_dict() for s in sessions],
                "pagination": {
                    "limit": limit,
                    "offset": offset,
                    "total": total,
                    "has_more": offset + len(sessions) < total,
                },
            }
        )

    @require_permission("learning:read")
    async def _get_session(self, session_id: str, handler: Any) -> HandlerResult:
        """Get session details by ID."""
        session = self._sessions.get(session_id)
        if not session:
            return error_response("Session not found", 404)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(session.to_dict())

    @require_permission("learning:write")
    async def _create_session(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Create a new training session."""
        name = body.get("name", "").strip()
        if not name:
            return error_response("Session name is required", 400)

        mode_str = body.get("mode", "supervised")
        if not isinstance(mode_str, str):
            return error_response("mode must be a string", 400)
        try:
            mode = LearningMode(mode_str)
        except ValueError:
            return error_response(f"Invalid learning mode: {mode_str}", 400)

        config = body.get("config", {})
        if not isinstance(config, dict):
            return error_response("config must be a JSON object", 400)

        total_epochs = body.get("total_epochs", 100)
        if isinstance(total_epochs, bool) or not isinstance(total_epochs, int) or total_epochs <= 0:
            return error_response("total_epochs must be a positive integer", 400)

        # Check max active sessions
        active_sessions = sum(
            1
            for s in self._sessions.values()
            if s.status in (SessionStatus.PENDING, SessionStatus.RUNNING)
        )
        if active_sessions >= MAX_ACTIVE_SESSIONS:
            return error_response(
                f"Maximum active sessions ({MAX_ACTIVE_SESSIONS}) reached",
                400,
            )

        user = self.get_current_user(handler)
        owner_id = user.user_id if user else "anonymous"

        session_id = self._generate_session_id()
        now = datetime.now(timezone.utc)

        session = TrainingSession(
            id=session_id,
            name=name,
            mode=mode,
            status=SessionStatus.PENDING,
            created_at=now,
            owner_id=owner_id,
            config=config,
            total_epochs=total_epochs,
        )

        # Automatically start the session
        session.status = SessionStatus.RUNNING
        session.started_at = now

        self._sessions[session_id] = session

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "session": session.to_dict(),
                "message": f"Training session created and started: {session_id}",
            },
            status=201,
        )

    @require_permission("learning:write")
    async def _stop_session(self, session_id: str, handler: Any) -> HandlerResult:
        """Stop a running training session."""
        session = self._sessions.get(session_id)
        if not session:
            return error_response("Session not found", 404)

        if session.status not in (SessionStatus.PENDING, SessionStatus.RUNNING):
            return error_response(
                f"Cannot stop session with status: {session.status.value}",
                400,
            )

        session.status = SessionStatus.CANCELLED
        session.completed_at = datetime.now(timezone.utc)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "session": session.to_dict(),
                "message": f"Training session stopped: {session_id}",
            }
        )

    @require_permission("learning:read")
    async def _get_metrics(
        self,
        query_params: dict[str, str],
        handler: Any,
    ) -> HandlerResult:
        """Get learning metrics with filtering."""
        session_id = query_params.get("session_id")
        agent_id = query_params.get("agent_id")
        limit = safe_query_int(query_params, "limit", default=100, min_val=1, max_val=1000)

        metrics = self._metrics.copy()

        # Apply filters
        if session_id:
            metrics = [m for m in metrics if m.session_id == session_id]
        if agent_id:
            metrics = [m for m in metrics if m.agent_id == agent_id]

        # Sort by timestamp descending
        metrics.sort(key=lambda m: m.timestamp, reverse=True)
        metrics = metrics[:limit]

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "metrics": [m.to_dict() for m in metrics],
                "count": len(metrics),
            }
        )

    @require_permission("learning:read")
    async def _get_metric_by_type(
        self,
        metric_type: str,
        query_params: dict[str, str],
        handler: Any,
    ) -> HandlerResult:
        """Get metrics of a specific type."""
        try:
            m_type = MetricType(metric_type)
        except ValueError:
            return error_response(f"Invalid metric type: {metric_type}", 400)

        metrics = [m for m in self._metrics if m.metric_type == m_type]
        metrics.sort(key=lambda m: m.timestamp, reverse=True)

        # Calculate aggregates
        if metrics:
            values = [m.value for m in metrics]
            avg_value = sum(values) / len(values)
            min_value = min(values)
            max_value = max(values)
        else:
            avg_value = 0.0
            min_value = 0.0
            max_value = 0.0

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "metric_type": metric_type,
                "count": len(metrics),
                "average": round(avg_value, 4),
                "min": round(min_value, 4),
                "max": round(max_value, 4),
                "recent": [m.to_dict() for m in metrics[:10]],
            }
        )

    @require_permission("learning:read")
    async def _list_patterns(
        self,
        query_params: dict[str, str],
        handler: Any,
    ) -> HandlerResult:
        """List detected patterns with filtering."""
        pattern_type_filter = query_params.get("pattern_type")
        validated_only = query_params.get("validated", "").lower() == "true"
        try:
            min_confidence = float(query_params.get("min_confidence", MIN_PATTERN_CONFIDENCE))
        except (ValueError, TypeError):
            min_confidence = MIN_PATTERN_CONFIDENCE
        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=200)

        patterns = list(self._patterns.values())

        # Apply filters
        if pattern_type_filter:
            try:
                p_type = PatternType(pattern_type_filter)
                patterns = [p for p in patterns if p.pattern_type == p_type]
            except ValueError:
                return error_response(f"Invalid pattern type: {pattern_type_filter}", 400)

        if validated_only:
            patterns = [p for p in patterns if p.is_validated]

        patterns = [p for p in patterns if p.confidence >= min_confidence]

        # Sort by confidence descending
        patterns.sort(key=lambda p: p.confidence, reverse=True)
        patterns = patterns[:limit]

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "patterns": [p.to_dict() for p in patterns],
                "count": len(patterns),
            }
        )

    @require_permission("learning:read")
    async def _get_pattern(self, pattern_id: str, handler: Any) -> HandlerResult:
        """Get pattern details by ID."""
        pattern = self._patterns.get(pattern_id)
        if not pattern:
            return error_response("Pattern not found", 404)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(pattern.to_dict())

    @require_permission("learning:write")
    async def _validate_pattern(
        self,
        pattern_id: str,
        body: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Validate a detected pattern."""
        pattern = self._patterns.get(pattern_id)
        if not pattern:
            return error_response("Pattern not found", 404)

        user = self.get_current_user(handler)
        validated_by = user.user_id if user else "anonymous"

        pattern.is_validated = True
        pattern.validated_by = validated_by
        pattern.validated_at = datetime.now(timezone.utc)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "pattern": pattern.to_dict(),
                "message": f"Pattern validated: {pattern_id}",
            }
        )

    @require_permission("learning:read")
    async def _list_knowledge(
        self,
        query_params: dict[str, str],
        handler: Any,
    ) -> HandlerResult:
        """List extracted knowledge with filtering."""
        verified_only = query_params.get("verified", "").lower() == "true"
        source_type = query_params.get("source_type")
        limit = safe_query_int(query_params, "limit", default=50, min_val=1, max_val=200)

        knowledge_items = list(self._knowledge.values())

        # Apply filters
        if verified_only:
            knowledge_items = [k for k in knowledge_items if k.is_verified]
        if source_type:
            knowledge_items = [k for k in knowledge_items if k.source_type == source_type]

        # Sort by confidence descending
        knowledge_items.sort(key=lambda k: k.confidence, reverse=True)
        knowledge_items = knowledge_items[:limit]

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "knowledge": [k.to_dict() for k in knowledge_items],
                "count": len(knowledge_items),
            }
        )

    @require_permission("learning:read")
    async def _get_knowledge_item(self, knowledge_id: str, handler: Any) -> HandlerResult:
        """Get knowledge item details by ID."""
        knowledge = self._knowledge.get(knowledge_id)
        if not knowledge:
            return error_response("Knowledge item not found", 404)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(knowledge.to_dict())

    @require_permission("learning:write")
    async def _extract_knowledge(
        self,
        body: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Trigger knowledge extraction from debates."""
        debate_ids = body.get("debate_ids", [])
        if not isinstance(debate_ids, list) or not all(
            isinstance(debate_id, str) and debate_id.strip() for debate_id in debate_ids
        ):
            return error_response("debate_ids is required and must be a list of strings", 400)
        if not debate_ids:
            return error_response("debate_ids is required", 400)

        topics = body.get("topics", ["general"])
        if not isinstance(topics, list) or not all(isinstance(topic, str) for topic in topics):
            return error_response("topics must be a list of strings", 400)

        # Simulate knowledge extraction
        knowledge_id = self._generate_knowledge_id()
        now = datetime.now(timezone.utc)

        knowledge = ExtractedKnowledge(
            id=knowledge_id,
            title=body.get("title", "Extracted Knowledge"),
            content=body.get("content", "Knowledge extracted from debate analysis."),
            source_type="debate_analysis",
            source_debates=debate_ids,
            confidence=random.uniform(0.7, 0.95),  # noqa: S311 -- simulated metric
            extracted_at=now,
            topics=topics,
        )

        self._knowledge[knowledge_id] = knowledge

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "knowledge": knowledge.to_dict(),
                "message": f"Knowledge extracted: {knowledge_id}",
            },
            status=201,
        )

    @require_permission("learning:write")
    async def _submit_feedback(
        self,
        body: dict[str, Any],
        handler: Any,
    ) -> HandlerResult:
        """Submit feedback on learning outcomes."""
        feedback_type_str = body.get("feedback_type", "neutral")
        try:
            feedback_type = FeedbackType(feedback_type_str)
        except ValueError:
            return error_response(f"Invalid feedback type: {feedback_type_str}", 400)

        target_type = body.get("target_type")
        target_id = body.get("target_id")
        comment = body.get("comment", "").strip()

        if not target_type or not target_id:
            return error_response("target_type and target_id are required", 400)

        if target_type not in ("session", "pattern", "knowledge"):
            return error_response(f"Invalid target_type: {target_type}", 400)

        rating = body.get("rating")
        if rating is not None:
            if isinstance(rating, bool) or not isinstance(rating, int):
                return error_response("rating must be an integer", 400)

        user = self.get_current_user(handler)
        submitted_by = user.user_id if user else "anonymous"

        feedback_id = self._generate_feedback_id()
        now = datetime.now(timezone.utc)

        feedback = LearningFeedback(
            id=feedback_id,
            feedback_type=feedback_type,
            target_type=target_type,
            target_id=target_id,
            comment=comment,
            submitted_by=submitted_by,
            submitted_at=now,
            rating=rating,
        )

        self._feedback.append(feedback)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "feedback": feedback.to_dict(),
                "message": "Feedback submitted successfully",
            },
            status=201,
        )

    @require_permission("learning:read")
    async def _get_recommendations(
        self,
        query_params: dict[str, str],
        handler: Any,
    ) -> HandlerResult:
        """Get learning recommendations."""
        limit = safe_query_int(query_params, "limit", default=10, min_val=1, max_val=50)

        # Generate recommendations based on current state
        recommendations: list[LearningRecommendation] = []
        now = datetime.now(timezone.utc)

        # Recommendation based on session activity
        running_sessions = sum(
            1 for s in self._sessions.values() if s.status == SessionStatus.RUNNING
        )
        if running_sessions == 0:
            recommendations.append(
                LearningRecommendation(
                    id=f"rec_{uuid.uuid4().hex[:8]}",
                    title="Start a training session",
                    description="No active training sessions. Consider starting a new session to improve model performance.",
                    priority=2,
                    recommendation_type="action",
                    estimated_impact=0.15,
                    created_at=now,
                )
            )

        # Recommendation based on patterns
        unvalidated_patterns = sum(
            1 for p in self._patterns.values() if not p.is_validated and p.confidence > 0.7
        )
        if unvalidated_patterns > 0:
            recommendations.append(
                LearningRecommendation(
                    id=f"rec_{uuid.uuid4().hex[:8]}",
                    title=f"Validate {unvalidated_patterns} high-confidence patterns",
                    description="There are high-confidence patterns awaiting validation. Validating them will improve learning accuracy.",
                    priority=1,
                    recommendation_type="review",
                    estimated_impact=0.2,
                    created_at=now,
                )
            )

        # Recommendation based on feedback
        recent_negative = sum(
            1
            for f in self._feedback
            if f.feedback_type == FeedbackType.NEGATIVE
            and (now - f.submitted_at) < timedelta(days=7)
        )
        if recent_negative > 3:
            recommendations.append(
                LearningRecommendation(
                    id=f"rec_{uuid.uuid4().hex[:8]}",
                    title="Address negative feedback",
                    description=f"Received {recent_negative} negative feedback items this week. Review and address concerns.",
                    priority=1,
                    recommendation_type="improvement",
                    estimated_impact=0.25,
                    created_at=now,
                )
            )

        # Sort by priority
        recommendations.sort(key=lambda r: r.priority)
        recommendations = recommendations[:limit]

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "recommendations": [r.to_dict() for r in recommendations],
                "count": len(recommendations),
            }
        )

    @require_permission("learning:read")
    async def _get_performance(self, handler: Any) -> HandlerResult:
        """Get model performance statistics."""
        sessions = list(self._sessions.values())

        total_sessions = len(sessions)
        successful_sessions = sum(1 for s in sessions if s.status == SessionStatus.COMPLETED)
        failed_sessions = sum(1 for s in sessions if s.status == SessionStatus.FAILED)

        # Calculate averages
        completed_sessions = [s for s in sessions if s.status == SessionStatus.COMPLETED]
        if completed_sessions:
            avg_accuracy = sum(s.metrics.get("accuracy", 0) for s in completed_sessions) / len(
                completed_sessions
            )
            avg_loss = sum(s.current_loss for s in completed_sessions) / len(completed_sessions)
        else:
            avg_accuracy = 0.0
            avg_loss = 0.0

        total_epochs = sum(s.epochs_completed for s in sessions)

        # Estimate training time (mock calculation)
        total_training_hours = total_epochs * 0.01  # Assume 0.01 hours per epoch

        stats = PerformanceStats(
            total_sessions=total_sessions,
            successful_sessions=successful_sessions,
            failed_sessions=failed_sessions,
            average_accuracy=avg_accuracy,
            average_loss=avg_loss,
            total_epochs_trained=total_epochs,
            total_training_time_hours=total_training_hours,
            patterns_detected=len(self._patterns),
            knowledge_items_extracted=len(self._knowledge),
            feedback_received=len(self._feedback),
            last_updated=datetime.now(timezone.utc),
        )

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "performance": stats.to_dict(),
            }
        )

    @require_permission("learning:write")
    async def _calibrate(self, body: dict[str, Any], handler: Any) -> HandlerResult:
        """Trigger model calibration."""
        agent_ids = body.get("agent_ids", [])
        force = body.get("force", False)
        if not isinstance(agent_ids, list) or not all(
            isinstance(agent_id, str) for agent_id in agent_ids
        ):
            return error_response("agent_ids must be a list of strings", 400)
        if not isinstance(force, bool):
            return error_response("force must be a boolean", 400)

        # Simulate calibration
        now = datetime.now(timezone.utc)
        calibration_id = f"calibration_{uuid.uuid4().hex[:12]}"

        # Record calibration metric
        metric = LearningMetric(
            metric_type=MetricType.CALIBRATION,
            value=random.uniform(0.85, 0.98),  # noqa: S311 -- simulated metric
            timestamp=now,
            metadata={
                "calibration_id": calibration_id,
                "agent_ids": agent_ids,
                "forced": force,
            },
        )
        self._metrics.append(metric)

        cb = self._get_circuit_breaker()
        cb.record_success()

        return json_response(
            {
                "calibration_id": calibration_id,
                "metric": metric.to_dict(),
                "message": "Calibration completed successfully",
            }
        )


# Handler factory function for registration
def create_autonomous_learning_handler(server_context: dict[str, Any]) -> AutonomousLearningHandler:
    """Factory function for handler registration."""
    return AutonomousLearningHandler(server_context)
