"""
Consensus Memory endpoint handlers.

Endpoints:
- GET /api/consensus/similar - Find debates similar to a topic
- GET /api/consensus/settled - Get high-confidence settled topics
- GET /api/consensus/stats - Get consensus memory statistics
- GET /api/consensus/dissents - Get recent dissenting views
- GET /api/consensus/contrarian-views - Get contrarian perspectives
- GET /api/consensus/risk-warnings - Get risk warnings and edge cases
- GET /api/consensus/domain/:domain - Get domain-specific history
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from aragora.config import (
    CACHE_TTL_CONSENSUS_SETTLED,
    CACHE_TTL_CONSENSUS_SIMILAR,
    CACHE_TTL_CONSENSUS_STATS,
    CACHE_TTL_CONTRARIAN_VIEWS,
    CACHE_TTL_RECENT_DISSENTS,
    CACHE_TTL_RISK_WARNINGS,
)
from aragora.server.validation.entities import SAFE_SLUG_PATTERN
from aragora.server.versioning.compat import strip_version_prefix

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_bounded_float_param,
    get_bounded_string_param,
    get_clamped_int_param,
    get_db_connection,
    handle_errors,
    json_response,
    require_feature,
    safe_error_message,
    ttl_cache,
)
from aragora.billing.auth import extract_user_from_request
from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext
from ..utils.rate_limit import RateLimiter, get_client_ip

# Rate limiter for consensus endpoints (30 requests per minute)
_consensus_limiter = RateLimiter(requests_per_minute=30)
from aragora.utils.optional_imports import try_import

logger = logging.getLogger(__name__)

# Lazy imports for optional dependencies using centralized utility
_consensus_imports, CONSENSUS_MEMORY_AVAILABLE = try_import(
    "aragora.memory.consensus", "ConsensusMemory", "DissentRetriever"
)
ConsensusMemory = _consensus_imports["ConsensusMemory"]
DissentRetriever = _consensus_imports["DissentRetriever"]


class ConsensusHandler(BaseHandler):
    """Handler for consensus memory endpoints."""

    def __init__(self, ctx: dict | None = None):
        """Initialize handler with optional context."""
        self.ctx = ctx or {}

    ROUTES = [
        "/api/consensus",
        "/api/consensus/similar",
        "/api/consensus/settled",
        "/api/consensus/stats",
        "/api/consensus/dissents",
        "/api/consensus/contrarian-views",
        "/api/consensus/risk-warnings",
        "/api/consensus/seed-demo",
        "/api/consensus/detect",
        "/api/consensus/domain/*",
        "/api/v1/consensus/domain",
    ]

    def can_handle(self, path: str, method: str = "GET") -> bool:
        """Check if this handler can process the given path."""
        path = strip_version_prefix(path)
        if path in self.ROUTES:
            return True
        # Handle /api/consensus/domain/:domain pattern
        if path.startswith("/api/consensus/domain/"):
            return True
        # Handle /api/consensus/status/:debate_id pattern
        if path.startswith("/api/consensus/status/"):
            return True
        return False

    def _check_memory_permission(
        self, handler: Any, user: Any, action: str = "read"
    ) -> HandlerResult | None:
        """Check RBAC permission for memory operations."""
        permission = f"memory.{action}"
        try:
            # Handle both UserAuthContext objects and dicts
            if hasattr(user, "user_id"):
                user_id = str(user.user_id) if user.user_id else "unknown"
            elif hasattr(user, "id"):
                user_id = str(user.id) if user.id else "unknown"
            elif isinstance(user, dict):
                user_id = str(user.get("id", "unknown"))
            else:
                user_id = "unknown"

            if hasattr(user, "org_id"):
                org_id = user.org_id
            elif isinstance(user, dict):
                org_id = user.get("org_id")
            else:
                org_id = None

            # UserAuthContext has 'role' (singular), dicts may have 'roles' (plural)
            if hasattr(user, "roles"):
                roles = set(user.roles)
            elif hasattr(user, "role"):
                roles = {user.role} if user.role else {"member"}
            elif isinstance(user, dict):
                roles = set(user.get("roles", ["member"]))
            else:
                roles = {"member"}

            context = AuthorizationContext(
                user_id=user_id,
                org_id=org_id,
                roles=roles,
                permissions=set(),
            )
            checker = get_permission_checker()
            decision = checker.check_permission(context, permission)
            if not decision.allowed:
                logger.warning(
                    "RBAC denied %s for user %s: %s", permission, user_id, decision.reason
                )
                return error_response("Permission denied", 403)
            return None
        except (TypeError, ValueError, KeyError, AttributeError) as e:
            logger.error("RBAC check failed: %s", e)
            return error_response("Authorization check failed", 500)

    @staticmethod
    def _validate_domain(domain: str | None) -> tuple[str | None, HandlerResult | None]:
        """Validate domain parameter against safe slug pattern.

        Returns (validated_domain, error_response) tuple.
        If domain is None, returns (None, None).
        If domain fails validation, returns (None, error_response).
        """
        if domain is None:
            return None, None
        if not SAFE_SLUG_PATTERN.match(domain):
            return None, error_response("Invalid domain format", 400)
        return domain, None

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route consensus requests to appropriate methods."""
        path = strip_version_prefix(path)
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _consensus_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for consensus endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Auth: skip for GET (public read-only dashboard data), require for mutations
        method = getattr(handler, "command", "GET") if handler else "GET"
        if method != "GET" or path == "/api/consensus/seed-demo":
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
            if path == "/api/consensus/seed-demo":
                _, perm_err = self.require_permission_or_error(handler, "consensus:write")
                if perm_err:
                    return perm_err
                rbac_err = self._check_memory_permission(handler, user, "update")
                if rbac_err:
                    return rbac_err

        if path == "/api/consensus":
            return self._get_consensus_stats()

        if path == "/api/consensus/similar":
            # Validate raw topic length before truncation
            raw_topic = query_params.get("topic", "")
            if isinstance(raw_topic, list):
                raw_topic = raw_topic[0] if raw_topic else ""
            if len(raw_topic) > 100_000:
                return error_response("Topic too long (max 100000 chars)", 400)
            topic = get_bounded_string_param(query_params, "topic", "", max_length=100_000)
            if not topic:
                return error_response("Topic required", 400)
            limit = get_clamped_int_param(query_params, "limit", 5, min_val=1, max_val=20)
            return self._get_similar_debates(topic.strip(), limit)

        if path == "/api/consensus/settled":
            min_confidence = get_bounded_float_param(
                query_params, "min_confidence", 0.8, min_val=0.0, max_val=1.0
            )
            limit = get_clamped_int_param(query_params, "limit", 20, min_val=1, max_val=100)
            return self._get_settled_topics(min_confidence, limit)

        if path == "/api/consensus/stats":
            return self._get_consensus_stats()

        if path == "/api/consensus/dissents":
            topic = get_bounded_string_param(query_params, "topic", "", max_length=500)
            domain = get_bounded_string_param(query_params, "domain", None, max_length=100)
            limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
            return self._get_recent_dissents(topic.strip() if topic else None, domain, limit)

        if path == "/api/consensus/contrarian-views":
            topic = get_bounded_string_param(query_params, "topic", "", max_length=500)
            domain = get_bounded_string_param(query_params, "domain", None, max_length=100)
            limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
            return self._get_contrarian_views(topic.strip() if topic else None, domain, limit)

        if path == "/api/consensus/risk-warnings":
            topic = get_bounded_string_param(query_params, "topic", "", max_length=500)
            domain = get_bounded_string_param(query_params, "domain", None, max_length=100)
            limit = get_clamped_int_param(query_params, "limit", 10, min_val=1, max_val=50)
            return self._get_risk_warnings(topic.strip() if topic else None, domain, limit)

        if path == "/api/consensus/seed-demo":
            # Require authentication for seed-demo (mutating operation)
            user_ctx = extract_user_from_request(handler, self.ctx.get("user_store"))
            if not user_ctx.authenticated:
                return error_response("Authentication required", 401)
            return self._seed_demo_data()

        if path.startswith("/api/consensus/status/"):
            # Path stripped: /api/consensus/status/{debate_id} -> index 4
            debate_id, err = self.extract_path_param(path, 4, "debate_id")
            if err:
                return err
            return self._get_consensus_status(debate_id)

        if path.startswith("/api/consensus/domain/"):
            # Path stripped: api/consensus/domain/{domain} -> index 4
            domain, err = self.extract_path_param(path, 4, "domain")
            if err:
                return err
            limit = get_clamped_int_param(query_params, "limit", 50, min_val=1, max_val=200)
            return self._get_domain_history(domain, limit)

        return None

    @handle_errors("consensus detection")
    def handle_post(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Handle POST requests for consensus detection."""
        path = strip_version_prefix(path)

        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _consensus_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for consensus endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Auth required for POST
        user, err = self.require_auth_or_error(handler)
        if err:
            return err
        _, perm_err = self.require_permission_or_error(handler, "consensus:write")
        if perm_err:
            return perm_err

        if path == "/api/consensus/detect":
            body, body_err = self.read_json_body_validated(handler)
            if body_err:
                return body_err
            return self._detect_consensus(body)

        return None

    @handle_errors("consensus detection")
    def _detect_consensus(self, body: dict[str, Any]) -> HandlerResult:
        """Detect consensus from provided proposals/text.

        Accepts a list of proposals and analyzes them for consensus using
        the ConsensusBuilder from the debate engine.

        Request body:
            task: str - The debate task/question
            proposals: list[dict] - List of proposals with 'agent', 'content', and optional 'round'
            threshold: float (optional) - Confidence threshold for consensus (default: 0.7)

        Returns:
            Consensus analysis including proof, claims, votes, and partial consensus.
        """
        task = body.get("task", "")
        if not task:
            return error_response("'task' field is required", 400)

        proposals = body.get("proposals", [])
        if not proposals or not isinstance(proposals, list):
            return error_response("'proposals' must be a non-empty list", 400)

        threshold = body.get("threshold", 0.7)
        if not isinstance(threshold, (int, float)) or not 0.0 <= threshold <= 1.0:
            return error_response("'threshold' must be a number between 0.0 and 1.0", 400)

        try:
            from aragora.debate.consensus import ConsensusBuilder, VoteType

            # Generate a debate ID for this analysis
            import hashlib

            debate_id = "detect-" + hashlib.sha256(task.encode()).hexdigest()[:12]

            builder = ConsensusBuilder(debate_id=debate_id, task=task)

            # Process proposals into claims and evidence
            for proposal in proposals:
                agent = proposal.get("agent", "unknown")
                content = proposal.get("content", "")
                round_num = proposal.get("round", 0)

                if not content:
                    continue

                claim = builder.add_claim(
                    statement=content[:500],
                    author=agent,
                    confidence=0.6,
                    round_num=round_num,
                )
                builder.add_evidence(
                    claim_id=claim.claim_id,
                    source=agent,
                    content=content,
                    evidence_type="argument",
                    supports=True,
                    strength=0.6,
                )

            # Analyze cross-proposal agreement to detect consensus
            agents = list({p.get("agent", "unknown") for p in proposals if p.get("content")})
            total_agents = len(agents) if agents else 1

            # Simple consensus detection: check keyword overlap between proposals
            contents = [p.get("content", "") for p in proposals if p.get("content")]
            if len(contents) >= 2:
                # Calculate pairwise agreement using keyword overlap
                agreement_scores = []
                for i in range(len(contents)):
                    for j in range(i + 1, len(contents)):
                        words_a = set(w.lower() for w in contents[i].split() if len(w) > 4)
                        words_b = set(w.lower() for w in contents[j].split() if len(w) > 4)
                        if words_a and words_b:
                            overlap = len(words_a & words_b)
                            union = len(words_a | words_b)
                            agreement_scores.append(overlap / union if union else 0.0)
                avg_agreement = (
                    sum(agreement_scores) / len(agreement_scores) if agreement_scores else 0.0
                )
            else:
                avg_agreement = 1.0  # Single proposal trivially agrees with itself

            confidence = min(avg_agreement * 1.2, 1.0)  # Scale up slightly
            consensus_reached = confidence >= threshold

            # Record votes
            for agent in agents:
                vote_type = VoteType.AGREE if consensus_reached else VoteType.CONDITIONAL
                builder.record_vote(
                    agent=agent,
                    vote=vote_type,
                    confidence=confidence,
                    reasoning="Agreed with consensus" if consensus_reached else "Partial agreement",
                )

            # Determine final claim
            final_claim = contents[0][:500] if contents else task
            reasoning_summary = (
                f"Analyzed {len(proposals)} proposals from {total_agents} agents. "
                f"Average keyword agreement: {avg_agreement:.0%}. "
                f"{'Consensus reached' if consensus_reached else 'Consensus not reached'} "
                f"(threshold: {threshold:.0%})."
            )

            # Build the proof
            proof = builder.build(
                final_claim=final_claim,
                confidence=confidence,
                consensus_reached=consensus_reached,
                reasoning_summary=reasoning_summary,
                rounds=max((p.get("round", 0) for p in proposals), default=0),
            )

            return json_response(
                {
                    "data": {
                        "debate_id": debate_id,
                        "consensus_reached": consensus_reached,
                        "confidence": round(confidence, 4),
                        "threshold": threshold,
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
                }
            )

        except ImportError:
            return error_response("Consensus detection module not available", 503)

    @handle_errors("consensus status retrieval")
    def _get_consensus_status(self, debate_id: str) -> HandlerResult:
        """Get consensus status for an existing debate.

        Looks up the debate in storage, builds a ConsensusProof from the result,
        and returns the consensus analysis.
        """
        storage = self.get_storage()
        if storage is None:
            return error_response("Storage not available", 503)

        try:
            debate_result = storage.get_debate(debate_id)
        except (KeyError, ValueError, OSError) as e:
            logger.debug("Failed to retrieve debate %s: %s", debate_id, e)
            debate_result = None

        if debate_result is None:
            return error_response(f"Debate not found: {debate_id}", 404)

        try:
            from aragora.debate.consensus import ConsensusBuilder, build_partial_consensus

            builder = ConsensusBuilder.from_debate_result(debate_result)

            # Build proof from the debate result
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

            # Build partial consensus
            partial = build_partial_consensus(debate_result)

            return json_response(
                {
                    "data": {
                        "debate_id": debate_id,
                        "consensus_reached": consensus_reached,
                        "confidence": round(confidence, 4),
                        "agreement_ratio": round(proof.agreement_ratio, 4),
                        "has_strong_consensus": proof.has_strong_consensus,
                        "final_claim": proof.final_claim,
                        "supporting_agents": proof.supporting_agents,
                        "dissenting_agents": proof.dissenting_agents,
                        "claims_count": len(proof.claims),
                        "dissents_count": len(proof.dissents),
                        "unresolved_tensions_count": len(proof.unresolved_tensions),
                        "partial_consensus": partial.to_dict(),
                        "proof": proof.to_dict(),
                        "checksum": proof.checksum,
                    }
                }
            )

        except ImportError:
            return error_response("Consensus detection module not available", 503)

    @ttl_cache(
        ttl_seconds=CACHE_TTL_CONSENSUS_SIMILAR, key_prefix="consensus_similar", skip_first=True
    )
    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("similar debates retrieval")
    def _get_similar_debates(self, topic: str, limit: int) -> HandlerResult:
        """Find debates similar to a topic."""
        if not topic:
            return error_response("topic parameter required", 400)

        memory = ConsensusMemory()
        similar = memory.find_similar_debates(topic, limit=limit)
        return json_response(
            {
                "query": topic,
                "similar": [
                    {
                        "topic": s.consensus.topic,
                        "conclusion": s.consensus.conclusion,
                        "strength": s.consensus.strength.value,
                        "confidence": s.consensus.confidence,
                        "similarity": s.similarity_score,
                        "agents": s.consensus.participating_agents,
                        "dissent_count": len(s.dissents),
                        "timestamp": s.consensus.timestamp.isoformat(),
                    }
                    for s in similar
                ],
                "count": len(similar),
            }
        )

    @ttl_cache(
        ttl_seconds=CACHE_TTL_CONSENSUS_SETTLED, key_prefix="consensus_settled", skip_first=True
    )
    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("settled topics retrieval")
    def _get_settled_topics(self, min_confidence: float, limit: int) -> HandlerResult:
        """Get high-confidence settled topics."""
        memory = ConsensusMemory()
        with get_db_connection(memory.db_path) as conn:
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
            rows = cursor.fetchall()

        return json_response(
            {
                "min_confidence": min_confidence,
                "topics": [
                    {
                        "topic": row[0],
                        "conclusion": row[1],
                        "confidence": row[2],
                        "strength": row[3],
                        "timestamp": row[4],
                    }
                    for row in rows
                ],
                "count": len(rows),
            }
        )

    @ttl_cache(ttl_seconds=CACHE_TTL_CONSENSUS_STATS, key_prefix="consensus_stats", skip_first=True)
    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("consensus stats retrieval")
    def _get_consensus_stats(self) -> HandlerResult:
        """Get consensus memory statistics."""
        memory = ConsensusMemory()
        raw_stats = memory.get_statistics()

        with get_db_connection(memory.db_path) as conn:
            cursor = conn.cursor()
            # Combined query for better performance
            cursor.execute("""
                SELECT
                    SUM(CASE WHEN confidence >= 0.7 THEN 1 ELSE 0 END) as high_conf_count,
                    AVG(confidence) as avg_conf
                FROM consensus
            """)
            row = cursor.fetchone()
            high_confidence_count = row[0] if row and row[0] else 0
            avg_confidence = row[1] if row and row[1] else 0.0

        return json_response(
            {
                "total_topics": raw_stats.get("total_consensus", 0),
                "high_confidence_count": high_confidence_count,
                "domains": list(raw_stats.get("by_domain", {}).keys()),
                "avg_confidence": round(avg_confidence, 3),
                "total_dissents": raw_stats.get("total_dissents", 0),
                "by_strength": raw_stats.get("by_strength", {}),
                "by_domain": raw_stats.get("by_domain", {}),
            }
        )

    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("demo data seeding")
    def _seed_demo_data(self) -> HandlerResult:
        """Seed demo consensus data for search functionality."""
        try:
            from aragora.fixtures import load_demo_consensus

            memory = ConsensusMemory()

            # Get stats before seeding
            stats_before = memory.get_statistics()
            total_before = stats_before.get("total_consensus", 0)

            seeded = load_demo_consensus(memory)

            # Get stats after seeding
            stats_after = memory.get_statistics()
            total_after = stats_after.get("total_consensus", 0)

            return json_response(
                {
                    "success": True,
                    "seeded": seeded,
                    "total_before": total_before,
                    "total_after": total_after,
                    "db_path": memory.db_path,
                    "message": (
                        f"Seeded {seeded} demo consensus records"
                        if seeded > 0
                        else (
                            f"Database has {total_before} existing records"
                            if total_before > 0
                            else "No records added"
                        )
                    ),
                }
            )
        except ImportError:
            return error_response("Fixtures module not available", 503)
        except (KeyError, ValueError, OSError) as e:
            logger.error("Failed to seed demo data: %s", e)
            return error_response(safe_error_message(e, "seeding"), 500)

    @ttl_cache(ttl_seconds=CACHE_TTL_RECENT_DISSENTS, key_prefix="recent_dissents", skip_first=True)
    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("recent dissents retrieval")
    def _get_recent_dissents(
        self, topic: str | None, domain: str | None, limit: int
    ) -> HandlerResult:
        """Get recent dissents, optionally filtered by topic and domain."""
        domain, domain_err = self._validate_domain(domain)
        if domain_err:
            return domain_err

        memory = ConsensusMemory()

        with get_db_connection(memory.db_path) as conn:
            cursor = conn.cursor()

            # Build query with optional filters using parameterized placeholders
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
            """  # noqa: S608 -- dynamic clause from internal state
            params.append(limit)
            cursor.execute(query, tuple(params))
            rows = cursor.fetchall()

        dissents = []
        for row in rows:
            try:
                from aragora.memory.consensus import DissentRecord

                record = DissentRecord.from_dict(json.loads(row[0]))
                topic_name = row[1] or "Unknown topic"
                majority_view = row[2] or "No consensus recorded"

                dissents.append(
                    {
                        "topic": topic_name,
                        "majority_view": majority_view,
                        "dissenting_view": record.content,
                        "dissenting_agent": record.agent_id,
                        "confidence": record.confidence,
                        "reasoning": record.reasoning if record.reasoning else None,
                    }
                )
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                logger.debug("Failed to parse dissent record: %s", e)

        return json_response({"dissents": dissents})

    @ttl_cache(
        ttl_seconds=CACHE_TTL_CONTRARIAN_VIEWS, key_prefix="contrarian_views", skip_first=True
    )
    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("contrarian views retrieval")
    def _get_contrarian_views(
        self, topic: str | None, domain: str | None, limit: int
    ) -> HandlerResult:
        """Get historical contrarian/dissenting views."""
        domain, domain_err = self._validate_domain(domain)
        if domain_err:
            return domain_err

        memory = ConsensusMemory()

        if topic and DissentRetriever is not None:
            try:
                retriever = DissentRetriever(memory)
                records = retriever.find_contrarian_views(topic, domain=domain, limit=limit)
            except (KeyError, ValueError, OSError, TypeError) as e:
                logger.warning("DissentRetriever.find_contrarian_views failed: %s", e)
                records = []
        else:
            with get_db_connection(memory.db_path) as conn:
                cursor = conn.cursor()
                query = """
                    SELECT data FROM dissent
                    WHERE dissent_type IN ('fundamental_disagreement', 'alternative_approach')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()

            records = []
            for row in rows:
                try:
                    from aragora.memory.consensus import DissentRecord

                    records.append(DissentRecord.from_dict(json.loads(row[0])))
                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                    logger.debug("Failed to parse contrarian view record: %s", e)

        return json_response(
            {
                "views": [
                    {
                        "agent": r.agent_id or "unknown",
                        "position": r.content or "",
                        "confidence": r.confidence if r.confidence is not None else 0.0,
                        "reasoning": r.reasoning or "",
                        "debate_id": r.debate_id or "",
                    }
                    for r in records
                ],
            }
        )

    @ttl_cache(ttl_seconds=CACHE_TTL_RISK_WARNINGS, key_prefix="risk_warnings", skip_first=True)
    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("risk warnings retrieval")
    def _get_risk_warnings(
        self, topic: str | None, domain: str | None, limit: int
    ) -> HandlerResult:
        """Get risk warnings and edge case concerns."""
        domain, domain_err = self._validate_domain(domain)
        if domain_err:
            return domain_err

        memory = ConsensusMemory()

        if topic and DissentRetriever is not None:
            try:
                retriever = DissentRetriever(memory)
                records = retriever.find_risk_warnings(topic, domain=domain, limit=limit)
            except (KeyError, ValueError, OSError, TypeError) as e:
                logger.warning("DissentRetriever.find_risk_warnings failed: %s", e)
                records = []
        else:
            with get_db_connection(memory.db_path) as conn:
                cursor = conn.cursor()
                query = """
                    SELECT data FROM dissent
                    WHERE dissent_type IN ('risk_warning', 'edge_case_concern')
                    ORDER BY timestamp DESC
                    LIMIT ?
                """
                cursor.execute(query, (limit,))
                rows = cursor.fetchall()

            records = []
            for row in rows:
                try:
                    from aragora.memory.consensus import DissentRecord

                    records.append(DissentRecord.from_dict(json.loads(row[0])))
                except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                    logger.debug("Failed to parse risk warning record: %s", e)

        def _safe_dissent_type_str(dt: Any) -> str:
            """Safely extract dissent type as string."""
            if dt is None:
                return "unknown"
            if hasattr(dt, "value"):
                return dt.value
            return str(dt)

        def _safe_timestamp_str(ts: Any) -> str:
            """Safely convert timestamp to ISO string."""
            if ts is None:
                from datetime import datetime

                return datetime.now().isoformat()
            if hasattr(ts, "isoformat"):
                return ts.isoformat()
            return str(ts)

        def infer_severity(confidence: float, dissent_type: str) -> str:
            if dissent_type == "risk_warning":
                if confidence >= 0.8:
                    return "critical"
                elif confidence >= 0.6:
                    return "high"
                elif confidence >= 0.4:
                    return "medium"
            return "low"

        return json_response(
            {
                "warnings": [
                    {
                        "domain": (r.metadata or {}).get("domain", "general"),
                        "risk_type": _safe_dissent_type_str(r.dissent_type)
                        .replace("_", " ")
                        .title(),
                        "severity": infer_severity(
                            r.confidence, _safe_dissent_type_str(r.dissent_type)
                        ),
                        "description": r.content or "",
                        "mitigation": r.rebuttal if r.rebuttal else None,
                        "detected_at": _safe_timestamp_str(r.timestamp),
                    }
                    for r in records
                ],
            }
        )

    @require_feature(lambda: CONSENSUS_MEMORY_AVAILABLE, "Consensus memory")
    @handle_errors("domain history retrieval")
    def _get_domain_history(self, domain: str, limit: int) -> HandlerResult:
        """Get consensus history for a domain."""
        # Domain is already validated by extract_path_param with SAFE_ID_PATTERN
        memory = ConsensusMemory()
        records = memory.get_domain_consensus_history(domain, limit=limit)
        return json_response(
            {
                "domain": domain,
                "history": [r.to_dict() for r in records],
                "count": len(records),
            }
        )
