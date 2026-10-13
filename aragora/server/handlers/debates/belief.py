"""
Belief Network and Reasoning endpoint handlers.

Endpoints:
- GET /api/belief-network/:debate_id/cruxes - Get key claims that impact debate outcome
- GET /api/belief-network/:debate_id/load-bearing-claims - Get high-centrality claims
- GET /api/provenance/:debate_id/claims/:claim_id/support - Get claim verification status
- GET /api/laboratory/emergent-traits - Get emergent traits from agent performance
- GET /api/debate/:debate_id/graph-stats - Get argument graph statistics
"""

from __future__ import annotations

__all__ = [
    "BeliefHandler",
]

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

from aragora.rbac.checker import get_permission_checker
from aragora.rbac.models import AuthorizationContext
from aragora.server.validation import validate_debate_id, validate_id
from aragora.server.versioning.compat import strip_version_prefix
from aragora.utils.optional_imports import try_import

from ..base import (
    BaseHandler,
    HandlerResult,
    error_response,
    get_clamped_int_param,
    handle_errors,
    json_response,
)
from ..utils.rate_limit import RateLimiter, get_client_ip

logger = logging.getLogger(__name__)

# Rate limiter for belief network endpoints (60 requests per minute - read-heavy)
_belief_limiter = RateLimiter(requests_per_minute=60)

# Lazy imports for optional dependencies using centralized utility
_belief_imports, BELIEF_NETWORK_AVAILABLE = try_import(
    "aragora.reasoning.belief", "BeliefNetwork", "BeliefPropagationAnalyzer"
)
BeliefNetwork = _belief_imports["BeliefNetwork"]
BeliefPropagationAnalyzer = _belief_imports["BeliefPropagationAnalyzer"]

_lab_imports, LABORATORY_AVAILABLE = try_import("aragora.agents.laboratory", "PersonaLaboratory")
PersonaLaboratory = _lab_imports["PersonaLaboratory"]

_prov_imports, PROVENANCE_AVAILABLE = try_import(
    "aragora.reasoning.provenance", "ProvenanceTracker"
)
ProvenanceTracker = _prov_imports["ProvenanceTracker"]


