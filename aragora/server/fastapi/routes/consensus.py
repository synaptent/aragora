"""
Consensus Memory Endpoints (FastAPI v2).

Migrated from: aragora/server/handlers/consensus.py (aiohttp handler)

Provides async consensus memory endpoints with Pydantic validation:
- GET  /api/v2/consensus/similar        - Find debates similar to a topic
- GET  /api/v2/consensus/settled         - Get high-confidence settled topics
- GET  /api/v2/consensus/stats           - Get consensus memory statistics
- GET  /api/v2/consensus/dissents        - Get recent dissenting views
- GET  /api/v2/consensus/contrarian-views - Get contrarian perspectives
- GET  /api/v2/consensus/risk-warnings   - Get risk warnings and edge cases
- GET  /api/v2/consensus/domain/{domain} - Get domain-specific history
- GET  /api/v2/consensus/status/{debate_id} - Get consensus status for a debate
- POST /api/v2/consensus/detect          - Detect consensus from proposals

Migration Notes:
    This module replaces the manual path routing, query param extraction,
    and dict-based responses in ConsensusHandler with:
    - FastAPI path/query parameter validation (automatic 422 on bad input)
    - Pydantic response models (auto-generated OpenAPI schema)
    - FastAPI dependency injection for auth and storage
    - Async-native endpoints (no sync-to-async bridging)
    All existing behavior is preserved; response shapes match the legacy
    handler for backward compatibility.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, field_validator

from ..dependencies.auth import require_permission
from ..middleware.error_handling import NotFoundError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/consensus", tags=["Consensus"])

# Safe slug pattern (mirrors aragora.server.validation.entities.SAFE_SLUG_PATTERN)
_SAFE_SLUG_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")


# =============================================================================
# Pydantic Request/Response Models
# =============================================================================


class SimilarDebateItem(BaseModel):
    """A single similar debate result."""

    topic: str
    conclusion: str
    strength: str
    confidence: float
    similarity: float
    agents: list[str] = Field(default_factory=list)
    dissent_count: int = 0
    timestamp: str


class SimilarDebatesResponse(BaseModel):
    """Response for the /similar endpoint."""

    query: str
    similar: list[SimilarDebateItem]
    count: int


class SettledTopic(BaseModel):
    """A single settled consensus topic."""

    topic: str
    conclusion: str
    confidence: float
    strength: str
    timestamp: str


class SettledTopicsResponse(BaseModel):
    """Response for the /settled endpoint."""

    min_confidence: float
    topics: list[SettledTopic]
    count: int


class ConsensusStatsResponse(BaseModel):
    """Response for the /stats endpoint."""

    total_topics: int = 0
    high_confidence_count: int = 0
    domains: list[str] = Field(default_factory=list)
    avg_confidence: float = 0.0
    total_dissents: int = 0
    by_strength: dict[str, Any] = Field(default_factory=dict)
    by_domain: dict[str, Any] = Field(default_factory=dict)


class DissentItem(BaseModel):
    """A single dissent record."""

    topic: str
    majority_view: str
    dissenting_view: str
    dissenting_agent: str
    confidence: float
    reasoning: str | None = None


class DissentsResponse(BaseModel):
    """Response for the /dissents endpoint."""

    dissents: list[DissentItem]


class ContrarianView(BaseModel):
    """A single contrarian view record."""

    agent: str
    position: str
    confidence: float
    reasoning: str
    debate_id: str


class ContrarianViewsResponse(BaseModel):
    """Response for the /contrarian-views endpoint."""

    views: list[ContrarianView]


class RiskWarning(BaseModel):
    """A single risk warning."""

    domain: str
    risk_type: str
    severity: str
    description: str
    mitigation: str | None = None
    detected_at: str


class RiskWarningsResponse(BaseModel):
    """Response for the /risk-warnings endpoint."""

    warnings: list[RiskWarning]


class DomainHistoryResponse(BaseModel):
    """Response for the /domain/{domain} endpoint."""

    domain: str
    history: list[dict[str, Any]]
    count: int


class ConsensusStatusResponse(BaseModel):
    """Response for the /status/{debate_id} endpoint."""

    debate_id: str
    consensus_reached: bool
    confidence: float
    agreement_ratio: float
    has_strong_consensus: bool
    final_claim: str
    supporting_agents: list[str] = Field(default_factory=list)
    dissenting_agents: list[str] = Field(default_factory=list)
    claims_count: int = 0
    dissents_count: int = 0
    unresolved_tensions_count: int = 0
    partial_consensus: dict[str, Any] = Field(default_factory=dict)
    proof: dict[str, Any] = Field(default_factory=dict)
    checksum: str = ""


class DetectProposal(BaseModel):
    """A single proposal for consensus detection."""

    agent: str = "unknown"
    content: str
    round: int = 0

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Proposal content must not be empty")
        return v


class DetectConsensusRequest(BaseModel):
    """Request body for POST /detect."""

    task: str = Field(..., min_length=1, max_length=10000)
    proposals: list[DetectProposal] = Field(..., min_length=1)
    threshold: float = Field(0.7, ge=0.0, le=1.0)


class DetectConsensusResponse(BaseModel):
    """Response for the /detect endpoint."""

    data: dict[str, Any]


# =============================================================================
# Dependencies
# =============================================================================


def _get_consensus_memory():
    """Import and return ConsensusMemory (raises 503 if unavailable)."""
    try:
        from aragora.memory.consensus import ConsensusMemory

        return ConsensusMemory()
    except ImportError:
        raise HTTPException(status_code=503, detail="Consensus memory not available")


def _get_db_connection(db_path: str):
    """Get a database connection (reuse existing utility)."""
    from aragora.server.handlers.utils.database import get_db_connection

    return get_db_connection(db_path)


async def get_storage(request: Request):
    """Dependency to get storage from app state."""
    ctx = getattr(request.app.state, "context", None)
    if not ctx:
        raise HTTPException(status_code=503, detail="Server not initialized")
    storage = ctx.get("storage")
    if not storage:
        raise HTTPException(status_code=503, detail="Storage not available")
    return storage


def _validate_domain(domain: str) -> str:
    """Validate domain slug, raising 400 on invalid input."""
    if not _SAFE_SLUG_RE.match(domain):
        raise HTTPException(status_code=400, detail="Invalid domain format")
    return domain


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/similar", response_model=SimilarDebatesResponse)
async def find_similar_debates(
    topic: str = Query(..., min_length=1, max_length=100_000, description="Topic to search for"),
    limit: int = Query(5, ge=1, le=20, description="Max results to return"),
) -> SimilarDebatesResponse:
    """
    Find debates similar to a topic.

    Searches consensus memory for previously debated topics that are
    semantically similar to the given topic.
    """
    memory = _get_consensus_memory()
    similar = await asyncio.to_thread(memory.find_similar_debates, topic.strip(), limit=limit)
    return SimilarDebatesResponse(
        query=topic,
        similar=[
            SimilarDebateItem(
                topic=s.consensus.topic,
                conclusion=s.consensus.conclusion,
                strength=s.consensus.strength.value,
                confidence=s.consensus.confidence,
                similarity=s.similarity_score,
                agents=s.consensus.participating_agents,
                dissent_count=len(s.dissents),
                timestamp=s.consensus.timestamp.isoformat(),
            )
            for s in similar
        ],
        count=len(similar),
    )


@router.get("/settled", response_model=SettledTopicsResponse)
async def get_settled_topics(
    min_confidence: float = Query(0.8, ge=0.0, le=1.0, description="Minimum confidence threshold"),
    limit: int = Query(20, ge=1, le=100, description="Max results to return"),
) -> SettledTopicsResponse:
    """
    Get high-confidence settled topics.

    Returns consensus topics where confidence meets or exceeds
    the given threshold, ordered by confidence descending.
    """
    memory = _get_consensus_memory()

    def _query_settled():
        with _get_db_connection(memory.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT topic, conclusion, confidence, strength, timestamp
                FROM consensus
                WHERE confidence >= ?
                ORDER BY confidence DESC, timestamp DESC
                LIMIT ?
                """,
                (min_confidence, limit),
            )
            return cursor.fetchall()

    rows = await asyncio.to_thread(_query_settled)

    return SettledTopicsResponse(
        min_confidence=min_confidence,
        topics=[
            SettledTopic(
                topic=row[0],
                conclusion=row[1],
                confidence=row[2],
                strength=row[3],
                timestamp=row[4],
            )
            for row in rows
        ],
        count=len(rows),
    )


