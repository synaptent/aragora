"""
Decision data models (dataclasses).

Extracted from decision.py for modularity.
Provides request/response schemas for the unified decision system.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .decision_types import (
    DecisionType,
    InputSource,
    Priority,
    _DEFAULT_DECISION_CONSENSUS,
    _DEFAULT_DECISION_MAX_AGENTS,
    _DEFAULT_DECISION_ROUNDS,
    _default_decision_agents,
)


@dataclass
class ResponseChannel:
    """
    Where to send the decision result.

    Supports multiple output channels for the same request.
    """

    platform: str  # slack, discord, http, websocket, email, webhook, voice
    channel_id: str | None = None  # Slack channel, Discord channel, etc.
    user_id: str | None = None  # Direct message to user
    thread_id: str | None = None  # Reply in thread
    webhook_url: str | None = None  # Webhook callback URL
    email_address: str | None = None  # Email recipient
    response_format: str = "full"  # full, summary, notification, voice
    include_reasoning: bool = True  # Include chain-of-thought

    # Voice/TTS settings
    voice_enabled: bool = False  # Whether to include voice response
    voice_id: str = "narrator"  # TTS voice/speaker identifier
    voice_only: bool = False  # If True, only send audio (no text)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "platform": self.platform,
            "channel_id": self.channel_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "webhook_url": self.webhook_url,
            "email_address": self.email_address,
            "response_format": self.response_format,
            "include_reasoning": self.include_reasoning,
            "voice_enabled": self.voice_enabled,
            "voice_id": self.voice_id,
            "voice_only": self.voice_only,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ResponseChannel:
        """Create from dictionary."""
        return cls(
            platform=data.get("platform", "http"),
            channel_id=data.get("channel_id"),
            user_id=data.get("user_id"),
            thread_id=data.get("thread_id"),
            webhook_url=data.get("webhook_url"),
            email_address=data.get("email_address"),
            response_format=data.get("response_format", "full"),
            include_reasoning=data.get("include_reasoning", True),
            voice_enabled=data.get("voice_enabled", False),
            voice_id=data.get("voice_id", "narrator"),
            voice_only=data.get("voice_only", False),
        )


@dataclass
class RequestContext:
    """
    Context and metadata for the decision request.

    Provides audit trail and correlation capabilities.
    """

    # Correlation
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    parent_request_id: str | None = None  # If spawned from another request
    session_id: str | None = None  # User session

    # User info
    user_id: str | None = None
    user_name: str | None = None
    user_email: str | None = None
    user_roles: list[str] = field(default_factory=list)

    # Tenant/workspace
    tenant_id: str | None = None
    workspace_id: str | None = None

    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    deadline: datetime | None = None  # Hard deadline for response

    # Additional context
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "correlation_id": self.correlation_id,
            "parent_request_id": self.parent_request_id,
            "session_id": self.session_id,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "user_email": self.user_email,
            "user_roles": self.user_roles,
            "tenant_id": self.tenant_id,
            "workspace_id": self.workspace_id,
            "created_at": self.created_at.isoformat(),
            "deadline": self.deadline.isoformat() if self.deadline else None,
            "tags": self.tags,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RequestContext:
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        deadline = data.get("deadline")
        if isinstance(deadline, str):
            deadline = datetime.fromisoformat(deadline)

        return cls(
            correlation_id=data.get("correlation_id", str(uuid.uuid4())),
            parent_request_id=data.get("parent_request_id"),
            session_id=data.get("session_id"),
            user_id=data.get("user_id"),
            user_name=data.get("user_name"),
            user_email=data.get("user_email"),
            user_roles=data.get("user_roles", []),
            tenant_id=data.get("tenant_id"),
            workspace_id=data.get("workspace_id"),
            created_at=created_at or datetime.now(timezone.utc),
            deadline=deadline,
            tags=data.get("tags", []),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DecisionConfig:
    """
    Configuration for the decision-making process.

    Unified configuration that maps to specific engine configs.
    """

    # Common settings
    timeout_seconds: int = 300
    max_agents: int = _DEFAULT_DECISION_MAX_AGENTS
    agents: list[str] = field(default_factory=_default_decision_agents)

    # Debate-specific (mapped to DebateProtocol)
    rounds: int = _DEFAULT_DECISION_ROUNDS
    consensus: str = _DEFAULT_DECISION_CONSENSUS  # majority, unanimous, judge, weighted
    enable_calibration: bool = True
    early_stopping: bool = True

    # Workflow-specific (mapped to WorkflowConfig)
    workflow_id: str | None = None
    workflow_inputs: dict[str, Any] = field(default_factory=dict)
    stop_on_failure: bool = True
    enable_checkpointing: bool = True

    # Gauntlet-specific (mapped to GauntletConfig)
    enable_adversarial: bool = False
    enable_formal_verification: bool = False
    robustness_threshold: float = 0.6
    attack_categories: list[str] = field(default_factory=list)

    # Knowledge integration
    use_knowledge_mound: bool = True
    include_evidence: bool = True
    evidence_sources: list[str] = field(default_factory=list)

    # Decision integrity / implementation planning
    # Example:
    # decision_integrity = {
    #   "include_receipt": True,
    #   "include_plan": True,
    #   "include_context": False,
    #   "plan_strategy": "single_task",
    #   "notify_origin": False,
    # }
    decision_integrity: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "timeout_seconds": self.timeout_seconds,
            "max_agents": self.max_agents,
            "agents": self.agents,
            "rounds": self.rounds,
            "consensus": self.consensus,
            "enable_calibration": self.enable_calibration,
            "early_stopping": self.early_stopping,
            "workflow_id": self.workflow_id,
            "workflow_inputs": self.workflow_inputs,
            "stop_on_failure": self.stop_on_failure,
            "enable_checkpointing": self.enable_checkpointing,
            "enable_adversarial": self.enable_adversarial,
            "enable_formal_verification": self.enable_formal_verification,
            "robustness_threshold": self.robustness_threshold,
            "attack_categories": self.attack_categories,
            "use_knowledge_mound": self.use_knowledge_mound,
            "include_evidence": self.include_evidence,
            "evidence_sources": self.evidence_sources,
            "decision_integrity": self.decision_integrity,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionConfig:
        """Create from dictionary."""
        raw_decision_integrity = data.get("decision_integrity", {}) or {}
        if isinstance(raw_decision_integrity, dict):
            decision_integrity = raw_decision_integrity
        elif isinstance(raw_decision_integrity, bool):
            decision_integrity = {} if raw_decision_integrity else {}
        else:
            decision_integrity = {}

        return cls(
            timeout_seconds=data.get("timeout_seconds", 300),
            max_agents=data.get("max_agents", _DEFAULT_DECISION_MAX_AGENTS),
            agents=data.get("agents", _default_decision_agents()),
            rounds=data.get("rounds", _DEFAULT_DECISION_ROUNDS),
            consensus=data.get("consensus", _DEFAULT_DECISION_CONSENSUS),
            enable_calibration=data.get("enable_calibration", True),
            early_stopping=data.get("early_stopping", True),
            workflow_id=data.get("workflow_id"),
            workflow_inputs=data.get("workflow_inputs", {}),
            stop_on_failure=data.get("stop_on_failure", True),
            enable_checkpointing=data.get("enable_checkpointing", True),
            enable_adversarial=data.get("enable_adversarial", False),
            enable_formal_verification=data.get("enable_formal_verification", False),
            robustness_threshold=data.get("robustness_threshold", 0.6),
            attack_categories=data.get("attack_categories", []),
            use_knowledge_mound=data.get("use_knowledge_mound", True),
            include_evidence=data.get("include_evidence", True),
            evidence_sources=data.get("evidence_sources", []),
            decision_integrity=decision_integrity,
        )


def normalize_document_ids(value: Any, max_items: int = 50) -> list[str]:
    """Normalize document ID input to a clean list of strings."""
    if not value:
        return []
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, list):
        candidates = value
    else:
        return []

    seen: set[str] = set()
    normalized: list[str] = []
    for item in candidates:
        if not isinstance(item, str):
            continue
        doc_id = item.strip()
        if not doc_id or doc_id in seen:
            continue
        seen.add(doc_id)
        normalized.append(doc_id)
        if len(normalized) >= max_items:
            break
    return normalized


def effective_metadata_document_ids(metadata: Any) -> list[str]:
    """Document IDs a request grounds on from its context metadata.

    A non-empty ``documents`` value shadows ``document_ids``, even when it
    holds no valid ID. Routing and the cache/in-flight key both use this, so
    two requests that run on different documents never share a key.
    """
    if not isinstance(metadata, dict):
        return []
    return normalize_document_ids(metadata.get("documents") or metadata.get("document_ids"))


@dataclass
class DecisionRequest:
    """
    Unified decision request that normalizes input from all channels.

    This is the canonical request format for Aragora's decision-making
    capabilities, accepting input from HTTP, WebSocket, chat platforms,
    voice, email, and enterprise integrations.
    """

    # Core content
    content: str  # The question, topic, or input text
    decision_type: DecisionType = DecisionType.AUTO

    # Source and routing
    source: InputSource = InputSource.HTTP_API
    response_channels: list[ResponseChannel] = field(default_factory=list)

    # Request context
    context: RequestContext = field(default_factory=RequestContext)

    # Configuration
    config: DecisionConfig = field(default_factory=DecisionConfig)

    # Priority
    priority: Priority = Priority.NORMAL

    # Additional input data
    attachments: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)

    # Request ID
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __post_init__(self):
        """Validate and normalize the request."""
        # Ensure content is not empty
        if not self.content or not self.content.strip():
            raise ValueError("Decision request content cannot be empty")

        # Ensure at least one response channel
        if not self.response_channels:
            self.response_channels = [ResponseChannel(platform=self.source.value)]

        # Auto-detect decision type if needed
        if self.decision_type == DecisionType.AUTO:
            self.decision_type = self._detect_decision_type()

        # Normalize document IDs
        self.documents = normalize_document_ids(self.documents)

    def _detect_decision_type(self) -> DecisionType:
        """Auto-detect the appropriate decision type based on content."""
        content_lower = self.content.lower()

        # Check for workflow triggers
        if self.config.workflow_id:
            return DecisionType.WORKFLOW

        # Check for gauntlet triggers
        gauntlet_keywords = ["validate", "stress test", "probe", "attack", "security"]
        if any(kw in content_lower for kw in gauntlet_keywords):
            return DecisionType.GAUNTLET

        # Check for quick response triggers
        quick_keywords = ["quick", "fast", "simple", "brief"]
        if any(kw in content_lower for kw in quick_keywords):
            return DecisionType.QUICK

        # Default to debate for complex questions
        return DecisionType.DEBATE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "request_id": self.request_id,
            "content": self.content,
            "decision_type": self.decision_type.value,
            "source": self.source.value,
            "response_channels": [rc.to_dict() for rc in self.response_channels],
            "context": self.context.to_dict(),
            "config": self.config.to_dict(),
            "priority": self.priority.value,
            "attachments": self.attachments,
            "evidence": self.evidence,
            "documents": list(self.documents),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DecisionRequest:
        """Create from dictionary."""
        return cls(
            request_id=data.get("request_id", str(uuid.uuid4())),
            content=data.get("content", ""),
            decision_type=DecisionType(data.get("decision_type", "auto")),
            source=InputSource(data.get("source", "http_api")),
            response_channels=[
                ResponseChannel.from_dict(rc) for rc in data.get("response_channels", [])
            ],
            context=RequestContext.from_dict(data.get("context", {})),
            config=DecisionConfig.from_dict(data.get("config", {})),
            priority=Priority(data.get("priority", "normal")),
            attachments=data.get("attachments", []),
            evidence=data.get("evidence", []),
            documents=normalize_document_ids(
                data.get("documents") or data.get("document_ids") or []
            ),
        )

    @classmethod
    def from_chat_message(
        cls,
        message: str,
        platform: str,
        channel_id: str,
        user_id: str | None = None,
        thread_id: str | None = None,
        **kwargs,
    ) -> DecisionRequest:
        """Create from a chat platform message."""
        documents = normalize_document_ids(
            kwargs.pop("documents", None) or kwargs.pop("document_ids", None) or []
        )
        attachments = kwargs.pop("attachments", []) or []
        evidence = kwargs.pop("evidence", []) or []
        config = kwargs.pop("config", None) or kwargs.pop("decision_config", None)
        decision_integrity = kwargs.pop("decision_integrity", None)
        if config is None and decision_integrity is not None:
            if isinstance(decision_integrity, bool):
                decision_integrity = {} if decision_integrity else {}
            elif not isinstance(decision_integrity, dict):
                decision_integrity = {}
            config = DecisionConfig(decision_integrity=decision_integrity or {})
        source = InputSource(platform.lower())

        response_channel = ResponseChannel(
            platform=platform,
            channel_id=channel_id,
            user_id=user_id,
            thread_id=thread_id,
        )

        context = RequestContext(
            user_id=user_id,
            metadata=kwargs,
        )

        request_kwargs = {
            "content": message,
            "source": source,
            "response_channels": [response_channel],
            "context": context,
            "documents": documents,
            "attachments": attachments,
            "evidence": evidence,
        }
        if config is not None:
            request_kwargs["config"] = config

        return cls(**request_kwargs)  # type: ignore[arg-type]

    @classmethod
    def from_http(
        cls,
        body: dict[str, Any],
        headers: dict[str, str] | None = None,
    ) -> DecisionRequest:
        """Create from HTTP API request body."""
        # Extract correlation ID from headers if present
        correlation_id = None
        if headers:
            correlation_id = headers.get("X-Correlation-ID") or headers.get("X-Request-ID")

        # Handle both new unified format and legacy debate format
        if "content" in body:
            request = cls.from_dict(body)
        else:
            # Legacy format: {question, agents, rounds, consensus, ...}
            documents = normalize_document_ids(
                body.get("documents") or body.get("document_ids") or []
            )
            request = cls(
                content=body.get("question") or body.get("task") or body.get("input_text", ""),
                decision_type=DecisionType(body.get("decision_type", "debate")),
                source=InputSource.HTTP_API,
                config=DecisionConfig(
                    agents=body.get("agents", _default_decision_agents()),
                    rounds=body.get("rounds", _DEFAULT_DECISION_ROUNDS),
                    consensus=body.get("consensus", _DEFAULT_DECISION_CONSENSUS),
                    timeout_seconds=body.get("timeout", 300),
                    decision_integrity=body.get("decision_integrity", {}) or {},
                ),
                documents=documents,
                attachments=body.get("attachments", []),
                evidence=body.get("evidence", []),
            )

        if correlation_id:
            request.context.correlation_id = correlation_id

        return request

    @classmethod
    def from_voice(
        cls,
        transcription: str,
        platform: str,
        channel_id: str,
        audio_duration: float | None = None,
        voice_response: bool = True,
        voice_id: str = "narrator",
        **kwargs,
    ) -> DecisionRequest:
        """Create from a voice message transcription."""
        source_map = {
            "slack": InputSource.VOICE_SLACK,
            "telegram": InputSource.VOICE_TELEGRAM,
            "whatsapp": InputSource.VOICE_WHATSAPP,
        }
        source = source_map.get(platform.lower(), InputSource.VOICE)

        context = RequestContext(
            metadata={
                "audio_duration": audio_duration,
                "transcription_source": "whisper",
                **kwargs,
            }
        )

        # Voice input defaults to voice+text response
        response_channel = ResponseChannel(
            platform=platform,
            channel_id=channel_id,
            response_format="voice_with_text" if voice_response else "full",
            voice_enabled=voice_response,
            voice_id=voice_id,
        )

        return cls(
            content=transcription,
            source=source,
            response_channels=[response_channel],
            context=context,
        )

    @classmethod
    def from_document(
        cls,
        content: str,
        source_platform: str,
        document_id: str,
        document_title: str | None = None,
        document_url: str | None = None,
        user_id: str | None = None,
        **kwargs,
    ) -> DecisionRequest:
        """Create from a document source (Google Drive, SharePoint, etc.)."""
        source_map = {
            "google_drive": InputSource.GOOGLE_DRIVE,
            "gdrive": InputSource.GOOGLE_DRIVE,
            "onedrive": InputSource.ONEDRIVE,
            "sharepoint": InputSource.SHAREPOINT,
            "dropbox": InputSource.DROPBOX,
            "s3": InputSource.S3,
            "confluence": InputSource.CONFLUENCE,
            "notion": InputSource.NOTION,
        }
        source = source_map.get(source_platform.lower(), InputSource.INTERNAL)

        context = RequestContext(
            user_id=user_id,
            metadata={
                "document_id": document_id,
                "document_title": document_title,
                "document_url": document_url,
                "source_platform": source_platform,
                **kwargs,
            },
        )

        # For document sources, typically respond via webhook or the originating system
        response_channel = ResponseChannel(
            platform=source_platform,
            webhook_url=kwargs.get("webhook_url"),
            response_format="full",
        )

        return cls(
            content=content,
            source=source,
            response_channels=[response_channel],
            context=context,
        )


@dataclass
class DecisionResult:
    """
    Unified decision result returned by all decision engines.
    """

    request_id: str
    decision_type: DecisionType

    # Core result
    answer: str
    confidence: float  # 0-1
    consensus_reached: bool

    # Detailed results
    reasoning: str | None = None
    evidence_used: list[dict[str, Any]] = field(default_factory=list)
    agent_contributions: list[dict[str, Any]] = field(default_factory=list)

    # Metadata
    duration_seconds: float = 0.0
    completed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    # Engine-specific results
    debate_id: str | None = None  # ID of associated debate
    debate_result: Any | None = None  # DebateResult
    workflow_result: Any | None = None  # WorkflowResult
    gauntlet_result: Any | None = None  # GauntletResult
    decision_integrity: dict[str, Any] | None = None  # Receipt + plan package

    # Extensible metadata
    metadata: dict[str, Any] | None = None

    # Status
    success: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        result = {
            "request_id": self.request_id,
            "decision_type": self.decision_type.value,
            "answer": self.answer,
            "confidence": self.confidence,
            "consensus_reached": self.consensus_reached,
            "reasoning": self.reasoning,
            "evidence_used": self.evidence_used,
            "agent_contributions": self.agent_contributions,
            "duration_seconds": self.duration_seconds,
            "completed_at": self.completed_at.isoformat(),
            "debate_id": self.debate_id,
            "success": self.success,
            "error": self.error,
        }
        if self.decision_integrity is not None:
            result["decision_integrity"] = self.decision_integrity  # type: ignore[assignment]
        return result


__all__ = [
    "ResponseChannel",
    "RequestContext",
    "DecisionConfig",
    "DecisionRequest",
    "DecisionResult",
]
