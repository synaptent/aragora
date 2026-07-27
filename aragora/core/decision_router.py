"""
Decision Router for unified request routing.

Extracted from decision.py for modularity.
Routes decision requests to appropriate engines (Debate, Workflow, Gauntlet, Quick).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal, cast
from collections.abc import Awaitable, Callable

from .decision_types import (
    DecisionType,
)
from .decision_models import (
    DecisionRequest,
    DecisionResult,
    ResponseChannel,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Lazy imports to avoid circular dependencies
# =============================================================================

# Lazy import for tracing
_tracing_imported = False
_trace_decision = None
_trace_decision_engine = None
_trace_response_delivery = None


def _import_tracing():
    """Lazy import tracing utilities."""
    global _tracing_imported, _trace_decision, _trace_decision_engine, _trace_response_delivery
    if _tracing_imported:
        return
    try:
        from aragora.observability.tracing import (
            trace_decision,
            trace_decision_engine,
            trace_response_delivery,
        )

        _trace_decision = trace_decision
        _trace_decision_engine = trace_decision_engine
        _trace_response_delivery = trace_response_delivery
    except ImportError:
        pass
    _tracing_imported = True


# Lazy import for caching
_cache_imported = False
_decision_cache = None


def _import_cache():
    """Lazy import cache utilities."""
    global _cache_imported, _decision_cache
    if _cache_imported:
        return
    try:
        from aragora.core.decision_cache import get_decision_cache

        _decision_cache = get_decision_cache()
    except ImportError:
        pass
    _cache_imported = True


# Lazy import for metrics
_metrics_imported = False
_record_decision_request = None
_record_decision_result = None
_record_decision_error = None
_record_decision_cache_hit = None
_record_decision_dedup_hit = None


def _import_metrics():
    """Lazy import metrics utilities."""
    global _metrics_imported, _record_decision_request, _record_decision_result
    global _record_decision_error, _record_decision_cache_hit, _record_decision_dedup_hit
    if _metrics_imported:
        return
    try:
        from aragora.observability.decision_metrics import (
            record_decision_request,
            record_decision_result,
            record_decision_error,
            record_decision_cache_hit,
            record_decision_dedup_hit,
        )

        _record_decision_request = record_decision_request
        _record_decision_result = record_decision_result
        _record_decision_error = record_decision_error
        _record_decision_cache_hit = record_decision_cache_hit
        _record_decision_dedup_hit = record_decision_dedup_hit
    except ImportError:
        pass
    _metrics_imported = True


# Lazy import for audit logging
_audit_imported = False
_audit_log_decision_started = None
_audit_log_decision_completed = None


def _import_audit():
    """Lazy import audit utilities."""
    global _audit_imported, _audit_log_decision_started, _audit_log_decision_completed
    if _audit_imported:
        return
    try:
        from aragora.audit.unified import (
            get_unified_audit_logger,
            UnifiedAuditEvent,
            UnifiedAuditCategory,
            AuditOutcome,
            AuditSeverity,
        )

        _logger = get_unified_audit_logger()

        def log_decision_started(
            request_id: str,
            decision_type: str,
            source: str,
            user_id: str | None = None,
            workspace_id: str | None = None,
            content_preview: str | None = None,
        ) -> None:
            """Log decision request started."""
            _logger.log(
                UnifiedAuditEvent(
                    category=UnifiedAuditCategory.DEBATE_STARTED,
                    action=f"Decision {decision_type} started",
                    actor_id=user_id,
                    resource_type="decision",
                    resource_id=request_id,
                    workspace_id=workspace_id,
                    details={
                        "decision_type": decision_type,
                        "source": source,
                        "content_preview": (content_preview or "")[:200],
                    },
                )
            )

        def log_decision_completed(
            request_id: str,
            decision_type: str,
            success: bool,
            consensus_reached: bool,
            confidence: float,
            duration_seconds: float,
            user_id: str | None = None,
            workspace_id: str | None = None,
            error: str | None = None,
        ) -> None:
            """Log decision request completed."""
            _logger.log(
                UnifiedAuditEvent(
                    category=UnifiedAuditCategory.DEBATE_COMPLETED,
                    action=f"Decision {decision_type} completed",
                    outcome=AuditOutcome.SUCCESS if success else AuditOutcome.FAILURE,
                    severity=AuditSeverity.INFO if success else AuditSeverity.WARNING,
                    actor_id=user_id,
                    resource_type="decision",
                    resource_id=request_id,
                    workspace_id=workspace_id,
                    details={
                        "decision_type": decision_type,
                        "consensus_reached": consensus_reached,
                        "confidence": confidence,
                        "duration_seconds": duration_seconds,
                        "error": error,
                    },
                )
            )

        global _audit_log_decision_started, _audit_log_decision_completed
        _audit_log_decision_started = log_decision_started
        _audit_log_decision_completed = log_decision_completed
    except ImportError:
        pass
    _audit_imported = True


# =============================================================================
# DecisionRouter
# =============================================================================


class DecisionRouter:
    """
    Routes decision requests to the appropriate engine.

    Provides a unified entry point for all decision-making requests,
    handling routing, validation, and response delivery.
    """

    def __init__(
        self,
        debate_engine: Any | None = None,
        workflow_engine: Any | None = None,
        gauntlet_engine: Any | None = None,
        enable_voice_responses: bool = True,
        enable_caching: bool = True,
        enable_deduplication: bool = True,
        cache_ttl_seconds: float = 3600.0,
        rbac_enforcer: Any | None = None,
        document_store: Any | None = None,
        evidence_store: Any | None = None,
    ):
        """
        Initialize the router.

        Args:
            debate_engine: Arena instance or factory
            workflow_engine: WorkflowEngine instance or factory
            gauntlet_engine: GauntletOrchestrator instance or factory
            enable_voice_responses: Whether to enable TTS for voice responses
            enable_caching: Whether to cache decision results
            enable_deduplication: Whether to deduplicate concurrent identical requests
            cache_ttl_seconds: How long to cache results (default 1 hour)
            rbac_enforcer: Optional RBACEnforcer for authorization checks
        """
        self._debate_engine = debate_engine
        self._workflow_engine = workflow_engine
        self._gauntlet_engine = gauntlet_engine
        self._response_handlers: dict[str, Callable[..., Awaitable[None]]] = {}
        self._enable_voice_responses = enable_voice_responses
        self._tts_bridge: Any | None = None
        self._rbac_enforcer = rbac_enforcer
        self._document_store = document_store
        self._evidence_store = evidence_store

        # Cache configuration
        self._enable_caching = enable_caching
        self._enable_deduplication = enable_deduplication
        self._cache_ttl_seconds = cache_ttl_seconds

    def register_response_handler(
        self,
        platform: str,
        handler: Callable[[DecisionResult, ResponseChannel], Awaitable[None]],
    ) -> None:
        """Register a handler for delivering responses to a platform."""
        self._response_handlers[platform.lower()] = handler

    async def route(self, request: DecisionRequest) -> DecisionResult:
        """
        Route a decision request to the appropriate engine.

        Args:
            request: Unified decision request

        Returns:
            DecisionResult with the outcome

        Raises:
            PermissionDeniedError: If RBAC check fails
        """
        # Initialize tracing, caching, metrics, and audit if available
        _import_tracing()
        _import_cache()
        _import_metrics()
        _import_audit()

        logger.info(
            "Routing decision request %s (type=%s, source=%s)",
            request.request_id,
            request.decision_type.value,
            request.source.value,
        )

        # RBAC authorization check
        if self._rbac_enforcer and request.context.user_id:
            try:
                from aragora.rbac import ResourceType, Action, IsolationContext

                # Map decision type to resource type
                resource_type_map = {
                    DecisionType.DEBATE: ResourceType.DEBATE,
                    DecisionType.WORKFLOW: ResourceType.WORKFLOW,
                    DecisionType.GAUNTLET: ResourceType.AUDIT_FINDING,
                    DecisionType.QUICK: ResourceType.DEBATE,
                }
                resource_type = resource_type_map.get(request.decision_type, ResourceType.DEBATE)

                # Build isolation context
                actor_id = request.context.user_id or "anonymous"
                isolation_ctx = IsolationContext(
                    actor_id=actor_id,
                    workspace_id=request.context.workspace_id,
                )

                # Require CREATE permission
                await self._rbac_enforcer.require_async(
                    request.context.user_id,
                    resource_type,
                    Action.CREATE,
                    isolation_ctx,
                )
                logger.debug(
                    "RBAC check passed for user %s on %s",
                    request.context.user_id,
                    resource_type.value,
                )
            except ImportError:
                logger.debug("RBAC module not available, skipping authorization")
            except (PermissionError, ValueError) as e:
                logger.warning("RBAC check failed: %s", e)
                return DecisionResult(
                    request_id=request.request_id,
                    decision_type=request.decision_type,
                    answer="",
                    confidence=0.0,
                    consensus_reached=False,
                    success=False,
                    error=f"Authorization denied: {e}",
                )

        start_time = datetime.now(timezone.utc)

        # Record incoming request metric
        if _record_decision_request:
            _record_decision_request(
                decision_type=request.decision_type.value,
                source=request.source.value,
                priority=request.priority.value if request.priority else "normal",
            )

        # Log audit trail: decision started
        if _audit_log_decision_started:
            try:
                _audit_log_decision_started(
                    request_id=request.request_id,
                    decision_type=request.decision_type.value,
                    source=request.source.value,
                    user_id=request.context.user_id,
                    workspace_id=request.context.workspace_id,
                    content_preview=request.content[:200] if request.content else None,
                )
            except (OSError, RuntimeError, TypeError, ValueError) as e:
                logger.debug("Audit log (started) failed: %s", e)

        # Check cache first
        cache_hit = False
        if self._enable_caching and _decision_cache:
            cached_result = await _decision_cache.get(request)
            if cached_result:
                logger.info("Cache hit for request %s", request.request_id)
                cache_hit = True
                # Record cache hit metric
                if _record_decision_cache_hit:
                    _record_decision_cache_hit(request.decision_type.value)
                # Record result metric for cached response
                if _record_decision_result:
                    _record_decision_result(
                        decision_type=request.decision_type.value,
                        source=request.source.value,
                        success=cached_result.success,
                        confidence=cached_result.confidence,
                        duration_seconds=0.001,  # Near-instant for cache hit
                        consensus_reached=cached_result.consensus_reached,
                        cache_hit=True,
                    )
                # Still deliver responses for cached results
                await self._deliver_responses(request, cached_result)
                return cached_result

        # Check for in-flight deduplication
        if self._enable_deduplication and _decision_cache:
            if await _decision_cache.is_in_flight(request):
                logger.info("Waiting for in-flight request %s", request.request_id)
                dedup_result = await _decision_cache.wait_for_result(request)
                if dedup_result:
                    # Record dedup hit metric
                    if _record_decision_dedup_hit:
                        _record_decision_dedup_hit(request.decision_type.value)
                    # Record result metric for dedup response
                    if _record_decision_result:
                        _record_decision_result(
                            decision_type=request.decision_type.value,
                            source=request.source.value,
                            success=dedup_result.success,
                            confidence=dedup_result.confidence,
                            duration_seconds=(
                                datetime.now(timezone.utc) - start_time
                            ).total_seconds(),
                            consensus_reached=dedup_result.consensus_reached,
                            dedup_hit=True,
                        )
                    await self._deliver_responses(request, dedup_result)
                    return dedup_result

        # Mark as in-flight for deduplication
        if self._enable_deduplication and _decision_cache:
            await _decision_cache.mark_in_flight(request)

        # Create tracing span if available
        span = None
        span_ctx = None
        if _trace_decision_engine:
            try:
                from aragora.observability.tracing import trace_decision_routing

                span_ctx = trace_decision_routing(
                    request_id=request.request_id,
                    decision_type=request.decision_type.value,
                    source=request.source.value,
                    priority=request.priority.value if request.priority else "normal",
                )
                span = span_ctx.__enter__()
                span.set_attribute("decision.content_length", len(request.content))
                span.set_attribute("decision.cache_hit", cache_hit)
                if request.config and request.config.agents:
                    span.set_attribute("decision.agent_count", len(request.config.agents))
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.debug("Tracing not available: %s", e)

        try:
            if request.decision_type == DecisionType.DEBATE:
                result = await self._route_to_debate(request)
            elif request.decision_type == DecisionType.WORKFLOW:
                result = await self._route_to_workflow(request)
            elif request.decision_type == DecisionType.GAUNTLET:
                result = await self._route_to_gauntlet(request)
            elif request.decision_type == DecisionType.QUICK:
                result = await self._route_to_quick(request)
            else:
                raise ValueError(f"Unknown decision type: {request.decision_type}")

            # Calculate duration
            result.duration_seconds = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Record result in span
            if span:
                span.set_attribute("decision.duration_seconds", result.duration_seconds)
                span.set_attribute("decision.confidence", result.confidence)
                span.set_attribute("decision.consensus_reached", result.consensus_reached)
                span.set_attribute("decision.success", result.success)

            # Record successful result metric
            if _record_decision_result:
                agent_count = len(request.config.agents) if request.config.agents else 0
                _record_decision_result(
                    decision_type=request.decision_type.value,
                    source=request.source.value,
                    success=result.success,
                    confidence=result.confidence,
                    duration_seconds=result.duration_seconds,
                    consensus_reached=result.consensus_reached,
                    cache_hit=False,
                    dedup_hit=False,
                    agent_count=agent_count,
                )

            # Log audit trail: decision completed (success)
            if _audit_log_decision_completed:
                try:
                    _audit_log_decision_completed(
                        request_id=request.request_id,
                        decision_type=request.decision_type.value,
                        success=result.success,
                        consensus_reached=result.consensus_reached,
                        confidence=result.confidence,
                        duration_seconds=result.duration_seconds,
                        user_id=request.context.user_id,
                        workspace_id=request.context.workspace_id,
                        error=result.error,
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as audit_err:
                    logger.debug("Audit log (completed) failed: %s", audit_err)

            # Cache the result
            if self._enable_caching and _decision_cache and result.success:
                await _decision_cache.set(request, result, ttl_seconds=self._cache_ttl_seconds)

            # Complete in-flight for deduplication
            if self._enable_deduplication and _decision_cache:
                await _decision_cache.complete_in_flight(request, result=result)

            # Deliver responses
            await self._deliver_responses(request, result)

            return result

        except (
            ValueError,
            TypeError,
            KeyError,
            AttributeError,
            RuntimeError,
            OSError,
            TimeoutError,
        ) as e:
            logger.error("Decision routing failed: %s", e, exc_info=True)
            if span:
                span.set_attribute("decision.error", str(e)[:200])
                try:
                    span.record_exception(e)
                except (AttributeError, RuntimeError, TypeError) as trace_err:
                    logger.debug("Failed to record exception in span: %s", trace_err)

            error_duration = (datetime.now(timezone.utc) - start_time).total_seconds()

            # Record error metrics
            error_type = type(e).__name__
            if _record_decision_error:
                _record_decision_error(
                    decision_type=request.decision_type.value,
                    error_type=error_type,
                )

            if _record_decision_result:
                _record_decision_result(
                    decision_type=request.decision_type.value,
                    source=request.source.value,
                    success=False,
                    confidence=0.0,
                    duration_seconds=error_duration,
                    consensus_reached=False,
                    error_type=error_type,
                )

            # Log audit trail: decision completed (error)
            if _audit_log_decision_completed:
                try:
                    _audit_log_decision_completed(
                        request_id=request.request_id,
                        decision_type=request.decision_type.value,
                        success=False,
                        consensus_reached=False,
                        confidence=0.0,
                        duration_seconds=error_duration,
                        user_id=request.context.user_id,
                        workspace_id=request.context.workspace_id,
                        error=str(e),
                    )
                except (OSError, RuntimeError, TypeError, ValueError) as audit_err:
                    logger.debug("Audit log (error) failed: %s", audit_err)

            error_result = DecisionResult(
                request_id=request.request_id,
                decision_type=request.decision_type,
                answer="",
                confidence=0.0,
                consensus_reached=False,
                success=False,
                error=f"Decision routing failed: {type(e).__name__}",
                duration_seconds=error_duration,
            )

            # Complete in-flight with error
            if self._enable_deduplication and _decision_cache:
                await _decision_cache.complete_in_flight(request, error=e)

            return error_result
        finally:
            # Close span context
            if span_ctx:
                try:
                    span_ctx.__exit__(None, None, None)
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug("Span context exit error: %s", e)

            # Clean up in-flight status after a delay
            if self._enable_deduplication and _decision_cache:
                try:
                    await _decision_cache.clear_in_flight(request)
                except (OSError, RuntimeError, ConnectionError, TimeoutError) as e:
                    logger.debug("Failed to clear in-flight cache: %s", e)

    async def _route_to_debate(self, request: DecisionRequest) -> DecisionResult:
        """Route to debate engine."""
        # Create engine span if tracing available
        span = None
        span_ctx = None
        if _trace_decision_engine:
            try:
                span_ctx = _trace_decision_engine("debate", request.request_id)
                span = span_ctx.__enter__()
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.debug("Failed to create debate trace span: %s", e)

        try:
            if self._debate_engine is None:
                # Lazy load
                from aragora.debate import Arena

                self._debate_engine = Arena

            # Convert to debate format
            from aragora.agents import get_agents_by_names
            from aragora.core_types import Environment
            from aragora.debate.protocol import DebateProtocol

            # Gather knowledge context if enabled
            knowledge_context = ""
            document_ids: list[str] = []
            if request.config.use_knowledge_mound:
                knowledge_context, document_ids = await self._gather_knowledge_context(
                    query=request.content,
                    workspace_id=request.context.workspace_id,
                )

            # Merge explicit document IDs from request/context metadata
            explicit_docs: list[str] = []
            if getattr(request, "documents", None):
                explicit_docs.extend(request.documents)
            metadata = request.context.metadata or {}
            metadata_docs = metadata.get("documents") or metadata.get("document_ids") or []
            if metadata_docs:
                from aragora.core.decision_models import normalize_document_ids

                explicit_docs.extend(normalize_document_ids(metadata_docs))
            # Ingest attachments into DocumentStore where possible
            attachment_docs = self._ingest_attachments_to_documents(
                request.attachments,
                request=request,
            )
            if attachment_docs:
                explicit_docs.extend(attachment_docs)
            # Persist request-supplied evidence snippets for retrieval
            self._ingest_request_evidence(request.evidence, request=request)
            if explicit_docs:
                seen: set[str] = set()
                merged: list[str] = []
                for doc_id in explicit_docs + document_ids:
                    if doc_id and doc_id not in seen:
                        seen.add(doc_id)
                        merged.append(doc_id)
                document_ids = merged

            # Include attachment context (if any) for richer inputs
            attachment_context = self._format_attachment_context(request.attachments)
            if attachment_context:
                if knowledge_context:
                    knowledge_context = f"{knowledge_context}\n\n{attachment_context}"
                else:
                    knowledge_context = attachment_context
            evidence_context = self._format_request_evidence_context(request.evidence)
            if evidence_context:
                if knowledge_context:
                    knowledge_context = f"{knowledge_context}\n\n{evidence_context}"
                else:
                    knowledge_context = evidence_context

            env = Environment(
                task=request.content,
                context=knowledge_context,
                documents=document_ids,
            )
            # Cast consensus to Literal type expected by DebateProtocol
            consensus_type = cast(
                Literal[
                    "majority",
                    "unanimous",
                    "judge",
                    "none",
                    "weighted",
                    "supermajority",
                    "any",
                    "byzantine",
                ],
                request.config.consensus,
            )
            protocol = DebateProtocol(
                rounds=request.config.rounds,
                consensus=consensus_type,
                enable_calibration=request.config.enable_calibration,
                early_stopping=request.config.early_stopping,
                timeout_seconds=request.config.timeout_seconds,
            )

            if span:
                span.set_attribute("debate.rounds", request.config.rounds)
                span.set_attribute("debate.agents", ",".join(request.config.agents or []))

            # Create arena and run
            agents = get_agents_by_names(request.config.agents) if request.config.agents else []
            arena = self._debate_engine(
                environment=env,
                agents=agents,
                protocol=protocol,
                document_store=self._document_store,
                evidence_store=self._evidence_store,
            )

            debate_result = await arena.run()

            if span:
                span.set_attribute("debate.consensus_reached", debate_result.consensus_reached)
                if hasattr(debate_result, "rounds_used"):
                    span.set_attribute("debate.rounds_used", debate_result.rounds_used)

            decision_integrity = await self._maybe_build_decision_integrity(
                request,
                debate_result,
                arena=arena,
            )

            return DecisionResult(
                request_id=request.request_id,
                decision_type=DecisionType.DEBATE,
                answer=debate_result.final_answer or "",
                confidence=(
                    debate_result.confidence if hasattr(debate_result, "confidence") else 0.8
                ),
                consensus_reached=debate_result.consensus_reached,
                reasoning=debate_result.summary if hasattr(debate_result, "summary") else None,
                debate_id=getattr(debate_result, "debate_id", None),
                debate_result=debate_result,
                decision_integrity=decision_integrity,
            )
        finally:
            if span_ctx:
                try:
                    span_ctx.__exit__(None, None, None)
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug("Trace span cleanup error: %s", e)

    async def _maybe_build_decision_integrity(
        self,
        request: DecisionRequest,
        debate_result: Any,
        arena: Any | None = None,
    ) -> dict[str, Any] | None:
        """Optionally build a Decision Integrity package after debate completion."""
        cfg_raw = getattr(request.config, "decision_integrity", {}) or {}
        notify_origin = False
        if isinstance(cfg_raw, dict):
            notify_origin = bool(cfg_raw.get("notify_origin", False))

        try:
            from aragora.pipeline.decision_integrity_utils import (
                build_decision_integrity_payload,
            )
        except (ImportError, AttributeError) as exc:
            logger.debug("Decision integrity utilities unavailable: %s", exc)
            return None

        return await build_decision_integrity_payload(
            result=debate_result,
            debate_id=getattr(debate_result, "debate_id", None),
            arena=arena,
            decision_integrity=cfg_raw,
            document_store=self._document_store,
            evidence_store=self._evidence_store,
            notify_origin_override=notify_origin,
        )

    def _ingest_attachments_to_documents(
        self,
        attachments: list[dict[str, Any]] | None,
        request: DecisionRequest | None = None,
        max_items: int = 5,
        max_bytes: int = 2_000_000,
    ) -> list[str]:
        """Store supported attachments in DocumentStore and return document IDs."""
        if not attachments or not self._document_store:
            return []

        doc_ids: list[str] = []
        try:
            from aragora.documents.parsing import ParsedDocument, parse_document, parse_text
            import base64
        except (ImportError, AttributeError) as e:
            logger.debug("Document ingestion unavailable: %s", e)
            return []

        for idx, att in enumerate(attachments[:max_items]):
            if not isinstance(att, dict):
                continue
            existing = att.get("document_id") or att.get("doc_id")
            if isinstance(existing, str) and existing.strip():
                doc_ids.append(existing.strip())
                continue

            filename = att.get("filename") or att.get("name") or f"attachment_{idx + 1}.txt"
            data = att.get("data")
            content = att.get("content") or att.get("text")
            encoding = str(att.get("encoding") or "").lower()

            payload: bytes | None = None
            if isinstance(data, (bytes, bytearray)):
                payload = bytes(data)
            elif isinstance(content, (bytes, bytearray)):
                payload = bytes(content)
            elif isinstance(data, str):
                if encoding in {"base64", "b64"}:
                    try:
                        payload = base64.b64decode(data, validate=False)
                    except (ValueError, UnicodeError):
                        payload = data.encode("utf-8", errors="ignore")
                else:
                    payload = data.encode("utf-8", errors="ignore")
            elif isinstance(content, str):
                payload = content.encode("utf-8", errors="ignore")

            if not payload:
                continue
            if len(payload) > max_bytes:
                logger.debug("Skipping attachment %s (exceeds %s bytes)", filename, max_bytes)
                continue

            try:
                if filename.lower().endswith((".txt", ".md", ".markdown")):
                    parsed: ParsedDocument = parse_text(payload, filename)
                else:
                    parsed = parse_document(payload, filename)
                doc_id = self._document_store.add(parsed)
                if doc_id:
                    doc_ids.append(doc_id)
                self._store_attachment_evidence(
                    parsed=parsed,
                    filename=filename,
                    attachment=att,
                    index=idx,
                    request=request,
                )
            except (ValueError, TypeError, OSError, KeyError) as e:
                logger.debug("Failed to ingest attachment %s: %s", filename, e)

        return doc_ids

    def _store_attachment_evidence(
        self,
        parsed: Any,
        filename: str,
        attachment: dict[str, Any],
        index: int,
        request: DecisionRequest | None,
        max_chars: int = 4000,
    ) -> None:
        """Persist attachment text into EvidenceStore for cross-session retrieval."""
        if not self._evidence_store:
            return

        text = getattr(parsed, "text", None)
        if not isinstance(text, str):
            return
        text = text.strip()
        if not text:
            return

        snippet = text[:max_chars]
        url = attachment.get("url")
        if not isinstance(url, str):
            url = ""

        metadata: dict[str, Any] = {
            "filename": filename,
            "content_type": getattr(parsed, "content_type", None),
            "document_id": getattr(parsed, "id", None),
            "attachment_index": index,
        }
        if request is not None:
            metadata["request_id"] = request.request_id
            metadata["correlation_id"] = request.context.correlation_id
            if request.context.workspace_id:
                metadata["workspace_id"] = request.context.workspace_id
            if request.context.tenant_id:
                metadata["tenant_id"] = request.context.tenant_id
            if request.source:
                metadata["source"] = request.source.value

        try:
            import uuid

            evidence_id = f"att_{uuid.uuid4().hex}"
            self._evidence_store.save_evidence(
                evidence_id=evidence_id,
                source="attachment",
                title=filename,
                snippet=snippet,
                url=url,
                reliability_score=0.5,
                metadata=metadata,
            )
        except (ValueError, TypeError, OSError, KeyError) as e:
            logger.debug("Failed to store attachment evidence %s: %s", filename, e)

    def _format_attachment_context(
        self,
        attachments: list[dict[str, Any]] | None,
        max_items: int = 5,
        max_chars: int = 1200,
    ) -> str:
        """Build a compact context block from attachments."""
        if not attachments:
            return ""

        parts: list[str] = []
        for att in attachments[:max_items]:
            if not isinstance(att, dict):
                continue
            att_type = str(att.get("type") or "attachment")
            name = att.get("filename") or att.get("name") or att.get("title") or att_type
            url = att.get("url")
            content = att.get("content") or att.get("text")
            if content is None:
                data = att.get("data")
                if isinstance(data, str):
                    content = data

            if isinstance(content, (bytes, bytearray)):
                content = None

            header = f"### {name} ({att_type})"
            if url:
                header = f"{header}\nSource: {url}"

            if content:
                content_str = str(content).strip()
                if len(content_str) > max_chars:
                    content_str = content_str[:max_chars] + "..."
                parts.append(f"{header}\n{content_str}")
            else:
                parts.append(f"{header}\n[Attachment content not provided]")

        if not parts:
            return ""
        return "## Provided Attachments\n\n" + "\n\n".join(parts)

    def _ingest_request_evidence(
        self,
        evidence: list[dict[str, Any]] | None,
        request: DecisionRequest | None = None,
        max_items: int = 10,
        max_chars: int = 4000,
    ) -> list[str]:
        """Store request-supplied evidence in the EvidenceStore."""
        if not evidence or not self._evidence_store:
            return []

        saved_ids: list[str] = []
        for idx, item in enumerate(evidence[:max_items]):
            if not isinstance(item, dict):
                continue
            raw_snippet = item.get("snippet") or item.get("content") or item.get("text") or ""
            if isinstance(raw_snippet, (bytes, bytearray)):
                raw_snippet = raw_snippet.decode("utf-8", errors="ignore")
            snippet = str(raw_snippet).strip()
            if not snippet:
                continue

            if len(snippet) > max_chars:
                snippet = snippet[:max_chars] + "..."

            evidence_id = item.get("evidence_id") or item.get("id")
            if not isinstance(evidence_id, str) or not evidence_id:
                import uuid

                evidence_id = f"req_{uuid.uuid4().hex}"

            source = item.get("source") or item.get("type") or "request"
            title = item.get("title") or item.get("name") or f"Evidence {idx + 1}"
            url = item.get("url") if isinstance(item.get("url"), str) else ""
            reliability_score = item.get("reliability_score") or item.get("score") or 0.5
            try:
                reliability_score = float(reliability_score)
            except (TypeError, ValueError):
                reliability_score = 0.5

            metadata = dict(item.get("metadata") or {})
            metadata["evidence_index"] = idx
            if request is not None:
                metadata["request_id"] = request.request_id
                metadata["correlation_id"] = request.context.correlation_id
                if request.context.workspace_id:
                    metadata["workspace_id"] = request.context.workspace_id
                if request.context.tenant_id:
                    metadata["tenant_id"] = request.context.tenant_id
                if request.source:
                    metadata["source"] = request.source.value

            try:
                saved_id = self._evidence_store.save_evidence(
                    evidence_id=evidence_id,
                    source=str(source),
                    title=str(title),
                    snippet=snippet,
                    url=url,
                    reliability_score=reliability_score,
                    metadata=metadata,
                )
                saved_ids.append(saved_id)
            except (ValueError, TypeError, OSError, KeyError) as e:
                logger.debug("Failed to store request evidence %s: %s", evidence_id, e)

        return saved_ids

    def _format_request_evidence_context(
        self,
        evidence: list[dict[str, Any]] | None,
        max_items: int = 5,
        max_chars: int = 1200,
    ) -> str:
        """Format request-provided evidence for immediate context injection."""
        if not evidence:
            return ""

        parts: list[str] = []
        for item in evidence[:max_items]:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or "Evidence"
            source = item.get("source") or item.get("type") or "request"
            url = item.get("url")
            content = item.get("snippet") or item.get("content") or item.get("text") or ""
            if isinstance(content, (bytes, bytearray)):
                content = content.decode("utf-8", errors="ignore")
            content_str = str(content).strip()
            if not content_str:
                continue
            if len(content_str) > max_chars:
                content_str = content_str[:max_chars] + "..."

            header = f"### {title} ({source})"
            if url:
                header = f"{header}\nSource: {url}"
            parts.append(f"{header}\n{content_str}")

        if not parts:
            return ""
        return "## Provided Evidence\n\n" + "\n\n".join(parts)

    async def _route_to_workflow(self, request: DecisionRequest) -> DecisionResult:
        """Route to workflow engine."""
        span = None
        span_ctx = None
        if _trace_decision_engine:
            try:
                span_ctx = _trace_decision_engine("workflow", request.request_id)
                span = span_ctx.__enter__()
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.debug("Trace span error: %s", e)

        try:
            if self._workflow_engine is None:
                from aragora.workflow.engine import get_workflow_engine

                self._workflow_engine = get_workflow_engine()

            # Get or create workflow definition
            workflow_id = request.config.workflow_id
            if not workflow_id:
                raise ValueError("Workflow ID required for workflow decision type")

            if span:
                span.set_attribute("workflow.id", workflow_id)

            # Load workflow definition from workflow store
            import inspect
            from aragora.workflow.persistent_store import get_workflow_store

            workflow_store = get_workflow_store()
            definition_result = workflow_store.get_workflow(workflow_id)
            # Handle both sync and async get_workflow implementations
            if inspect.iscoroutine(definition_result):
                definition = await definition_result
            else:
                definition = definition_result
            if not definition:
                raise ValueError(f"Workflow not found: {workflow_id}")

            documents = list(getattr(request, "documents", []) or [])
            metadata_docs = (request.context.metadata or {}).get("documents") or (
                request.context.metadata or {}
            ).get("document_ids")
            if metadata_docs:
                from aragora.core.decision_models import normalize_document_ids

                documents.extend(normalize_document_ids(metadata_docs))
            # Execute
            workflow_result = await self._workflow_engine.execute(
                definition=definition,
                inputs={
                    "content": request.content,
                    "documents": documents,
                    "attachments": request.attachments or [],
                    "evidence": request.evidence or [],
                    **request.config.workflow_inputs,
                },
            )

            if span:
                span.set_attribute("workflow.success", workflow_result.success)

            # Extract answer from workflow final_output
            outputs = workflow_result.final_output if workflow_result.final_output else {}
            answer = outputs.get("answer") or outputs.get("result") or ""

            return DecisionResult(
                request_id=request.request_id,
                decision_type=DecisionType.WORKFLOW,
                answer=str(answer),
                confidence=0.9 if workflow_result.success else 0.0,
                consensus_reached=workflow_result.success,
                workflow_result=workflow_result,
            )
        finally:
            if span_ctx:
                try:
                    span_ctx.__exit__(None, None, None)
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug("Trace span cleanup error: %s", e)

    async def _route_to_gauntlet(self, request: DecisionRequest) -> DecisionResult:
        """Route to gauntlet engine."""
        span = None
        span_ctx = None
        if _trace_decision_engine:
            try:
                span_ctx = _trace_decision_engine("gauntlet", request.request_id)
                span = span_ctx.__enter__()
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.debug("Trace span error: %s", e)

        try:
            from aragora.gauntlet.orchestrator import (
                GauntletOrchestrator,
                GauntletConfig as OrchestratorConfig,
                Verdict,
            )
            from aragora.agents import get_agents_by_names

            if self._gauntlet_engine is None:
                agents = get_agents_by_names(request.config.agents) if request.config.agents else []
                self._gauntlet_engine = GauntletOrchestrator(agents=agents)

            config = OrchestratorConfig(
                input_content=request.content,
                enable_redteam=request.config.enable_adversarial,
                enable_verification=request.config.enable_formal_verification,
                max_duration_seconds=request.config.timeout_seconds,
            )

            if span:
                span.set_attribute("gauntlet.adversarial", request.config.enable_adversarial)
                span.set_attribute(
                    "gauntlet.formal_verification", request.config.enable_formal_verification
                )

            gauntlet_result = await self._gauntlet_engine.run(config=config)

            # Derive passed status from verdict
            passed = gauntlet_result.verdict in (Verdict.PASS, Verdict.APPROVED)
            verdict_summary = gauntlet_result.verdict.value if gauntlet_result.verdict else ""

            if span:
                span.set_attribute("gauntlet.passed", passed)
                span.set_attribute("gauntlet.confidence", gauntlet_result.confidence)

            return DecisionResult(
                request_id=request.request_id,
                decision_type=DecisionType.GAUNTLET,
                answer=verdict_summary,
                confidence=gauntlet_result.confidence,
                consensus_reached=passed,
                gauntlet_result=gauntlet_result,
            )
        finally:
            if span_ctx:
                try:
                    span_ctx.__exit__(None, None, None)
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug("Trace span cleanup error: %s", e)

    async def _route_to_quick(self, request: DecisionRequest) -> DecisionResult:
        """Route to quick single-agent response."""
        span = None
        span_ctx = None
        if _trace_decision_engine:
            try:
                span_ctx = _trace_decision_engine("quick", request.request_id)
                span = span_ctx.__enter__()
            except (ImportError, AttributeError, RuntimeError) as e:
                logger.debug("Trace span error: %s", e)

        # Use first configured agent for quick response
        agent_name = request.config.agents[0] if request.config.agents else "anthropic-api"

        if span:
            span.set_attribute("quick.agent", agent_name)

        try:
            from aragora.agents import create_agent
            from aragora.agents.base import AgentType

            agent = create_agent(cast(AgentType, agent_name))

            response = await agent.generate(request.content)

            if span:
                span.set_attribute("quick.response_length", len(response))

            return DecisionResult(
                request_id=request.request_id,
                decision_type=DecisionType.QUICK,
                answer=response,
                confidence=0.7,  # Single agent = moderate confidence
                consensus_reached=True,
                agent_contributions=[{"agent": agent_name, "response": response}],
            )
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.error("Quick response failed: %s", e)
            if span:
                span.set_attribute("quick.error", str(e)[:200])
            return DecisionResult(
                request_id=request.request_id,
                decision_type=DecisionType.QUICK,
                answer="",
                confidence=0.0,
                consensus_reached=False,
                success=False,
                error=f"Quick response failed: {type(e).__name__}",
            )
        finally:
            if span_ctx:
                try:
                    span_ctx.__exit__(None, None, None)
                except (AttributeError, RuntimeError, TypeError) as e:
                    logger.debug("Trace span cleanup error: %s", e)

    async def _gather_knowledge_context(
        self,
        query: str,
        workspace_id: str | None = None,
        max_items: int = 5,
    ) -> tuple[str, list[str]]:
        """
        Gather relevant knowledge context from Knowledge Mound for the debate.

        Args:
            query: The decision question/content
            workspace_id: Optional workspace to scope the query
            max_items: Maximum knowledge items to include

        Returns:
            Tuple of (context_string, document_ids)
        """
        try:
            from aragora.knowledge.pipeline import KnowledgePipeline, PipelineConfig

            # Create a lightweight pipeline for querying
            config = PipelineConfig(
                workspace_id=workspace_id or "default",
                use_knowledge_mound=True,
            )
            pipeline = KnowledgePipeline(config)
            await pipeline.start()

            try:
                # Query the knowledge mound for relevant context
                mound_result = await pipeline.query_mound(
                    query=query,
                    limit=max_items,
                )

                if not mound_result or not mound_result.items:
                    return "", []

                # Build context string from knowledge items
                context_parts = []
                document_ids = []

                for item in mound_result.items[:max_items]:
                    content = getattr(item, "content", str(item))
                    if len(content) > 500:
                        content = content[:500] + "..."
                    context_parts.append(f"[Knowledge] {content}")

                    # Extract document IDs if available
                    metadata = getattr(item, "metadata", {}) or {}
                    if doc_id := metadata.get("document_id"):
                        document_ids.append(doc_id)

                context_string = "\n\n".join(context_parts)
                if context_string:
                    context_string = (
                        f"## Relevant Organizational Knowledge\n\n{context_string}\n\n---\n"
                    )

                logger.info("Gathered %s knowledge items for debate context", len(context_parts))
                return context_string, list(set(document_ids))

            finally:
                await pipeline.stop()

        except ImportError:
            logger.debug("Knowledge pipeline not available for context gathering")
            return "", []
        except (ValueError, TypeError, KeyError, AttributeError, RuntimeError, OSError) as e:
            logger.warning("Failed to gather knowledge context: %s", e)
            return "", []

    def _get_tts_bridge(self) -> Any | None:
        """Lazy-load TTS bridge for voice responses."""
        if self._tts_bridge is not None:
            return self._tts_bridge

        if not self._enable_voice_responses:
            return None

        try:
            from aragora.connectors.chat.tts_bridge import get_tts_bridge

            self._tts_bridge = get_tts_bridge()
            logger.info("TTS bridge initialized for voice responses")
            return self._tts_bridge
        except ImportError as e:
            logger.warning("TTS bridge not available: %s", e)
            return None
        except (RuntimeError, OSError, AttributeError) as e:
            logger.error("Failed to initialize TTS bridge: %s", e)
            return None

    async def synthesize_voice_response(
        self,
        text: str,
        voice_id: str = "narrator",
        context: str | None = None,
    ) -> bytes | None:
        """
        Synthesize text to audio for voice response.

        Args:
            text: Text to synthesize
            voice_id: Voice/speaker identifier
            context: Optional context hint for voice selection

        Returns:
            Audio bytes if successful, None otherwise
        """
        tts = self._get_tts_bridge()
        if tts is None:
            logger.warning("TTS not available for voice response")
            return None

        try:
            audio_path = await tts.synthesize(
                text=text,
                voice=voice_id,
                context=context,
            )
            if audio_path and audio_path.exists():
                audio_bytes = audio_path.read_bytes()
                # Clean up temp file
                try:
                    audio_path.unlink()
                except (OSError, PermissionError) as e:
                    logger.debug("Failed to cleanup temp audio file: %s", e)
                return audio_bytes
        except (RuntimeError, OSError, ValueError, TypeError) as e:
            logger.error("Voice synthesis failed: %s", e)

        return None

    async def _deliver_responses(
        self,
        request: DecisionRequest,
        result: DecisionResult,
    ) -> None:
        """Deliver result to all response channels."""
        for channel in request.response_channels:
            try:
                # Handle voice responses
                if channel.voice_enabled or channel.response_format in ("voice", "voice_with_text"):
                    await self._deliver_voice_response(result, channel)

                    # If voice_only, skip text delivery
                    if channel.voice_only:
                        continue

                # Deliver text response via platform handler
                handler = self._response_handlers.get(channel.platform)
                if handler:
                    await handler(result, channel)

            except (RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
                logger.error("Failed to deliver to %s: %s", channel.platform, e)

    async def _deliver_voice_response(
        self,
        result: DecisionResult,
        channel: ResponseChannel,
    ) -> bytes | None:
        """Deliver voice response for a channel."""
        # Format text for voice (more concise than full text)
        if channel.response_format == "notification":
            voice_text = f"Decision complete. {result.answer[:200]}"
        elif channel.response_format == "summary":
            voice_text = result.answer[:500]
        else:
            voice_text = result.answer[:1000]

        # Add confidence if applicable
        if result.consensus_reached:
            voice_text = f"Consensus reached with {result.confidence:.0%} confidence. {voice_text}"

        # Synthesize audio
        audio_bytes = await self.synthesize_voice_response(
            text=voice_text,
            voice_id=channel.voice_id,
            context=result.decision_type.value,
        )

        if audio_bytes:
            # If there's a voice-specific handler, use it
            voice_handler = self._response_handlers.get(f"{channel.platform}_voice")
            if voice_handler:
                try:
                    await voice_handler(result, channel, audio_bytes)
                except (RuntimeError, OSError, ValueError, TypeError, ConnectionError) as e:
                    logger.error("Voice delivery failed for %s: %s", channel.platform, e)

        return audio_bytes


# =============================================================================
# Singleton management
# =============================================================================

_router: DecisionRouter | None = None


def get_decision_router(
    document_store: Any | None = None,
    evidence_store: Any | None = None,
) -> DecisionRouter:
    """Get or create the global decision router."""
    global _router
    if _router is None:
        _router = DecisionRouter(
            document_store=document_store,
            evidence_store=evidence_store,
        )
    else:
        if document_store and getattr(_router, "_document_store", None) is None:
            _router._document_store = document_store  # type: ignore[attr-defined]
        if evidence_store and getattr(_router, "_evidence_store", None) is None:
            _router._evidence_store = evidence_store  # type: ignore[attr-defined]
    return _router


def reset_decision_router() -> None:
    """Reset the global decision router (for testing)."""
    global _router
    _router = None


__all__ = [
    "DecisionRouter",
    "get_decision_router",
    "reset_decision_router",
]