class BeliefHandler(BaseHandler):
    """Handler for belief network and reasoning endpoints."""

    ROUTES: list[str] = [
        "/api/belief-network/*/cruxes",
        "/api/belief-network/*/load-bearing-claims",
        "/api/belief-network/*/graph",
        "/api/belief-network/*/export",
        "/api/provenance/*/claims/*/support",
        "/api/debate/*/graph-stats",
        # Versioned aliases for SDK parity
        "/api/v1/belief-network/*/graph",
        "/api/v1/belief-network/*/export",
        "/api/v1/debates/*/cruxes",
    ]

    def __init__(self, server_context: dict[str, Any]):
        """Initialize with server context."""
        super().__init__(server_context)
        self._km_adapter: BeliefAdapter | None = None

    def _emit_km_event(self, event_emitter: Any, event_type: str, data: dict) -> None:
        """Emit a KM event to WebSocket clients.

        Args:
            event_emitter: The EventEmitter from server context
            event_type: Type of event (e.g., 'belief_converged')
            data: Event data payload
        """
        try:
            from aragora.events.types import StreamEvent, StreamEventType

            # Map adapter event types to StreamEventType
            type_map = {
                "belief_converged": StreamEventType.BELIEF_CONVERGED,
                "crux_detected": StreamEventType.CRUX_DETECTED,
                "mound_updated": StreamEventType.MOUND_UPDATED,
            }

            stream_type = type_map.get(event_type, StreamEventType.MOUND_UPDATED)
            event = StreamEvent(type=stream_type, data=data)
            event_emitter.emit(event)
        except (ImportError, AttributeError, TypeError, KeyError) as e:
            logger.debug("Failed to emit KM event %s: %s", event_type, e)

    def _get_km_adapter(self) -> BeliefAdapter | None:
        """Get or create Knowledge Mound adapter for belief networks.

        Returns:
            BeliefAdapter instance, or None if KM not available
        """
        if self._km_adapter is not None:
            return self._km_adapter

        # Check if adapter exists in context
        if isinstance(self.ctx, dict) and "belief_km_adapter" in self.ctx:
            self._km_adapter = self.ctx["belief_km_adapter"]
            return self._km_adapter

        # Try to create adapter if KM is available
        try:
            from aragora.knowledge.mound.adapters.belief_adapter import BeliefAdapter

            self._km_adapter = BeliefAdapter(
                enable_dual_write=True,  # Enable bidirectional sync
            )

            # Wire event callback for WebSocket notifications
            event_emitter = self.ctx.get("event_emitter")
            if event_emitter:
                self._km_adapter.set_event_callback(
                    lambda event_type, data: self._emit_km_event(event_emitter, event_type, data)
                )

            # Store in context for sharing
            if isinstance(self.ctx, dict):
                self.ctx["belief_km_adapter"] = self._km_adapter
            logger.info("Belief KM adapter initialized")
            return self._km_adapter

        except ImportError:
            logger.debug("Knowledge Mound BeliefAdapter not available")
            return None
        except (RuntimeError, AttributeError, TypeError) as e:
            logger.warning("Failed to initialize Belief KM adapter: %s", e)
            return None

    def _create_belief_network(
        self,
        debate_id: str,
        topic: str | None = None,
        seed_from_km: bool = False,
    ) -> Any:
        """Create a BeliefNetwork with KM adapter wired.

        Implements query-before-action: optionally seeds the network with
        prior beliefs from Knowledge Mound before propagation.

        Args:
            debate_id: The debate ID for this network
            topic: Optional topic for KM seeding
            seed_from_km: If True and topic provided, seed beliefs from KM

        Returns:
            BeliefNetwork instance with optional KM adapter and seeded beliefs
        """
        km_adapter = self._get_km_adapter()
        network = BeliefNetwork(
            debate_id=debate_id,
            km_adapter=km_adapter,
        )

        # Query-before-action: Seed network with prior beliefs from KM
        if seed_from_km and topic and km_adapter:
            seeded = network.seed_from_km(topic, min_confidence=0.7)
            if seeded > 0:
                logger.info("Seeded belief network with %s prior beliefs from KM", seeded)

        return network

    def can_handle(self, path: str) -> bool:
        """Check if this handler can process the given path."""
        normalized = strip_version_prefix(path)
        if normalized in self.ROUTES:
            return True
        # Handle dynamic routes
        if normalized.startswith("/api/belief-network/") and normalized.endswith("/cruxes"):
            return True
        if normalized.startswith("/api/belief-network/") and normalized.endswith(
            "/load-bearing-claims"
        ):
            return True
        if normalized.startswith("/api/belief-network/") and normalized.endswith("/graph"):
            return True
        if normalized.startswith("/api/belief-network/") and normalized.endswith("/export"):
            return True
        if "/claims/" in normalized and normalized.endswith("/support"):
            return True
        if normalized.startswith("/api/debate/") and normalized.endswith("/graph-stats"):
            return True
        if normalized.startswith("/api/debates/") and normalized.endswith("/cruxes"):
            return True
        return False

    def _check_belief_permission(
        self, handler: Any, user: Any, permission: str = "belief:read"
    ) -> HandlerResult | None:
        """Check RBAC permission for belief network access.

        Args:
            handler: HTTP handler with request context
            user: Authenticated user
            permission: The permission to check (belief:read or belief:export)

        Returns:
            Error response if permission denied, None if allowed
        """
        user_id = getattr(user, "id", None) or getattr(user, "user_id", "anonymous")
        org_id = getattr(handler, "org_id", None) or getattr(user, "org_id", None)
        roles_header = ""
        if hasattr(handler, "headers"):
            roles_header = handler.headers.get("X-User-Roles", "")
        roles = set(roles_header.split(",")) if roles_header else {"member"}

        context = AuthorizationContext(
            user_id=str(user_id),
            org_id=org_id,
            roles=roles,
        )

        checker = get_permission_checker()
        decision = checker.check_permission(context, permission)

        if not decision.allowed:
            logger.warning("Permission denied for %s: %s", permission, decision.reason)
            return error_response("Permission denied", 403)

        return None

    def handle(self, path: str, query_params: dict, handler: Any) -> HandlerResult | None:
        """Route belief network requests to appropriate methods."""
        normalized = strip_version_prefix(path)
        # Rate limit check
        client_ip = get_client_ip(handler)
        if not _belief_limiter.is_allowed(client_ip):
            logger.warning("Rate limit exceeded for belief endpoint: %s", client_ip)
            return error_response("Rate limit exceeded. Please try again later.", 429)

        # Require authentication for belief network endpoints
        try:
            user, err = self.require_auth_or_error(handler)
            if err:
                return err
        except (AttributeError, RuntimeError, TypeError) as e:
            logger.warning("Authentication failed for belief endpoint: %s", e)
            return error_response("Authentication required", 401)

        # Check RBAC permission for belief:read access
        rbac_err = self._check_belief_permission(handler, user, "belief:read")
        if rbac_err:
            return rbac_err

        # Get nomic_dir from server context
        nomic_dir = self.ctx.get("nomic_dir")
        # Note: /api/laboratory/emergent-traits handled by LaboratoryHandler

        if normalized.startswith("/api/belief-network/") and normalized.endswith("/cruxes"):
            debate_id = self._extract_debate_id(normalized, 3)
            if debate_id is None:
                return error_response("Invalid debate_id", 400)
            top_k = get_clamped_int_param(query_params, "top_k", 3, min_val=1, max_val=10)
            return self._get_debate_cruxes(nomic_dir, debate_id, top_k)

        if normalized.startswith("/api/belief-network/") and normalized.endswith(
            "/load-bearing-claims"
        ):
            debate_id = self._extract_debate_id(normalized, 3)
            if debate_id is None:
                return error_response("Invalid debate_id", 400)
            limit = get_clamped_int_param(query_params, "limit", 5, min_val=1, max_val=20)
            return self._get_load_bearing_claims(nomic_dir, debate_id, limit)

        if normalized.startswith("/api/belief-network/") and normalized.endswith("/graph"):
            debate_id = self._extract_debate_id(normalized, 3)
            if debate_id is None:
                return error_response("Invalid debate_id", 400)
            include_cruxes = query_params.get("include_cruxes", ["true"])[0].lower() == "true"
            return self._get_belief_network_graph(nomic_dir, debate_id, include_cruxes)

        if normalized.startswith("/api/belief-network/") and normalized.endswith("/export"):
            # Export requires additional belief:export permission
            export_err = self._check_belief_permission(handler, user, "belief:export")
            if export_err:
                return export_err
            debate_id = self._extract_debate_id(normalized, 3)
            if debate_id is None:
                return error_response("Invalid debate_id", 400)
            format_type = query_params.get("format", ["json"])[0].lower()
            return self._export_belief_network(nomic_dir, debate_id, format_type)

        if "/claims/" in normalized and normalized.endswith("/support"):
            # Pattern: /api/provenance/:debate_id/claims/:claim_id/support
            parts = normalized.split("/")
            if len(parts) >= 7:
                debate_id = parts[3]
                claim_id = parts[5]
                valid_debate, _ = validate_debate_id(debate_id)
                valid_claim, _ = validate_id(claim_id, "claim ID")
                if not valid_debate or not valid_claim:
                    return error_response("Invalid ID format", 400)
                return self._get_claim_support(nomic_dir, debate_id, claim_id)
            return error_response("Invalid path format", 400)

        if normalized.startswith("/api/debate/") and normalized.endswith("/graph-stats"):
            debate_id = self._extract_debate_id(normalized, 3)
            if debate_id is None:
                return error_response("Invalid debate_id", 400)
            return self._get_debate_graph_stats(nomic_dir, debate_id)

        if normalized.startswith("/api/debates/") and normalized.endswith("/cruxes"):
            debate_id = self._extract_debate_id(normalized, 3)
            if debate_id is None:
                return error_response("Invalid debate_id", 400)
            limit = get_clamped_int_param(query_params, "limit", 5, min_val=1, max_val=20)
            return self._get_crux_analysis(nomic_dir, debate_id, limit)

        return None

    def _extract_debate_id(self, path: str, segment_index: int) -> str | None:
        """Extract and validate debate ID from path."""
        parts = path.split("/")
        if len(parts) > segment_index:
            debate_id = parts[segment_index]
            is_valid, _ = validate_debate_id(debate_id)
            if is_valid:
                return debate_id
        return None

    @handle_errors("emergent traits retrieval")
    def _get_emergent_traits(
        self, nomic_dir: Path | None, persona_manager: Any, min_confidence: float, limit: int
    ) -> HandlerResult:
        """Get emergent traits detected from agent performance patterns."""
        if not LABORATORY_AVAILABLE:
            return error_response("Persona laboratory not available", 503)

        lab = PersonaLaboratory(
            db_path=str(nomic_dir / "laboratory.db") if nomic_dir else None,
            persona_manager=persona_manager,
        )
        traits = lab.detect_emergent_traits()
        filtered = [t for t in traits if t.confidence >= min_confidence][:limit]
        return json_response(
            {
                "emergent_traits": [
                    {
                        "agent": t.agent_name,
                        "trait": t.trait_name,
                        "domain": t.domain,
                        "confidence": t.confidence,
                        "evidence": t.evidence,
                        "detected_at": t.detected_at,
                    }
                    for t in filtered
                ],
                "count": len(filtered),
                "min_confidence": min_confidence,
            }
        )

    @handle_errors("debate cruxes retrieval")
    def _get_debate_cruxes(
        self, nomic_dir: Path | None, debate_id: str, top_k: int
    ) -> HandlerResult:
        """Get key claims that would most impact the debate outcome."""
        if not BELIEF_NETWORK_AVAILABLE:
            return error_response("Belief network not available", 503)

        from aragora.debate.traces import DebateTrace

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            return error_response("Debate trace not found", 404)

        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build belief network from debate with KM adapter
        network = self._create_belief_network(debate_id)
        for msg in result.messages:
            network.add_claim(msg.agent, msg.content[:200], confidence=0.7)

        analyzer = BeliefPropagationAnalyzer(network)
        cruxes = analyzer.identify_debate_cruxes(top_k=top_k)

        return json_response(
            {
                "debate_id": debate_id,
                "cruxes": cruxes,
                "count": len(cruxes),
            }
        )

    @handle_errors("crux analysis retrieval")
    def _get_crux_analysis(
        self, nomic_dir: Path | None, debate_id: str, limit: int
    ) -> HandlerResult:
        """Get advanced crux analysis using CruxDetector.

        Uses influence, disagreement, uncertainty, and centrality scores
        to identify debate-pivotal claims.
        """
        if not BELIEF_NETWORK_AVAILABLE:
            return error_response("Belief network not available", 503)

        from aragora.debate.traces import DebateTrace
        from aragora.reasoning.crux_detector import CruxDetector

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            return error_response("Debate trace not found", 404)

        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build belief network from debate
        network = self._create_belief_network(debate_id)
        for msg in result.messages:
            network.add_claim(msg.agent, msg.content[:200], confidence=0.7)

        # Run crux detection
        km_adapter = self._get_km_adapter()
        detector = CruxDetector(network, km_adapter=km_adapter)
        analysis = detector.detect_cruxes(top_k=limit)

        return json_response(
            {
                "debate_id": debate_id,
                **analysis.to_dict(),
            }
        )

    @handle_errors("load bearing claims retrieval")
    def _get_load_bearing_claims(
        self, nomic_dir: Path | None, debate_id: str, limit: int
    ) -> HandlerResult:
        """Get claims with highest centrality (most load-bearing)."""
        if not BELIEF_NETWORK_AVAILABLE:
            return error_response("Belief network not available", 503)

        from aragora.debate.traces import DebateTrace

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            return error_response("Debate trace not found", 404)

        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build belief network from debate with KM adapter
        network = self._create_belief_network(debate_id)
        for msg in result.messages:
            network.add_claim(msg.agent, msg.content[:200], confidence=0.7)

        load_bearing = network.get_load_bearing_claims(limit=limit)

        return json_response(
            {
                "debate_id": debate_id,
                "load_bearing_claims": [
                    {
                        "claim_id": node.claim_id,
                        "statement": node.claim_statement,
                        "author": node.author,
                        "centrality": centrality,
                    }
                    for node, centrality in load_bearing
                ],
                "count": len(load_bearing),
            }
        )

    @handle_errors("claim support retrieval")
    def _get_claim_support(
        self, nomic_dir: Path | None, debate_id: str, claim_id: str
    ) -> HandlerResult:
        """Get verification status of all evidence supporting a claim."""
        if not PROVENANCE_AVAILABLE:
            return error_response("Provenance tracker not available", 503)

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        provenance_path = nomic_dir / "provenance" / f"{debate_id}.json"
        if not provenance_path.exists():
            return json_response(
                {
                    "debate_id": debate_id,
                    "claim_id": claim_id,
                    "support": None,
                    "message": "No provenance data for this debate",
                }
            )

        tracker = ProvenanceTracker.load(provenance_path)
        support = tracker.get_claim_support(claim_id)

        return json_response(
            {
                "debate_id": debate_id,
                "claim_id": claim_id,
                "support": support,
            }
        )

    @handle_errors("debate graph stats retrieval")
    def _get_debate_graph_stats(self, nomic_dir: Path | None, debate_id: str) -> HandlerResult:
        """Get argument graph statistics for a debate."""
        from aragora.debate.traces import DebateTrace
        from aragora.visualization.mapper import ArgumentCartographer

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            # Try replays directory as fallback
            replay_path = nomic_dir / "replays" / debate_id / "events.jsonl"
            if replay_path.exists():
                cartographer = ArgumentCartographer()
                cartographer.set_debate_context(debate_id, "")
                with replay_path.open() as f:
                    for line in f:
                        if line.strip():
                            try:
                                event = json.loads(line)
                            except json.JSONDecodeError:
                                continue  # Skip malformed event lines
                            if event.get("type") == "agent_message":
                                cartographer.update_from_message(
                                    agent=event.get("agent", "unknown"),
                                    content=event.get("data", {}).get("content", ""),
                                    role=event.get("data", {}).get("role", "proposer"),
                                    round_num=event.get("round", 1),
                                )
                            elif event.get("type") == "critique":
                                cartographer.update_from_critique(
                                    critic_agent=event.get("agent", "unknown"),
                                    target_agent=event.get("data", {}).get("target", "unknown"),
                                    severity=event.get("data", {}).get("severity", 0.5),
                                    round_num=event.get("round", 1),
                                    critique_text=event.get("data", {}).get("content", ""),
                                )
                stats = cartographer.get_statistics()
                return json_response(stats)
            else:
                return error_response("Debate not found", 404)

        # Load from trace file
        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build cartographer from debate result
        cartographer = ArgumentCartographer()
        cartographer.set_debate_context(debate_id, result.task or "")

        for msg in result.messages:
            cartographer.update_from_message(
                agent=msg.agent,
                content=msg.content,
                role=msg.role,
                round_num=msg.round,
            )

        for critique in result.critiques:
            cartographer.update_from_critique(
                critic_agent=critique.agent,
                target_agent=critique.target or "",
                severity=critique.severity,
                round_num=getattr(critique, "round", 1),
                critique_text=critique.reasoning,
            )

        stats = cartographer.get_statistics()
        return json_response(stats)

    @handle_errors("belief network graph retrieval")
    def _get_belief_network_graph(
        self, nomic_dir: Path | None, debate_id: str, include_cruxes: bool = True
    ) -> HandlerResult:
        """Get belief network as a graph structure for visualization.

        Returns nodes (claims) and links (influence relationships) suitable
        for force-directed graph rendering.

        Response:
        {
            "nodes": [
                {
                    "id": "claim_001",
                    "claim_id": "claim_001",
                    "statement": "...",
                    "author": "claude",
                    "centrality": 0.85,
                    "is_crux": true,
                    "crux_score": 0.92,
                    "entropy": 0.65,
                    "belief": {"true_prob": 0.6, "false_prob": 0.2, "uncertain_prob": 0.2}
                }
            ],
            "links": [
                {"source": "claim_001", "target": "claim_002", "weight": 0.7, "type": "supports"}
            ],
            "metadata": {
                "debate_id": "debate_abc",
                "total_claims": 15,
                "crux_count": 3
            }
        }
        """
        if not BELIEF_NETWORK_AVAILABLE:
            return error_response("Belief network not available", 503)

        from aragora.debate.traces import DebateTrace

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            return error_response("Debate trace not found", 404)

        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build belief network with KM adapter
        network = self._create_belief_network(debate_id)
        for msg in result.messages:
            network.add_claim(msg.agent, msg.content[:200], confidence=0.7)

        # Get cruxes if requested
        crux_ids = set()
        crux_scores = {}
        if include_cruxes:
            analyzer = BeliefPropagationAnalyzer(network)
            cruxes = analyzer.identify_debate_cruxes(top_k=10)
            for crux in cruxes:
                crux_ids.add(crux.get("claim_id", ""))
                crux_scores[crux.get("claim_id", "")] = crux.get("crux_score", 0)

        # Build graph structure
        nodes = []
        node_ids = set()

        for node_data in network.get_all_claims():
            node = node_data.get("node")
            if not node:
                continue

            claim_id = node.claim_id
            node_ids.add(claim_id)

            belief = (
                node.get_belief_distribution() if hasattr(node, "get_belief_distribution") else None
            )

            nodes.append(
                {
                    "id": claim_id,
                    "claim_id": claim_id,
                    "statement": node.claim_statement,
                    "author": node.author,
                    "centrality": node_data.get("centrality", 0.5),
                    "is_crux": claim_id in crux_ids,
                    "crux_score": crux_scores.get(claim_id),
                    "entropy": node_data.get("entropy", 0.5),
                    "belief": belief,
                }
            )

        # Build links from influence relationships
        links = []
        for edge in network.get_all_edges():
            source = edge.get("source")
            target = edge.get("target")
            if source in node_ids and target in node_ids:
                links.append(
                    {
                        "source": source,
                        "target": target,
                        "weight": edge.get("weight", 0.5),
                        "type": edge.get("type", "influences"),
                    }
                )

        return json_response(
            {
                "nodes": nodes,
                "links": links,
                "metadata": {
                    "debate_id": debate_id,
                    "total_claims": len(nodes),
                    "crux_count": len(crux_ids),
                },
            }
        )

    @handle_errors("belief network export")
    def _export_belief_network(
        self, nomic_dir: Path | None, debate_id: str, format_type: str = "json"
    ) -> HandlerResult:
        """Export belief network in various formats.

        Supported formats:
        - json: Full JSON structure (default)
        - graphml: GraphML format for Gephi/yEd
        - csv: CSV format (nodes and edges as separate arrays)

        Response varies by format type.
        """
        if not BELIEF_NETWORK_AVAILABLE:
            return error_response("Belief network not available", 503)

        from aragora.debate.traces import DebateTrace

        if not nomic_dir:
            return error_response("Nomic directory not configured", 503)

        trace_path = nomic_dir / "traces" / f"{debate_id}.json"
        if not trace_path.exists():
            return error_response("Debate trace not found", 404)

        trace = DebateTrace.load(trace_path)
        result = trace.to_debate_result()

        # Build belief network with KM adapter
        network = self._create_belief_network(debate_id)
        for msg in result.messages:
            network.add_claim(msg.agent, msg.content[:200], confidence=0.7)

        # Get cruxes
        analyzer = BeliefPropagationAnalyzer(network)
        cruxes = analyzer.identify_debate_cruxes(top_k=10)
        crux_ids = {c.get("claim_id", "") for c in cruxes}

        # Build export data
        nodes_data = []
        edges_data = []
        node_ids = set()

        for node_data in network.get_all_claims():
            node = node_data.get("node")
            if not node:
                continue

            claim_id = node.claim_id
            node_ids.add(claim_id)
            nodes_data.append(
                {
                    "id": claim_id,
                    "statement": node.claim_statement,
                    "author": node.author,
                    "centrality": node_data.get("centrality", 0.5),
                    "is_crux": claim_id in crux_ids,
                }
            )

        for edge in network.get_all_edges():
            source = edge.get("source")
            target = edge.get("target")
            if source in node_ids and target in node_ids:
                edges_data.append(
                    {
                        "source": source,
                        "target": target,
                        "weight": edge.get("weight", 0.5),
                        "type": edge.get("type", "influences"),
                    }
                )

        if format_type == "csv":
            # Return CSV-friendly structure
            return json_response(
                {
                    "format": "csv",
                    "debate_id": debate_id,
                    "nodes_csv": nodes_data,
                    "edges_csv": edges_data,
                    "headers": {
                        "nodes": ["id", "statement", "author", "centrality", "is_crux"],
                        "edges": ["source", "target", "weight", "type"],
                    },
                }
            )

        elif format_type == "graphml":
            # Build GraphML XML
            graphml_lines = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
                '  <key id="statement" for="node" attr.name="statement" attr.type="string"/>',
                '  <key id="author" for="node" attr.name="author" attr.type="string"/>',
                '  <key id="centrality" for="node" attr.name="centrality" attr.type="double"/>',
                '  <key id="is_crux" for="node" attr.name="is_crux" attr.type="boolean"/>',
                '  <key id="weight" for="edge" attr.name="weight" attr.type="double"/>',
                '  <key id="type" for="edge" attr.name="type" attr.type="string"/>',
                f'  <graph id="{debate_id}" edgedefault="directed">',
            ]

            for node in nodes_data:
                statement_escaped = (
                    node["statement"]
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                graphml_lines.append(f'    <node id="{node["id"]}">')
                graphml_lines.append(f'      <data key="statement">{statement_escaped}</data>')
                graphml_lines.append(f'      <data key="author">{node["author"]}</data>')
                graphml_lines.append(f'      <data key="centrality">{node["centrality"]}</data>')
                graphml_lines.append(
                    f'      <data key="is_crux">{str(node["is_crux"]).lower()}</data>'
                )
                graphml_lines.append("    </node>")

            for i, edge in enumerate(edges_data):
                graphml_lines.append(
                    f'    <edge id="e{i}" source="{edge["source"]}" target="{edge["target"]}">'
                )
                graphml_lines.append(f'      <data key="weight">{edge["weight"]}</data>')
                graphml_lines.append(f'      <data key="type">{edge["type"]}</data>')
                graphml_lines.append("    </edge>")

            graphml_lines.extend(["  </graph>", "</graphml>"])

            return json_response(
                {
                    "format": "graphml",
                    "debate_id": debate_id,
                    "content": "\n".join(graphml_lines),
                    "content_type": "application/xml",
                }
            )

        else:
            # Default JSON format
            return json_response(
                {
                    "format": "json",
                    "debate_id": debate_id,
                    "nodes": nodes_data,
                    "edges": edges_data,
                    "summary": {
                        "total_nodes": len(nodes_data),
                        "total_edges": len(edges_data),
                        "crux_count": len(crux_ids),
                    },
                }
            )
