"""Decision Integrity pipeline helpers.

Builds a Decision Integrity package from a debate artifact:
- Decision receipt (audit trail)
- Implementation plan (for multi-agent execution)
- Context snapshot (memory + knowledge state for auditability)
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from aragora.core_types import DebateResult
from aragora.gauntlet.receipt import DecisionReceipt
from aragora.implement import create_single_task_plan, generate_implement_plan
from aragora.implement.types import ImplementPlan

logger = logging.getLogger(__name__)


@dataclass
class ContextSnapshot:
    """Snapshot of knowledge/memory context available at decision time.

    Captures state from all memory tiers and knowledge sources so that
    the full evidentiary basis for a decision can be audited later.
    """

    continuum_entries: list[dict[str, Any]] = field(default_factory=list)
    cross_debate_context: str = ""
    cross_debate_ids: list[str] = field(default_factory=list)
    knowledge_items: list[dict[str, Any]] = field(default_factory=list)
    knowledge_sources: list[str] = field(default_factory=list)
    document_items: list[dict[str, Any]] = field(default_factory=list)
    evidence_items: list[dict[str, Any]] = field(default_factory=list)
    context_envelope: dict[str, Any] = field(default_factory=dict)
    total_context_tokens: int = 0
    retrieval_time_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "continuum_entries": self.continuum_entries,
            "cross_debate_context": self.cross_debate_context,
            "cross_debate_ids": self.cross_debate_ids,
            "knowledge_items": self.knowledge_items,
            "knowledge_sources": self.knowledge_sources,
            "document_items": self.document_items,
            "evidence_items": self.evidence_items,
            "context_envelope": self.context_envelope,
            "total_context_tokens": self.total_context_tokens,
            "retrieval_time_ms": self.retrieval_time_ms,
        }


@dataclass
class DecisionIntegrityPackage:
    """Bundle of artifacts for decision implementation."""

    debate_id: str
    receipt: DecisionReceipt | None
    plan: ImplementPlan | None
    context_snapshot: ContextSnapshot | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "debate_id": self.debate_id,
            "receipt": self.receipt.to_dict() if self.receipt else None,
            "plan": self.plan.to_dict() if self.plan else None,
            "context_snapshot": self.context_snapshot.to_dict() if self.context_snapshot else None,
        }


def _coerce_debate_result(debate: dict[str, Any]) -> DebateResult:
    """Best-effort conversion from stored debate dict to DebateResult."""
    agents = debate.get("agents", []) or []
    if isinstance(agents, str):
        agents = [a.strip() for a in agents.split(",") if a.strip()]

    return DebateResult(
        debate_id=str(debate.get("debate_id") or debate.get("id") or ""),
        task=str(debate.get("task") or debate.get("question") or ""),
        final_answer=str(debate.get("final_answer") or debate.get("conclusion") or ""),
        confidence=float(debate.get("confidence") or 0.0),
        consensus_reached=bool(debate.get("consensus_reached") or False),
        rounds_used=int(debate.get("rounds_used") or debate.get("rounds") or 0),
        rounds_completed=int(debate.get("rounds_completed") or 0),
        status=str(debate.get("status") or ""),
        participants=list(agents),
        metadata=dict(debate.get("metadata") or {}),
    )


def coerce_debate_result(debate: dict[str, Any]) -> DebateResult:
    """Public helper to coerce a stored debate dictionary into a DebateResult."""
    return _coerce_debate_result(debate)


async def capture_context_snapshot(
    task: str,
    *,
    continuum_memory: Any = None,
    cross_debate_memory: Any = None,
    knowledge_mound: Any = None,
    document_store: Any = None,
    evidence_store: Any = None,
    debate_id: str | None = None,
    max_entries: int = 10,
    max_tokens: int = 2000,
    auth_context: Any = None,
    context_envelope: dict[str, Any] | None = None,
    document_org_id: str | None = None,
) -> ContextSnapshot:
    """Capture a snapshot of all available memory/knowledge context.

    Queries Continuum Memory, Cross-Debate Memory, and Knowledge Mound
    to produce an auditable record of what context was available when a
    decision was made.

    Args:
        task: The debate task/question used as the query.
        continuum_memory: Optional ContinuumMemory instance.
        cross_debate_memory: Optional CrossDebateMemory instance.
        knowledge_mound: Optional KnowledgeMound instance.
        max_entries: Max entries to retrieve from each source.
        max_tokens: Max tokens for cross-debate context.
        document_org_id: Org whose documents are listed; defaults to the
            ``auth_context`` org. Without an org no documents are listed.
    """
    start = time.monotonic()
    snapshot = ContextSnapshot()

    filter_entries: Any = None
    resolve_tenant_id: Any = None
    tenant_enforcement_enabled: Any = None
    has_memory_read_access: Any = None
    build_access_envelope: Any = None
    emit_denial_telemetry: Any = None
    tenant_id: str | None = None
    enforce_tenant = False

    try:
        from aragora.memory.access import (  # type: ignore[no-redef]
            build_access_envelope,
            emit_denial_telemetry,
            filter_entries,
            has_memory_read_access,
            resolve_tenant_id,
            tenant_enforcement_enabled,
        )
    except (ImportError, AttributeError):
        logger.debug("RBAC access tracking unavailable")

    if context_envelope is not None:
        snapshot.context_envelope = dict(context_envelope)
    elif build_access_envelope is not None:
        snapshot.context_envelope = build_access_envelope(
            auth_context,
            source="pipeline.decision_integrity.context",
        )

    if resolve_tenant_id is not None:
        tenant_id = resolve_tenant_id(auth_context)
    if tenant_enforcement_enabled is not None and auth_context is not None:
        enforce_tenant = tenant_enforcement_enabled()

    memory_access_allowed = True
    if (
        auth_context is not None
        and has_memory_read_access is not None
        and not has_memory_read_access(auth_context)
    ):
        memory_access_allowed = False
        if emit_denial_telemetry is not None:
            emit_denial_telemetry(
                "pipeline.decision_integrity.context",
                auth_context,
                "missing_memory_read_permission",
            )

    # 1. Continuum Memory (slow + glacial tiers for institutional memory)
    if continuum_memory is not None and memory_access_allowed:
        try:
            from aragora.memory.tier_manager import MemoryTier

            retrieve_kwargs: dict[str, Any] = {
                "query": task,
                "tiers": [MemoryTier.SLOW, MemoryTier.GLACIAL],
                "limit": max_entries,
                "min_importance": 0.3,
            }
            if tenant_id is not None:
                retrieve_kwargs["tenant_id"] = tenant_id
            if enforce_tenant:
                retrieve_kwargs["enforce_tenant_isolation"] = True

            try:
                entries = continuum_memory.retrieve(**retrieve_kwargs)
            except TypeError:
                # Backward-compatible fallback for memory backends that do not
                # support scoped retrieval kwargs yet.
                retrieve_kwargs.pop("tenant_id", None)
                retrieve_kwargs.pop("enforce_tenant_isolation", None)
                entries = continuum_memory.retrieve(**retrieve_kwargs)

            if filter_entries is not None and auth_context is not None:
                entries = filter_entries(
                    entries,
                    auth_context,
                    source="pipeline.decision_integrity.continuum",
                )

            snapshot.continuum_entries = [
                asdict(e) if hasattr(e, "__dataclass_fields__") else {"content": str(e)}
                for e in entries
            ]
        except (TypeError, KeyError, ValueError, OSError, ConnectionError, RuntimeError) as exc:
            logger.debug("Continuum memory retrieval failed: %s", exc)

    # 2. Cross-Debate Memory
    if cross_debate_memory is not None and memory_access_allowed:
        try:
            context = await cross_debate_memory.get_relevant_context(
                task=task,
                max_tokens=max_tokens,
            )
            snapshot.cross_debate_context = context or ""
            # Try to extract referenced debate IDs from the memory store
            if hasattr(cross_debate_memory, "_entries"):
                task_lower = task.lower()
                snapshot.cross_debate_ids = [
                    eid
                    for eid, entry in list(cross_debate_memory._entries.items())[:50]
                    if hasattr(entry, "task") and task_lower in str(entry.task).lower()
                ][:5]
        except (TypeError, KeyError, ValueError, OSError, ConnectionError, RuntimeError) as exc:
            logger.debug("Cross-debate memory retrieval failed: %s", exc)

    # 3. Knowledge Mound
    if knowledge_mound is not None:
        try:
            query_kwargs: dict[str, Any] = {
                "query": task,
                "limit": max_entries,
            }
            if tenant_id:
                query_kwargs["workspace_id"] = tenant_id
            try:
                result = await knowledge_mound.query(**query_kwargs)
            except TypeError:
                query_kwargs.pop("workspace_id", None)
                result = await knowledge_mound.query(**query_kwargs)
            if hasattr(result, "items"):
                snapshot.knowledge_items = [
                    item.to_dict() if hasattr(item, "to_dict") else {"content": str(item)}
                    for item in result.items
                ]
            if hasattr(result, "sources"):
                snapshot.knowledge_sources = [
                    s.value if hasattr(s, "value") else str(s) for s in result.sources
                ]
        except (TypeError, KeyError, ValueError, OSError, ConnectionError, RuntimeError) as exc:
            logger.debug("Knowledge Mound query failed: %s", exc)

    # 4. Document store (uploaded documents of the debate's org only)
    doc_org = document_org_id or getattr(auth_context, "org_id", None)
    if document_store is not None and isinstance(doc_org, str) and doc_org:
        try:
            items = document_store.list_for_org(doc_org)
            if isinstance(items, list):
                snapshot.document_items = items[:max_entries]
        except (AttributeError, TypeError, OSError, ConnectionError, RuntimeError) as exc:
            logger.debug("Document store listing failed: %s", exc)

    # 5. Evidence store (debate-linked evidence)
    if evidence_store is not None:
        try:
            if debate_id:
                evidence = evidence_store.get_debate_evidence(debate_id)
            else:
                evidence = evidence_store.search_evidence(task, limit=max_entries)
            if isinstance(evidence, list):
                snapshot.evidence_items = evidence[:max_entries]
        except (AttributeError, TypeError, KeyError, OSError, ConnectionError, RuntimeError) as exc:
            logger.debug("Evidence store retrieval failed: %s", exc)

    # Estimate token count
    token_count = 0
    for e in snapshot.continuum_entries:
        token_count += len(str(e.get("content", ""))) // 4
    token_count += len(snapshot.cross_debate_context) // 4
    for item in snapshot.knowledge_items:
        token_count += len(str(item.get("content", ""))) // 4
    for item in snapshot.document_items:
        token_count += len(str(item.get("preview", ""))) // 4
    for item in snapshot.evidence_items:
        token_count += len(str(item.get("snippet", ""))) // 4
    snapshot.total_context_tokens = token_count
    snapshot.retrieval_time_ms = (time.monotonic() - start) * 1000

    return snapshot


def _build_cost_summary_for_receipt(
    debate_result: DebateResult,
) -> dict[str, Any] | None:
    """Build a cost_summary dict for DecisionReceipt from DebateResult fields.

    Tries the DebateCostTracker singleton first for rich per-agent/per-round
    breakdowns.  Falls back to the lightweight fields already on DebateResult
    (total_cost_usd, per_agent_cost).

    Returns None when no cost data is available.
    """
    debate_id = debate_result.debate_id or ""

    # Try DebateCostTracker for rich summary
    try:
        from aragora.billing.debate_costs import get_debate_cost_tracker

        dct = get_debate_cost_tracker()
        summary = dct.get_debate_cost(debate_id)
        if summary and summary.total_calls > 0:
            return summary.to_dict()
    except (ImportError, RuntimeError, ValueError, TypeError, AttributeError) as exc:
        logger.debug("DebateCostTracker unavailable, falling back to DebateResult fields: %s", exc)

    # Fallback: build minimal summary from DebateResult fields
    if debate_result.total_cost_usd > 0 or debate_result.per_agent_cost:
        return {
            "debate_id": debate_id,
            "total_cost_usd": str(debate_result.total_cost_usd),
            "per_agent": {
                name: {"total_cost_usd": str(cost)}
                for name, cost in debate_result.per_agent_cost.items()
            },
            "total_tokens_in": 0,
            "total_tokens_out": 0,
            "total_calls": 0,
        }

    return None


def build_integrity_package_from_result(
    debate_result: DebateResult,
    *,
    include_receipt: bool = True,
    include_plan: bool = True,
    plan_strategy: str = "single_task",
    repo_path: Path | None = None,
) -> DecisionIntegrityPackage:
    """Build a DecisionIntegrityPackage directly from a DebateResult.

    Synchronous adapter for use in PostDebateCoordinator where the
    DebateResult is already available (no dict coercion needed).

    Args:
        debate_result: A DebateResult from a completed debate.
        include_receipt: Whether to generate a DecisionReceipt.
        include_plan: Whether to generate an implementation plan.
        plan_strategy: "single_task" (default).
        repo_path: Repository root (defaults to cwd).
    """
    receipt = None
    if include_receipt:
        cost_summary = _build_cost_summary_for_receipt(debate_result)
        receipt = DecisionReceipt.from_debate_result(debate_result, cost_summary=cost_summary)

    plan: ImplementPlan | None = None
    if include_plan:
        repo_root = repo_path or Path.cwd()
        design = debate_result.final_answer or debate_result.task
        plan = create_single_task_plan(design=design, repo_path=repo_root)

    return DecisionIntegrityPackage(
        debate_id=debate_result.debate_id or "",
        receipt=receipt,
        plan=plan,
    )


async def build_decision_integrity_package(
    debate: dict[str, Any],
    *,
    include_receipt: bool = True,
    include_plan: bool = True,
    include_context: bool = False,
    plan_strategy: str = "single_task",
    repo_path: Path | None = None,
    continuum_memory: Any = None,
    cross_debate_memory: Any = None,
    knowledge_mound: Any = None,
    document_store: Any = None,
    evidence_store: Any = None,
    auth_context: Any = None,
    context_envelope: dict[str, Any] | None = None,
    document_org_id: str | None = None,
) -> DecisionIntegrityPackage:
    """Build a Decision Integrity package from a debate payload.

    Args:
        debate: Debate payload (dict) from storage.
        include_receipt: Whether to generate a DecisionReceipt.
        include_plan: Whether to generate an implementation plan.
        include_context: Whether to capture a context snapshot.
        plan_strategy: "single_task" (default) or "gemini" (best-effort).
        repo_path: Repository root (defaults to cwd).
        continuum_memory: Optional ContinuumMemory for context snapshot.
        cross_debate_memory: Optional CrossDebateMemory for context snapshot.
        knowledge_mound: Optional KnowledgeMound for context snapshot.
        document_store: Optional DocumentStore for context snapshot.
        evidence_store: Optional EvidenceStore for context snapshot.
        document_org_id: Org whose documents the snapshot may list (see
            :func:`capture_context_snapshot`).
    """
    debate_result = _coerce_debate_result(debate)
    receipt = None
    if include_receipt:
        cost_summary = _build_cost_summary_for_receipt(debate_result)
        receipt = DecisionReceipt.from_debate_result(debate_result, cost_summary=cost_summary)

    plan: ImplementPlan | None = None
    if include_plan:
        repo_root = repo_path or Path.cwd()
        design = debate_result.final_answer or debate_result.task
        if plan_strategy == "gemini":
            try:
                plan = await generate_implement_plan(design=design, repo_path=repo_root)
            except (OSError, ValueError, RuntimeError):
                plan = create_single_task_plan(design=design, repo_path=repo_root)
        else:
            plan = create_single_task_plan(design=design, repo_path=repo_root)

    context_snapshot: ContextSnapshot | None = None
    if include_context:
        context_snapshot = await capture_context_snapshot(
            task=debate_result.task,
            continuum_memory=continuum_memory,
            cross_debate_memory=cross_debate_memory,
            knowledge_mound=knowledge_mound,
            document_store=document_store,
            evidence_store=evidence_store,
            debate_id=debate_result.debate_id,
            auth_context=auth_context,
            context_envelope=context_envelope,
            document_org_id=document_org_id,
        )

    return DecisionIntegrityPackage(
        debate_id=debate_result.debate_id or str(debate.get("id") or ""),
        receipt=receipt,
        plan=plan,
        context_snapshot=context_snapshot,
    )


class DecisionContextPreloader:
    """Loads relevant context BEFORE a debate starts for kernel unification.

    Queries available subsystems (knowledge bridge, continuum memory,
    calibration/ELO) to build a pre-debate context dict.  Each subsystem
    is optional -- missing ones return empty results and failures degrade
    gracefully.
    """

    def __init__(
        self,
        knowledge_bridge: Any = None,
        memory: Any = None,
        calibration: Any = None,
    ) -> None:
        self._knowledge_bridge = knowledge_bridge
        self._memory = memory
        self._calibration = calibration

    def preload(self, task: str, domain: str | None = None) -> dict[str, Any]:
        """Build pre-debate context from available subsystems.

        Args:
            task: The debate task/question used as the query.
            domain: Optional domain hint for calibration lookup.

        Returns:
            Dict with keys ``precedents``, ``relevant_knowledge``, and
            ``agent_calibration``.  Each subsystem is optional -- missing
            ones return empty results.
        """
        ctx: dict[str, Any] = {
            "precedents": [],
            "relevant_knowledge": [],
            "agent_calibration": {},
        }

        # 1. Query knowledge bridge for precedents (PipelineBridge.query_precedents)
        if self._knowledge_bridge is not None:
            try:
                result = self._knowledge_bridge.query_precedents(task, limit=5)
                # Handle both sync and awaitable returns gracefully
                if isinstance(result, list):
                    ctx["precedents"] = result
            except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
                logger.debug("Knowledge bridge precedent query failed: %s", exc)

        # 2. Query continuum memory for patterns (ContinuumMemory.retrieve)
        if self._memory is not None:
            try:
                entries = self._memory.retrieve(query=task, limit=10)
                ctx["relevant_knowledge"] = [
                    entry.to_dict() if hasattr(entry, "to_dict") else {"content": str(entry)}
                    for entry in entries
                ]
            except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
                logger.debug("Memory retrieval for pre-debate context failed: %s", exc)

        # 3. Load agent calibration for domain (EloSystem.get_leaderboard / get_domain_calibration)
        if self._calibration is not None and domain:
            try:
                agents = self._calibration.get_top_agents_for_domain(domain, limit=5)
                ctx["agent_calibration"] = {
                    getattr(a, "agent_name", str(a)): getattr(a, "elo", 0.0) for a in agents
                }
            except (AttributeError, TypeError, ValueError, OSError, RuntimeError) as exc:
                logger.debug("Calibration lookup for domain %r failed: %s", domain, exc)

        return ctx