@router.get("/stats", response_model=ConsensusStatsResponse)
async def get_consensus_stats() -> ConsensusStatsResponse:
    """
    Get consensus memory statistics.

    Returns aggregate statistics including total topics, average
    confidence, domain breakdown, and strength distribution.
    """
    memory = _get_consensus_memory()
    raw_stats = await asyncio.to_thread(memory.get_statistics)

    def _query_stats():
        with _get_db_connection(memory.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    SUM(CASE WHEN confidence >= 0.7 THEN 1 ELSE 0 END) as high_conf_count,
                    AVG(confidence) as avg_conf
                FROM consensus
                """
            )
            return cursor.fetchone()

    row = await asyncio.to_thread(_query_stats)
    high_confidence_count = row[0] if row and row[0] else 0
    avg_confidence = row[1] if row and row[1] else 0.0

    return ConsensusStatsResponse(
        total_topics=raw_stats.get("total_consensus", 0),
        high_confidence_count=high_confidence_count,
        domains=list(raw_stats.get("by_domain", {}).keys()),
        avg_confidence=round(avg_confidence, 3),
        total_dissents=raw_stats.get("total_dissents", 0),
        by_strength=raw_stats.get("by_strength", {}),
        by_domain=raw_stats.get("by_domain", {}),
    )


@router.get("/dissents", response_model=DissentsResponse)
async def get_recent_dissents(
    topic: str | None = Query(None, max_length=500, description="Filter by topic substring"),
    domain: str | None = Query(None, max_length=100, description="Filter by domain"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
) -> DissentsResponse:
    """
    Get recent dissenting views.

    Returns dissent records, optionally filtered by topic and domain.
    """
    if domain is not None:
        domain = _validate_domain(domain)

    memory = _get_consensus_memory()

    import json as json_mod

    def _query_dissents():
        with _get_db_connection(memory.db_path) as conn:
            cursor = conn.cursor()
            conditions: list[str] = []
            params: list[Any] = []

            if topic:
                conditions.append("c.topic LIKE ?")
                params.append(f"%{topic}%")
            if domain:
                conditions.append("c.domain = ?")
                params.append(domain)

            where_clause = ""
            if conditions:
                where_clause = "WHERE " + " AND ".join(conditions)

            query = f"""
                SELECT d.data, c.topic, c.conclusion
                FROM dissent d
                LEFT JOIN consensus c ON d.debate_id = c.id
                {where_clause}
                ORDER BY d.timestamp DESC
                LIMIT ?
            """  # dynamic clause from internal state
            params.append(limit)
            cursor.execute(query, tuple(params))
            return cursor.fetchall()

    rows = await asyncio.to_thread(_query_dissents)

    dissents = []
    for row in rows:
        try:
            from aragora.memory.consensus import DissentRecord

            record = DissentRecord.from_dict(json_mod.loads(row[0]))
            topic_name = row[1] or "Unknown topic"
            majority_view = row[2] or "No consensus recorded"

            dissents.append(
                DissentItem(
                    topic=topic_name,
                    majority_view=majority_view,
                    dissenting_view=record.content,
                    dissenting_agent=record.agent_id,
                    confidence=record.confidence,
                    reasoning=record.reasoning if record.reasoning else None,
                )
            )
        except (json_mod.JSONDecodeError, ValueError, KeyError, TypeError) as e:
            logger.debug("Failed to parse dissent record: %s", e)

    return DissentsResponse(dissents=dissents)


@router.get("/contrarian-views", response_model=ContrarianViewsResponse)
async def get_contrarian_views(
    topic: str | None = Query(None, max_length=500, description="Filter by topic"),
    domain: str | None = Query(None, max_length=100, description="Filter by domain"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
) -> ContrarianViewsResponse:
    """
    Get historical contrarian/dissenting views.

    Returns perspectives that challenged majority consensus, optionally
    filtered by topic and domain.
    """
    if domain is not None:
        domain = _validate_domain(domain)

    memory = _get_consensus_memory()

    import json as json_mod

    try:
        from aragora.memory.consensus import DissentRetriever
    except ImportError:
        DissentRetriever = None  # type: ignore[assignment,misc]

    if topic and DissentRetriever is not None:
        try:
            retriever = DissentRetriever(memory)
            records = await asyncio.to_thread(
                retriever.find_contrarian_views, topic, domain=domain, limit=limit
            )
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("DissentRetriever.find_contrarian_views failed: %s", e)
            records = []
    else:

        def _query_contrarian():
            with _get_db_connection(memory.db_path) as conn:
                cursor = conn.cursor()
                query = """
                    SELECT data FROM dissent
                    WHERE dissent_type IN ('fundamental_disagreement', 'alternative_approach')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                return cursor.fetchall()

        rows = await asyncio.to_thread(_query_contrarian)

        records = []
        for row in rows:
            try:
                from aragora.memory.consensus import DissentRecord

                records.append(DissentRecord.from_dict(json_mod.loads(row[0])))
            except (json_mod.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                logger.debug("Failed to parse contrarian view record: %s", e)

    return ContrarianViewsResponse(
        views=[
            ContrarianView(
                agent=r.agent_id or "unknown",
                position=r.content or "",
                confidence=r.confidence if r.confidence is not None else 0.0,
                reasoning=r.reasoning or "",
                debate_id=r.debate_id or "",
            )
            for r in records
        ]
    )


@router.get("/risk-warnings", response_model=RiskWarningsResponse)
async def get_risk_warnings(
    topic: str | None = Query(None, max_length=500, description="Filter by topic"),
    domain: str | None = Query(None, max_length=100, description="Filter by domain"),
    limit: int = Query(10, ge=1, le=50, description="Max results to return"),
) -> RiskWarningsResponse:
    """
    Get risk warnings and edge case concerns.

    Returns risk-related dissent records, optionally filtered
    by topic and domain.
    """
    if domain is not None:
        domain = _validate_domain(domain)

    memory = _get_consensus_memory()

    import json as json_mod

    try:
        from aragora.memory.consensus import DissentRetriever
    except ImportError:
        DissentRetriever = None  # type: ignore[assignment,misc]

    if topic and DissentRetriever is not None:
        try:
            retriever = DissentRetriever(memory)
            records = await asyncio.to_thread(
                retriever.find_risk_warnings, topic, domain=domain, limit=limit
            )
        except (KeyError, ValueError, OSError, TypeError) as e:
            logger.warning("DissentRetriever.find_risk_warnings failed: %s", e)
            records = []
    else:

        def _query_risk_warnings():
            with _get_db_connection(memory.db_path) as conn:
                cursor = conn.cursor()
                query = """
                    SELECT data FROM dissent
                    WHERE dissent_type IN ('risk_warning', 'edge_case_concern')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                return cursor.fetchall()

        rows = await asyncio.to_thread(_query_risk_warnings)

        records = []
        for row in rows:
            try:
                from aragora.memory.consensus import DissentRecord

                records.append(DissentRecord.from_dict(json_mod.loads(row[0])))
            except (json_mod.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                logger.debug("Failed to parse risk warning record: %s", e)

    def _safe_dissent_type_str(dt: Any) -> str:
        if dt is None:
            return "unknown"
        if hasattr(dt, "value"):
            return dt.value
        return str(dt)

    def _safe_timestamp_str(ts: Any) -> str:
        if ts is None:
            return datetime.now().isoformat()
        if hasattr(ts, "isoformat"):
            return ts.isoformat()
        return str(ts)

    def _infer_severity(confidence: float, dissent_type: str) -> str:
        if dissent_type == "risk_warning":
            if confidence >= 0.8:
                return "critical"
            elif confidence >= 0.6:
                return "high"
            elif confidence >= 0.4:
                return "medium"
        return "low"

    return RiskWarningsResponse(
        warnings=[
            RiskWarning(
                domain=(r.metadata or {}).get("domain", "general"),
                risk_type=_safe_dissent_type_str(r.dissent_type).replace("_", " ").title(),
                severity=_infer_severity(r.confidence, _safe_dissent_type_str(r.dissent_type)),
                description=r.content or "",
                mitigation=r.rebuttal if r.rebuttal else None,
                detected_at=_safe_timestamp_str(r.timestamp),
            )
            for r in records
        ]
    )


@router.get("/domain/{domain}", response_model=DomainHistoryResponse)
async def get_domain_history(
    domain: str,
    limit: int = Query(50, ge=1, le=200, description="Max results to return"),
) -> DomainHistoryResponse:
    """
    Get consensus history for a specific domain.

    Returns all consensus records for the given domain, ordered
    by recency.
    """
    domain = _validate_domain(domain)
    memory = _get_consensus_memory()
    records = await asyncio.to_thread(memory.get_domain_consensus_history, domain, limit=limit)
    return DomainHistoryResponse(
        domain=domain,
        history=[r.to_dict() for r in records],
        count=len(records),
    )


@router.get("/status/{debate_id}", response_model=ConsensusStatusResponse)
async def get_consensus_status(
    debate_id: str,
    storage=Depends(get_storage),
) -> ConsensusStatusResponse:
    """
    Get consensus status for an existing debate.

    Looks up the debate in storage, builds a ConsensusProof from
    the result, and returns the consensus analysis.
    """
    try:
        if inspect.iscoroutinefunction(getattr(storage, "get_debate", None)):
            debate_result = await storage.get_debate(debate_id)
        else:
            debate_result = await asyncio.to_thread(storage.get_debate, debate_id)
    except (KeyError, ValueError, OSError) as e:
        logger.debug("Failed to retrieve debate %s: %s", debate_id, e)
        debate_result = None

    if debate_result is None:
        raise NotFoundError(f"Debate not found: {debate_id}")

    try:
        from aragora.debate.consensus import ConsensusBuilder, build_partial_consensus

        builder = ConsensusBuilder.from_debate_result(debate_result)

        final_answer = getattr(debate_result, "final_answer", "")
        confidence = getattr(debate_result, "confidence", 0.0)
        consensus_reached = getattr(debate_result, "consensus_reached", False)

        proof = builder.build(
            final_claim=final_answer[:500] if final_answer else "",
            confidence=confidence,
            consensus_reached=consensus_reached,
            reasoning_summary=(
                f"Debate {'reached' if consensus_reached else 'did not reach'} consensus "
                f"with {confidence:.0%} confidence."
            ),
            rounds=getattr(debate_result, "rounds_completed", 0),
        )

        partial = build_partial_consensus(debate_result)

        return ConsensusStatusResponse(
            debate_id=debate_id,
            consensus_reached=consensus_reached,
            confidence=round(confidence, 4),
            agreement_ratio=round(proof.agreement_ratio, 4),
            has_strong_consensus=proof.has_strong_consensus,
            final_claim=proof.final_claim,
            supporting_agents=proof.supporting_agents,
            dissenting_agents=proof.dissenting_agents,
            claims_count=len(proof.claims),
            dissents_count=len(proof.dissents),
            unresolved_tensions_count=len(proof.unresolved_tensions),
            partial_consensus=partial.to_dict(),
            proof=proof.to_dict(),
            checksum=proof.checksum,
        )

    except ImportError:
        raise HTTPException(status_code=503, detail="Consensus detection module not available")


@router.post(
    "/detect",
    response_model=DetectConsensusResponse,
)
async def detect_consensus(
    body: DetectConsensusRequest,
    auth=Depends(require_permission("consensus:write")),
) -> DetectConsensusResponse:
    """
    Detect consensus from provided proposals.

    Accepts a list of proposals and analyzes them for consensus using
    keyword overlap analysis and the ConsensusBuilder.

    Requires `consensus:write` permission.
    """
    try:
        from aragora.debate.consensus import ConsensusBuilder, VoteType

        debate_id = "detect-" + hashlib.sha256(body.task.encode()).hexdigest()[:12]
        builder = ConsensusBuilder(debate_id=debate_id, task=body.task)

        # Process proposals into claims and evidence
        for proposal in body.proposals:
            if not proposal.content:
                continue

            claim = builder.add_claim(
                statement=proposal.content[:500],
                author=proposal.agent,
                confidence=0.6,
                round_num=proposal.round,
            )
            builder.add_evidence(
                claim_id=claim.claim_id,
                source=proposal.agent,
                content=proposal.content,
                evidence_type="argument",
                supports=True,
                strength=0.6,
            )

        # Analyze cross-proposal agreement
        agents = list({p.agent for p in body.proposals if p.content})
        total_agents = len(agents) if agents else 1

        contents = [p.content for p in body.proposals if p.content]
        if len(contents) >= 2:
            agreement_scores = []
            for i in range(len(contents)):
                for j in range(i + 1, len(contents)):
                    words_a = {w.lower() for w in contents[i].split() if len(w) > 4}
                    words_b = {w.lower() for w in contents[j].split() if len(w) > 4}
                    if words_a and words_b:
                        overlap = len(words_a & words_b)
                        union = len(words_a | words_b)
                        agreement_scores.append(overlap / union if union else 0.0)
            avg_agreement = (
                sum(agreement_scores) / len(agreement_scores) if agreement_scores else 0.0
            )
        else:
            avg_agreement = 1.0

        confidence = min(avg_agreement * 1.2, 1.0)
        consensus_reached = confidence >= body.threshold

        # Record votes
        for agent in agents:
            vote_type = VoteType.AGREE if consensus_reached else VoteType.CONDITIONAL
            builder.record_vote(
                agent=agent,
                vote=vote_type,
                confidence=confidence,
                reasoning=("Agreed with consensus" if consensus_reached else "Partial agreement"),
            )

        final_claim = contents[0][:500] if contents else body.task
        reasoning_summary = (
            f"Analyzed {len(body.proposals)} proposals from {total_agents} agents. "
            f"Average keyword agreement: {avg_agreement:.0%}. "
            f"{'Consensus reached' if consensus_reached else 'Consensus not reached'} "
            f"(threshold: {body.threshold:.0%})."
        )

        proof = builder.build(
            final_claim=final_claim,
            confidence=confidence,
            consensus_reached=consensus_reached,
            reasoning_summary=reasoning_summary,
            rounds=max((p.round for p in body.proposals), default=0),
        )

        return DetectConsensusResponse(
            data={
                "debate_id": debate_id,
                "consensus_reached": consensus_reached,
                "confidence": round(confidence, 4),
                "threshold": body.threshold,
                "agreement_ratio": round(proof.agreement_ratio, 4),
                "has_strong_consensus": proof.has_strong_consensus,
                "final_claim": proof.final_claim,
                "reasoning_summary": proof.reasoning_summary,
                "supporting_agents": proof.supporting_agents,
                "dissenting_agents": proof.dissenting_agents,
                "claims_count": len(proof.claims),
                "evidence_count": len(proof.evidence_chain),
                "unresolved_tensions_count": len(proof.unresolved_tensions),
                "proof": proof.to_dict(),
                "checksum": proof.checksum,
            }
        )

    except ImportError:
        raise HTTPException(status_code=503, detail="Consensus detection module not available")
