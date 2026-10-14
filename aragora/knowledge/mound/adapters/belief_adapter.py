"""
BeliefAdapter - Bridges the Belief Network to the Knowledge Mound.

This adapter enables bidirectional integration between the reasoning/belief
system and the Knowledge Mound:

- Data flow IN: Converged beliefs, cruxes, and provenance chains stored in KM
- Data flow OUT: Historical cruxes and related claims retrieved for context
- Reverse flow: KM cross-references inform belief network construction

The adapter provides:
- Belief storage after propagation converges
- Crux persistence for cross-debate learning
- Provenance chain verification tracking
- Historical crux retrieval for prediction

ID Prefixes:
- bl_: Belief nodes
- cx_: Crux claims
- pv_: Provenance chains
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from collections.abc import Callable

from aragora.knowledge.mound.adapters._base import KnowledgeMoundAdapter
from aragora.knowledge.mound.adapters._fusion_mixin import FusionMixin
from aragora.knowledge.mound.adapters._semantic_mixin import SemanticSearchMixin

if TYPE_CHECKING:
    from aragora.knowledge.unified.types import KnowledgeItem
    from aragora.reasoning.belief import BeliefNetwork, BeliefNode, CruxClaim

# Type alias for event callback
EventCallback = Callable[[str, dict[str, Any]], None]

logger = logging.getLogger(__name__)

# ============================================================================
# Reverse Flow Dataclasses (KM → BeliefNetwork)
# ============================================================================


@dataclass
class KMThresholdUpdate:
    """Result of updating belief thresholds from KM patterns."""

    old_belief_confidence_threshold: float
    new_belief_confidence_threshold: float
    old_crux_score_threshold: float
    new_crux_score_threshold: float
    patterns_analyzed: int = 0
    adjustments_made: int = 0
    confidence: float = 0.7
    recommendation: str = "keep"  # "increase", "decrease", "keep"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMBeliefValidation:
    """Validation result from KM for a belief/crux."""

    belief_id: str
    km_confidence: float  # 0.0-1.0 from KM cross-referencing
    outcome_success_rate: float = 0.0  # Success rate when this belief was used
    cross_debate_frequency: int = 0  # How often this belief appears across debates
    was_contradicted: bool = False
    was_supported: bool = False
    recommendation: str = "keep"  # "boost", "penalize", "keep", "review"
    adjustment: float = 0.0  # Confidence adjustment amount
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class KMPriorRecommendation:
    """KM-validated prior probability for a claim type."""

    claim_type: str
    recommended_prior: float  # 0.0-1.0
    sample_count: int = 0
    confidence: float = 0.7
    supporting_debates: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class BeliefThresholdSyncResult:
    """Result of syncing thresholds from KM patterns."""

    beliefs_analyzed: int = 0
    cruxes_analyzed: int = 0
    threshold_updates: list[KMThresholdUpdate] = field(default_factory=list)
    validation_results: list[KMBeliefValidation] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    duration_ms: float = 0.0


@dataclass
class BeliefSearchResult:
    """Wrapper for belief search results with adapter metadata."""

    belief: dict[str, Any]
    relevance_score: float = 0.0
    matched_topics: list[str] = field(default_factory=list)


@dataclass
class CruxSearchResult:
    """Wrapper for crux search results."""

    crux: dict[str, Any]
    relevance_score: float = 0.0
    debate_ids: list[str] = field(default_factory=list)


class BeliefAdapter(FusionMixin, SemanticSearchMixin, KnowledgeMoundAdapter):
    """
    Adapter that bridges BeliefNetwork to the Knowledge Mound.

    Provides methods for the Knowledge Mound's federated query system:
    - store_converged_belief: Store beliefs after propagation
    - store_crux: Store pivotal claims for cross-debate learning
    - store_provenance: Store verified provenance chains
    - search_similar_cruxes: Find historical cruxes on topic
    - search_related_claims: Find claims related by topic

    Usage:
        from aragora.reasoning.belief import BeliefNetwork, CruxClaim
        from aragora.knowledge.mound.adapters import BeliefAdapter

        network = BeliefNetwork(debate_id="debate-123")
        adapter = BeliefAdapter(network)

        # After propagation, store converged beliefs
        result = network.propagate()
        if result.converged:
            adapter.store_converged_beliefs(min_confidence=0.8)

        # Store detected cruxes
        cruxes = detector.detect_cruxes(min_crux_score=0.3)
        for crux in cruxes:
            adapter.store_crux(crux)
    """

    BELIEF_PREFIX = "bl_"
    CRUX_PREFIX = "cx_"
    PROVENANCE_PREFIX = "pv_"

    # Thresholds from plan
    MIN_BELIEF_CONFIDENCE = 0.8  # Only store high-confidence beliefs
    MIN_CRUX_SCORE = 0.3  # Store cruxes above this threshold

    # Mixin configuration
    adapter_name = "belief"
    source_type = "belief"

    # FusionMixin abstract method implementations
    def _get_fusion_sources(self) -> list[str]:
        """Return list of source adapters this adapter can fuse data from."""
        return ["consensus", "elo", "evidence", "continuum", "insights"]

    def _extract_fusible_data(
        self,
        km_item: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Extract fusible data from a KM item.

        Args:
            km_item: A Knowledge Mound item with validation data.

        Returns:
            Dictionary of extracted data suitable for fusion.
        """
        metadata = km_item.get("metadata", {})
        confidence = km_item.get("confidence") or metadata.get("confidence", 0.5)

        # Check if this is a crux
        is_crux = metadata.get("is_crux", False)
        crux_score = metadata.get("crux_score", 0.0) if is_crux else None

        return {
            "confidence": float(confidence) if confidence else 0.5,
            "source_id": km_item.get("id") or metadata.get("source_id"),
            "is_crux": is_crux,
            "crux_score": crux_score,
            "centrality": metadata.get("centrality", 0.0),
            "is_valid": float(confidence) >= self.MIN_BELIEF_CONFIDENCE if confidence else True,
            "sources": metadata.get("sources", []),
            "reasoning": metadata.get("reasoning"),
        }

    def _apply_fusion_result(
        self,
        record: Any,
        fusion_result: Any,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """Apply a fusion result to a belief record.

        Args:
            record: The belief record (dict) to update.
            fusion_result: The fused validation result with fused_confidence.
            metadata: Optional additional metadata.

        Returns:
            True if the record was updated.
        """
        try:
            # Get fused confidence from result
            fused_confidence = getattr(fusion_result, "fused_confidence", None)
            if fused_confidence is None:
                return False

            # Handle dict records
            if isinstance(record, dict):
                record["confidence"] = fused_confidence
                record["km_fused"] = True
                record["km_fused_confidence"] = fused_confidence
                if metadata:
                    record.setdefault("metadata", {})["fusion_metadata"] = metadata
                record_id = record.get("id", "unknown")

                # Update stored belief if it exists
                belief_id = record.get("id")
                if belief_id and belief_id in self._beliefs:
                    self._beliefs[belief_id]["confidence"] = fused_confidence
                    self._beliefs[belief_id]["km_fused"] = True
            else:
                setattr(record, "confidence", fused_confidence)
                if hasattr(record, "metadata") and isinstance(record.metadata, dict):
                    record.metadata["km_fused"] = True
                    record.metadata["km_fused_confidence"] = fused_confidence
                record_id = getattr(record, "id", "unknown")

            logger.debug(
                f"Applied fusion result to belief {record_id}: "
                f"fused_confidence={fused_confidence:.3f}"
            )
            return True
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            logger.warning("Failed to apply fusion result to belief: %s", e)
            return False

    def __init__(
        self,
        network: BeliefNetwork | None = None,
        enable_dual_write: bool = False,
        event_callback: EventCallback | None = None,
        enable_resilience: bool = True,
    ):
        """
        Initialize the adapter.

        Args:
            network: Optional BeliefNetwork instance to wrap
            enable_dual_write: If True, writes go to both systems during migration
            event_callback: Optional callback for emitting events (event_type, data)
            enable_resilience: If True, enables circuit breaker and bulkhead protection
        """
        # Initialize base adapter (handles dual_write, event_callback, resilience, metrics, tracing)
        super().__init__(
            enable_dual_write=enable_dual_write,
            event_callback=event_callback,
            enable_resilience=enable_resilience,
        )

        self._network = network

        # In-memory storage for queries (will be replaced by KM backend)
        self._beliefs: dict[str, dict[str, Any]] = {}
        self._cruxes: dict[str, dict[str, Any]] = {}
        self._provenance: dict[str, dict[str, Any]] = {}

        # Indices for fast lookup
        self._debate_beliefs: dict[str, list[str]] = {}  # debate_id -> [belief_ids]
        self._debate_cruxes: dict[str, list[str]] = {}  # debate_id -> [crux_ids]
        self._topic_cruxes: dict[str, list[str]] = {}  # topic -> [crux_ids]

    # set_event_callback, _emit_event, _record_metric inherited from KnowledgeMoundAdapter

    # SemanticSearchMixin required methods

    def _get_record_by_id(self, record_id: str) -> Any | None:
        """Get a belief or crux record by ID (required by SemanticSearchMixin).

        Searches beliefs first, then cruxes, then provenance chains.
        Handles prefixed IDs (bl_, cx_, pv_) from the SemanticStore.

        Args:
            record_id: The record identifier, possibly prefixed.

        Returns:
            The record dict, or None if not found.
        """
        # Try beliefs with and without prefix
        if record_id.startswith(self.BELIEF_PREFIX):
            belief = self._beliefs.get(record_id)
            if belief is not None:
                return belief
            return self._beliefs.get(record_id[len(self.BELIEF_PREFIX) :])

        # Try cruxes with and without prefix
        if record_id.startswith(self.CRUX_PREFIX):
            crux = self._cruxes.get(record_id)
            if crux is not None:
                return crux
            return self._cruxes.get(record_id[len(self.CRUX_PREFIX) :])

        # Try provenance with and without prefix
        if record_id.startswith(self.PROVENANCE_PREFIX):
            prov = self._provenance.get(record_id)
            if prov is not None:
                return prov
            return self._provenance.get(record_id[len(self.PROVENANCE_PREFIX) :])

        # No prefix: try all storage dicts with prefixed and raw IDs
        for prefix, storage in [
            (self.BELIEF_PREFIX, self._beliefs),
            (self.CRUX_PREFIX, self._cruxes),
            (self.PROVENANCE_PREFIX, self._provenance),
        ]:
            if record_id in storage:
                return storage[record_id]
            prefixed = f"{prefix}{record_id}"
            if prefixed in storage:
                return storage[prefixed]

        return None

    def _record_to_dict(self, record: Any, similarity: float = 0.0) -> dict[str, Any]:
        """Convert a belief/crux/provenance record to dict (required by SemanticSearchMixin).

        Handles dict records from the in-memory stores. Adds a similarity
        score for semantic search ranking.

        Args:
            record: The record (typically a dict from _beliefs, _cruxes, or _provenance).
            similarity: Similarity score from the semantic search.

        Returns:
            Dictionary representation with similarity score.
        """
        if isinstance(record, dict):
            result = dict(record)
            result["similarity"] = similarity
            return result
        # Fallback for non-dict records (e.g., dataclass objects)
        return {
            "id": getattr(record, "id", getattr(record, "node_id", None)),
            "content": getattr(record, "claim_statement", getattr(record, "statement", "")),
            "confidence": getattr(record, "confidence", 0.0),
            "similarity": similarity,
            "metadata": getattr(record, "metadata", {}),
        }

    def _extract_record_id(self, source_id: str) -> str:
        """Extract record ID from prefixed source ID (override for SemanticSearchMixin).

        Args:
            source_id: The source ID from SemanticStore, possibly prefixed.

        Returns:
            The actual record ID for lookup.
        """
        for prefix in (self.BELIEF_PREFIX, self.CRUX_PREFIX, self.PROVENANCE_PREFIX):
            if source_id.startswith(prefix):
                return source_id[len(prefix) :]
        return source_id

    @property
    def network(self) -> BeliefNetwork | None:
        """Access the underlying BeliefNetwork."""
        return self._network

    def set_network(self, network: BeliefNetwork) -> None:
        """Set the belief network to use."""
        self._network = network

    def store_converged_belief(
        self,
        node: BeliefNode,
        debate_id: str | None = None,
    ) -> str | None:
        """
        Store a converged belief node in the Knowledge Mound.

        Args:
            node: The BeliefNode to store
            debate_id: Optional debate ID (uses network's if not provided)

        Returns:
            The belief ID if stored, None if below threshold
        """
        import time

        start = time.time()
        success = False

        try:
            # Check confidence threshold
            confidence = node.posterior.p_true if hasattr(node.posterior, "p_true") else 0.5
            if (
                confidence < self.MIN_BELIEF_CONFIDENCE
                and (1 - confidence) < self.MIN_BELIEF_CONFIDENCE
            ):
                logger.debug(f"Belief {node.node_id} below confidence threshold: {confidence:.2f}")
                return None

            debate_id = debate_id or (self._network.debate_id if self._network else None)
            belief_id = f"{self.BELIEF_PREFIX}{node.node_id}"

            belief_data = {
                "id": belief_id,
                "node_id": node.node_id,
                "claim_id": node.claim_id,
                "claim_statement": node.claim_statement,
                "author": node.author,
                "confidence": confidence,
                "prior_confidence": node.prior.p_true if hasattr(node.prior, "p_true") else 0.5,
                "status": node.status.value if hasattr(node.status, "value") else str(node.status),
                "centrality": node.centrality,
                "update_count": node.update_count,
                "debate_id": debate_id,
                "parent_ids": node.parent_ids,
                "child_ids": node.child_ids,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "metadata": node.metadata if hasattr(node, "metadata") else {},
            }

            self._beliefs[belief_id] = belief_data

            # Update indices
            if debate_id:
                if debate_id not in self._debate_beliefs:
                    self._debate_beliefs[debate_id] = []
                self._debate_beliefs[debate_id].append(belief_id)

            # Emit event for WebSocket updates
            self._emit_event(
                "belief_converged",
                {
                    "belief_id": belief_id,
                    "claim_statement": node.claim_statement[:100] if node.claim_statement else "",
                    "confidence": confidence,
                    "debate_id": debate_id,
                },
            )

            logger.info(f"Stored converged belief: {belief_id} (confidence={confidence:.2f})")
            success = True
            return belief_id
        finally:
            self._record_metric("store", success, time.time() - start)

    def store_converged_beliefs(
        self,
        min_confidence: float | None = None,
    ) -> list[str]:
        """
        Store all converged beliefs from the network above threshold.

        Args:
            min_confidence: Minimum confidence threshold (default: MIN_BELIEF_CONFIDENCE)

        Returns:
            List of stored belief IDs
        """
        if not self._network:
            logger.warning("No network set, cannot store beliefs")
            return []

        min_conf = min_confidence or self.MIN_BELIEF_CONFIDENCE
        stored_ids = []

        for node in self._network.nodes.values():
            confidence = node.posterior.p_true if hasattr(node.posterior, "p_true") else 0.5
            # Store if confidence is high in either direction
            if confidence >= min_conf or (1 - confidence) >= min_conf:
                belief_id = self.store_converged_belief(node)
                if belief_id:
                    stored_ids.append(belief_id)

        logger.info("Stored %s converged beliefs from network", len(stored_ids))
        return stored_ids

    def store_crux(
        self,
        crux: CruxClaim,
        debate_id: str | None = None,
        topics: list[str] | None = None,
    ) -> str | None:
        """
        Store a crux claim in the Knowledge Mound.

        Args:
            crux: The CruxClaim to store
            debate_id: Optional debate ID
            topics: Optional topic tags for indexing

        Returns:
            The crux ID if stored, None if below threshold
        """
        if crux.crux_score < self.MIN_CRUX_SCORE:
            logger.debug(f"Crux {crux.claim_id} below score threshold: {crux.crux_score:.2f}")
            return None

        debate_id = debate_id or (self._network.debate_id if self._network else None)
        crux_id = f"{self.CRUX_PREFIX}{crux.claim_id}"

        crux_data = {
            "id": crux_id,
            "claim_id": crux.claim_id,
            "statement": crux.statement,
            "author": crux.author,
            "crux_score": crux.crux_score,
            "influence_score": crux.influence_score,
            "disagreement_score": crux.disagreement_score,
            "uncertainty_score": crux.uncertainty_score,
            "centrality_score": crux.centrality_score,
            "affected_claims": crux.affected_claims,
            "contesting_agents": crux.contesting_agents,
            "resolution_impact": crux.resolution_impact,
            "debate_id": debate_id,
            "topics": topics or [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self._cruxes[crux_id] = crux_data

        # Update indices
        if debate_id:
            if debate_id not in self._debate_cruxes:
                self._debate_cruxes[debate_id] = []
            self._debate_cruxes[debate_id].append(crux_id)

        for topic in topics or []:
            topic_lower = topic.lower()
            if topic_lower not in self._topic_cruxes:
                self._topic_cruxes[topic_lower] = []
            self._topic_cruxes[topic_lower].append(crux_id)

        # Emit event for WebSocket updates
        self._emit_event(
            "crux_detected",
            {
                "crux_id": crux_id,
                "statement": crux.statement[:100] if crux.statement else "",
                "crux_score": crux.crux_score,
                "debate_id": debate_id,
                "topics": topics or [],
            },
        )

        logger.info(f"Stored crux: {crux_id} (score={crux.crux_score:.2f})")
        return crux_id

    def store_provenance(
        self,
        chain_id: str,
        source_id: str,
        claim_ids: list[str],
        verified: bool,
        verification_method: str,
        debate_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Store a provenance chain in the Knowledge Mound.

        Args:
            chain_id: Unique identifier for the provenance chain
            source_id: ID of the original source
            claim_ids: List of claim IDs in the chain
            verified: Whether the chain is verified
            verification_method: How verification was done
            debate_id: Optional debate ID
            metadata: Optional additional metadata

        Returns:
            The provenance ID if stored, None if not verified
        """
        # Only store verified chains per plan
        if not verified:
            logger.debug("Provenance chain %s not verified, skipping", chain_id)
            return None

        debate_id = debate_id or (self._network.debate_id if self._network else None)
        prov_id = f"{self.PROVENANCE_PREFIX}{chain_id}"

        prov_data = {
            "id": prov_id,
            "chain_id": chain_id,
            "source_id": source_id,
            "claim_ids": claim_ids,
            "verified": verified,
            "verification_method": verification_method,
            "debate_id": debate_id,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        self._provenance[prov_id] = prov_data

        logger.info("Stored provenance chain: %s", prov_id)
        return prov_id

    def get_belief(self, belief_id: str) -> dict[str, Any] | None:
        """
        Get a specific belief by ID.

        Args:
            belief_id: The belief ID (may be prefixed with "bl_")

        Returns:
            Belief dict or None
        """
        if not belief_id.startswith(self.BELIEF_PREFIX):
            belief_id = f"{self.BELIEF_PREFIX}{belief_id}"
        return self._beliefs.get(belief_id)

    def get_crux(self, crux_id: str) -> dict[str, Any] | None:
        """
        Get a specific crux by ID.

        Args:
            crux_id: The crux ID (may be prefixed with "cx_")

        Returns:
            Crux dict or None
        """
        if not crux_id.startswith(self.CRUX_PREFIX):
            crux_id = f"{self.CRUX_PREFIX}{crux_id}"
        return self._cruxes.get(crux_id)

    def search_similar_cruxes(
        self,
        query: str,
        limit: int = 10,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Find historical cruxes similar to the query.

        This enables cross-debate learning by finding cruxes
        that appeared in previous debates on similar topics.

        Args:
            query: Search query (keywords from claim statement)
            limit: Maximum results to return
            min_score: Minimum crux score threshold

        Returns:
            List of matching crux dicts
        """
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for crux in self._cruxes.values():
            if crux["crux_score"] < min_score:
                continue

            statement_lower = crux["statement"].lower()
            statement_words = set(statement_lower.split())

            # Simple keyword overlap scoring
            overlap = len(query_words & statement_words)
            if overlap > 0:
                relevance = overlap / max(len(query_words), 1)
                results.append(
                    {
                        **crux,
                        "relevance_score": relevance,
                    }
                )

        # Sort by relevance * crux_score
        results.sort(
            key=lambda x: x["relevance_score"] * x["crux_score"],
            reverse=True,
        )

        return results[:limit]

    def search_cruxes_by_topic(
        self,
        topic: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Find cruxes tagged with a specific topic.

        Args:
            topic: Topic to search for
            limit: Maximum results

        Returns:
            List of matching crux dicts
        """
        topic_lower = topic.lower()
        crux_ids = self._topic_cruxes.get(topic_lower, [])

        results = []
        for crux_id in crux_ids[:limit]:
            crux = self._cruxes.get(crux_id)
            if crux:
                results.append(crux)

        return results

    def get_debate_beliefs(
        self,
        debate_id: str,
        min_confidence: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Get all beliefs from a specific debate.

        Args:
            debate_id: The debate ID
            min_confidence: Minimum confidence filter

        Returns:
            List of belief dicts
        """
        belief_ids = self._debate_beliefs.get(debate_id, [])
        results = []

        for belief_id in belief_ids:
            belief = self._beliefs.get(belief_id)
            if belief and belief.get("confidence", 0) >= min_confidence:
                results.append(belief)

        return results

    def get_debate_cruxes(
        self,
        debate_id: str,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Get all cruxes from a specific debate.

        Args:
            debate_id: The debate ID
            min_score: Minimum crux score filter

        Returns:
            List of crux dicts
        """
        crux_ids = self._debate_cruxes.get(debate_id, [])
        results = []

        for crux_id in crux_ids:
            crux = self._cruxes.get(crux_id)
            if crux and crux.get("crux_score", 0) >= min_score:
                results.append(crux)

        return results

    def to_knowledge_item(self, belief: dict[str, Any]) -> KnowledgeItem:
        """
        Convert a belief dict to a KnowledgeItem.

        Args:
            belief: The belief dictionary

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.unified.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        # Map confidence to level
        confidence_val = belief.get("confidence", 0.5)
        if confidence_val >= 0.9:
            confidence = ConfidenceLevel.VERIFIED
        elif confidence_val >= 0.8:
            confidence = ConfidenceLevel.HIGH
        elif confidence_val >= 0.6:
            confidence = ConfidenceLevel.MEDIUM
        elif confidence_val >= 0.4:
            confidence = ConfidenceLevel.LOW
        else:
            confidence = ConfidenceLevel.UNVERIFIED

        created_at = belief.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=belief["id"],
            content=belief.get("claim_statement", ""),
            source=KnowledgeSource.BELIEF,
            source_id=belief.get("node_id", belief["id"]),
            confidence=confidence,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "author": belief.get("author", ""),
                "debate_id": belief.get("debate_id", ""),
                "centrality": belief.get("centrality", 0.0),
                "prior_confidence": belief.get("prior_confidence", 0.5),
                "update_count": belief.get("update_count", 0),
            },
            importance=confidence_val,
        )

    def crux_to_knowledge_item(self, crux: dict[str, Any]) -> KnowledgeItem:
        """
        Convert a crux dict to a KnowledgeItem.

        Args:
            crux: The crux dictionary

        Returns:
            KnowledgeItem for unified knowledge mound API
        """
        from aragora.knowledge.unified.types import (
            ConfidenceLevel,
            KnowledgeItem,
            KnowledgeSource,
        )

        # Crux score maps to HIGH confidence (they are pivotal claims)
        crux_score = crux.get("crux_score", 0.5)
        if crux_score >= 0.7:
            confidence = ConfidenceLevel.HIGH
        elif crux_score >= 0.5:
            confidence = ConfidenceLevel.MEDIUM
        else:
            confidence = ConfidenceLevel.LOW

        created_at = crux.get("created_at")
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            except ValueError:
                created_at = datetime.now(timezone.utc)
        elif created_at is None:
            created_at = datetime.now(timezone.utc)

        return KnowledgeItem(
            id=crux["id"],
            content=crux.get("statement", ""),
            source=KnowledgeSource.BELIEF,  # Cruxes are a type of belief
            source_id=crux.get("claim_id", crux["id"]),
            confidence=confidence,
            created_at=created_at,
            updated_at=created_at,
            metadata={
                "author": crux.get("author", ""),
                "debate_id": crux.get("debate_id", ""),
                "crux_score": crux_score,
                "influence_score": crux.get("influence_score", 0.0),
                "disagreement_score": crux.get("disagreement_score", 0.0),
                "resolution_impact": crux.get("resolution_impact", 0.0),
                "topics": crux.get("topics", []),
                "is_crux": True,
            },
            importance=crux_score,
        )

    def get_stats(self) -> dict[str, Any]:
        """Get statistics about stored beliefs and cruxes."""
        self.__init_reverse_flow_state()
        return {
            "total_beliefs": len(self._beliefs),
            "total_cruxes": len(self._cruxes),
            "total_provenance_chains": len(self._provenance),
            "debates_with_beliefs": len(self._debate_beliefs),
            "debates_with_cruxes": len(self._debate_cruxes),
            "topics_indexed": len(self._topic_cruxes),
            # Reverse flow stats
            "km_validations_applied": self._km_validations_applied,
            "km_threshold_updates": self._km_threshold_updates,
            "km_priors_computed": len(self._km_validated_priors),
        }

    # ========================================================================
    # Reverse Flow Methods (KM → BeliefNetwork)
    # ========================================================================

    def __init_reverse_flow_state(self) -> None:
        """Initialize reverse flow state if not already done."""
        if not hasattr(self, "_km_validations_applied"):
            self._km_validations_applied = 0
        if not hasattr(self, "_km_threshold_updates"):
            self._km_threshold_updates = 0
        if not hasattr(self, "_km_validated_priors"):
            self._km_validated_priors: dict[str, KMPriorRecommendation] = {}
        if not hasattr(self, "_km_validations"):
            self._km_validations: list[KMBeliefValidation] = []
        if not hasattr(self, "_outcome_history"):
            self._outcome_history: dict[str, list[dict[str, Any]]] = {}

    def record_outcome(
        self,
        belief_id: str,
        debate_id: str,
        was_successful: bool,
        confidence: float = 0.7,
    ) -> None:
        """
        Record an outcome for a belief used in a debate.

        This enables outcome-based validation of beliefs.

        Args:
            belief_id: The belief ID
            debate_id: The debate where this belief was used
            was_successful: Whether the debate outcome was successful
            confidence: Confidence in the outcome assessment
        """
        self.__init_reverse_flow_state()

        if belief_id not in self._outcome_history:
            self._outcome_history[belief_id] = []

        self._outcome_history[belief_id].append(
            {
                "debate_id": debate_id,
                "was_successful": was_successful,
                "confidence": confidence,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def update_belief_thresholds_from_km(
        self,
        km_items: list[dict[str, Any]],
        min_confidence: float = 0.7,
    ) -> KMThresholdUpdate:
        """
        Reverse flow: Analyze KM patterns to update belief network thresholds.

        Examines KM patterns to determine optimal thresholds for:
        - MIN_BELIEF_CONFIDENCE: What confidence level correlates with success?
        - MIN_CRUX_SCORE: What crux score indicates valuable cruxes?

        Args:
            km_items: KM items with outcome metadata to analyze
            min_confidence: Minimum confidence for threshold updates

        Returns:
            KMThresholdUpdate with recommended threshold changes
        """
        self.__init_reverse_flow_state()

        old_belief_threshold = self.MIN_BELIEF_CONFIDENCE
        old_crux_threshold = self.MIN_CRUX_SCORE

        # Analyze success rates at different confidence levels
        confidence_buckets: dict[str, list[bool]] = {
            "0.6-0.7": [],
            "0.7-0.8": [],
            "0.8-0.9": [],
            "0.9-1.0": [],
        }

        crux_buckets: dict[str, list[bool]] = {
            "0.2-0.3": [],
            "0.3-0.4": [],
            "0.4-0.5": [],
            "0.5+": [],
        }

        for item in km_items:
            meta = item.get("metadata", {})
            confidence_val = meta.get("confidence", item.get("confidence", 0.5))
            was_successful = meta.get("outcome_success", False)
            crux_score = meta.get("crux_score", 0.0)
            is_crux = meta.get("is_crux", False)

            # Bucket by confidence
            if 0.6 <= confidence_val < 0.7:
                confidence_buckets["0.6-0.7"].append(was_successful)
            elif 0.7 <= confidence_val < 0.8:
                confidence_buckets["0.7-0.8"].append(was_successful)
            elif 0.8 <= confidence_val < 0.9:
                confidence_buckets["0.8-0.9"].append(was_successful)
            elif confidence_val >= 0.9:
                confidence_buckets["0.9-1.0"].append(was_successful)

            # Bucket cruxes by score
            if is_crux and crux_score > 0:
                if 0.2 <= crux_score < 0.3:
                    crux_buckets["0.2-0.3"].append(was_successful)
                elif 0.3 <= crux_score < 0.4:
                    crux_buckets["0.3-0.4"].append(was_successful)
                elif 0.4 <= crux_score < 0.5:
                    crux_buckets["0.4-0.5"].append(was_successful)
                elif crux_score >= 0.5:
                    crux_buckets["0.5+"].append(was_successful)

        # Compute success rates per bucket
        def success_rate(bucket: list[bool]) -> float | None:
            if len(bucket) < 3:  # Need minimum samples
                return None
            return sum(bucket) / len(bucket)

        # Find optimal belief threshold
        new_belief_threshold = old_belief_threshold
        recommendation = "keep"
        adjustments_made = 0

        rates = {
            0.65: success_rate(confidence_buckets["0.6-0.7"]),
            0.75: success_rate(confidence_buckets["0.7-0.8"]),
            0.85: success_rate(confidence_buckets["0.8-0.9"]),
            0.95: success_rate(confidence_buckets["0.9-1.0"]),
        }

        # Find threshold where success rate is acceptable (>= 60%)
        valid_rates = {k: v for k, v in rates.items() if v is not None and v >= 0.6}
        if valid_rates:
            # Use lowest threshold that still gives good success rate
            new_belief_threshold = min(valid_rates.keys())
            if new_belief_threshold != old_belief_threshold:
                recommendation = (
                    "decrease" if new_belief_threshold < old_belief_threshold else "increase"
                )
                adjustments_made += 1

        # Find optimal crux threshold
        new_crux_threshold = old_crux_threshold
        crux_rates = {
            0.25: success_rate(crux_buckets["0.2-0.3"]),
            0.35: success_rate(crux_buckets["0.3-0.4"]),
            0.45: success_rate(crux_buckets["0.4-0.5"]),
            0.55: success_rate(crux_buckets["0.5+"]),
        }

        valid_crux_rates = {k: v for k, v in crux_rates.items() if v is not None and v >= 0.5}
        if valid_crux_rates:
            new_crux_threshold = min(valid_crux_rates.keys())
            if new_crux_threshold != old_crux_threshold:
                adjustments_made += 1

        # Apply new thresholds if confidence is high enough
        computed_confidence = min(
            len(km_items) / 100,  # More items = more confidence
            1.0,
        )

        if computed_confidence >= min_confidence:
            self.MIN_BELIEF_CONFIDENCE = new_belief_threshold
            self.MIN_CRUX_SCORE = new_crux_threshold
            self._km_threshold_updates += 1

        update = KMThresholdUpdate(
            old_belief_confidence_threshold=old_belief_threshold,
            new_belief_confidence_threshold=new_belief_threshold,
            old_crux_score_threshold=old_crux_threshold,
            new_crux_score_threshold=new_crux_threshold,
            patterns_analyzed=len(km_items),
            adjustments_made=adjustments_made,
            confidence=computed_confidence,
            recommendation=recommendation,
            metadata={
                "confidence_rates": {k: v for k, v in rates.items() if v is not None},
                "crux_rates": {k: v for k, v in crux_rates.items() if v is not None},
            },
        )

        logger.info(
            f"Threshold update: belief {old_belief_threshold:.2f} → {new_belief_threshold:.2f}, "
            f"crux {old_crux_threshold:.2f} → {new_crux_threshold:.2f} ({recommendation})"
        )

        return update

    async def get_km_validated_priors(
        self,
        claim_type: str,
        km_items: list[dict[str, Any]] | None = None,
    ) -> KMPriorRecommendation:
        """
        Get KM-validated prior probability for a claim type.

        Analyzes historical outcomes to determine what prior probability
        should be assigned to claims of this type.

        Args:
            claim_type: Type of claim (e.g., "factual", "opinion", "prediction")
            km_items: Optional KM items to analyze (uses cached if not provided)

        Returns:
            KMPriorRecommendation with recommended prior
        """
        self.__init_reverse_flow_state()

        # Check cache first
        if claim_type in self._km_validated_priors and km_items is None:
            return self._km_validated_priors[claim_type]

        # Analyze items for this claim type
        matching_items = []
        supporting_debates = []

        items_to_analyze = km_items or []

        for item in items_to_analyze:
            meta = item.get("metadata", {})
            item_type = meta.get("claim_type", "")

            if item_type.lower() == claim_type.lower():
                matching_items.append(item)
                if debate_id := meta.get("debate_id"):
                    supporting_debates.append(debate_id)

        # Compute recommended prior from success rates
        if not matching_items:
            # Default prior for unknown types
            return KMPriorRecommendation(
                claim_type=claim_type,
                recommended_prior=0.5,
                sample_count=0,
                confidence=0.5,
                supporting_debates=[],
                metadata={"source": "default"},
            )

        # Calculate success-weighted prior
        success_count = 0
        total_weight = 0.0

        for item in matching_items:
            meta = item.get("metadata", {})
            was_successful = meta.get("outcome_success", False)
            confidence = meta.get("confidence", 0.5)

            if was_successful:
                success_count += 1
            total_weight += confidence

        # Prior is weighted success rate
        recommended_prior = success_count / len(matching_items) if matching_items else 0.5

        # Confidence based on sample size
        sample_confidence = min(len(matching_items) / 20, 1.0)

        recommendation = KMPriorRecommendation(
            claim_type=claim_type,
            recommended_prior=recommended_prior,
            sample_count=len(matching_items),
            confidence=sample_confidence,
            supporting_debates=list(set(supporting_debates)),
            metadata={
                "success_count": success_count,
                "total_items": len(matching_items),
                "avg_confidence": total_weight / len(matching_items) if matching_items else 0.0,
            },
        )

        # Cache the result
        self._km_validated_priors[claim_type] = recommendation

        return recommendation

    async def validate_belief_from_km(
        self,
        belief_id: str,
        km_cross_references: list[dict[str, Any]],
    ) -> KMBeliefValidation:
        """
        Validate a belief based on KM cross-references.

        Examines how this belief relates to other KM items to determine
        if it should be boosted, penalized, or flagged for review.

        Args:
            belief_id: The belief ID to validate
            km_cross_references: Related KM items for cross-referencing

        Returns:
            KMBeliefValidation with recommendation
        """
        self.__init_reverse_flow_state()

        belief = self.get_belief(belief_id)
        if not belief:
            return KMBeliefValidation(
                belief_id=belief_id,
                km_confidence=0.0,
                recommendation="review",
                metadata={"error": "belief_not_found"},
            )

        # Analyze cross-references
        support_count = 0
        contradiction_count = 0
        success_outcomes = 0
        total_outcomes = 0
        debate_ids = set()

        for ref in km_cross_references:
            meta = ref.get("metadata", {})
            relationship = meta.get("relationship", "")

            if relationship == "supports":
                support_count += 1
            elif relationship == "contradicts":
                contradiction_count += 1

            if debate_id := meta.get("debate_id"):
                debate_ids.add(debate_id)

            if "outcome_success" in meta:
                total_outcomes += 1
                if meta["outcome_success"]:
                    success_outcomes += 1

        # Also check recorded outcome history
        if belief_id in self._outcome_history:
            for outcome in self._outcome_history[belief_id]:
                total_outcomes += 1
                if outcome["was_successful"]:
                    success_outcomes += 1
                debate_ids.add(outcome["debate_id"])

        # Compute metrics
        cross_debate_frequency = len(debate_ids)
        outcome_success_rate = success_outcomes / total_outcomes if total_outcomes > 0 else 0.0
        was_contradicted = contradiction_count > support_count
        was_supported = support_count > contradiction_count

        # Determine recommendation and adjustment
        if was_contradicted and contradiction_count >= 3:
            recommendation = "penalize"
            adjustment = -0.1 * min(contradiction_count / 5, 1.0)
        elif was_supported and support_count >= 3 and outcome_success_rate >= 0.6:
            recommendation = "boost"
            adjustment = 0.1 * min(support_count / 5, 1.0) * outcome_success_rate
        elif total_outcomes >= 5 and outcome_success_rate < 0.3:
            recommendation = "review"
            adjustment = -0.05
        else:
            recommendation = "keep"
            adjustment = 0.0

        # KM confidence based on evidence
        km_confidence = 0.5
        if total_outcomes > 0:
            km_confidence = 0.5 + (outcome_success_rate - 0.5) * min(total_outcomes / 10, 1.0)
        if was_supported:
            km_confidence += 0.1 * min(support_count / 5, 1.0)
        if was_contradicted:
            km_confidence -= 0.1 * min(contradiction_count / 5, 1.0)
        km_confidence = max(0.0, min(1.0, km_confidence))

        validation = KMBeliefValidation(
            belief_id=belief_id,
            km_confidence=km_confidence,
            outcome_success_rate=outcome_success_rate,
            cross_debate_frequency=cross_debate_frequency,
            was_contradicted=was_contradicted,
            was_supported=was_supported,
            recommendation=recommendation,
            adjustment=adjustment,
            metadata={
                "support_count": support_count,
                "contradiction_count": contradiction_count,
                "success_outcomes": success_outcomes,
                "total_outcomes": total_outcomes,
            },
        )

        self._km_validations.append(validation)
        self._km_validations_applied += 1

        return validation

    async def apply_km_validation(
        self,
        validation: KMBeliefValidation,
    ) -> bool:
        """
        Apply a KM validation to update the belief's stored confidence.

        Args:
            validation: The validation result to apply

        Returns:
            True if applied successfully
        """
        self.__init_reverse_flow_state()

        belief = self._beliefs.get(validation.belief_id)
        if not belief:
            # Try with prefix
            prefixed_id = f"{self.BELIEF_PREFIX}{validation.belief_id}"
            belief = self._beliefs.get(prefixed_id)
            if not belief:
                return False

        # Apply adjustment
        old_confidence = belief.get("confidence", 0.5)
        new_confidence = max(0.0, min(1.0, old_confidence + validation.adjustment))

        belief["confidence"] = new_confidence
        belief["km_validated"] = True
        belief["km_validation_time"] = datetime.now(timezone.utc).isoformat()
        belief["km_confidence"] = validation.km_confidence

        if "metadata" not in belief:
            belief["metadata"] = {}
        belief["metadata"]["km_validation"] = {
            "recommendation": validation.recommendation,
            "adjustment": validation.adjustment,
            "old_confidence": old_confidence,
            "new_confidence": new_confidence,
        }

        logger.info(
            f"Applied KM validation to {validation.belief_id}: "
            f"{old_confidence:.2f} → {new_confidence:.2f} ({validation.recommendation})"
        )

        return True

    async def sync_validations_from_km(
        self,
        km_items: list[dict[str, Any]],
        min_confidence: float = 0.7,
    ) -> BeliefThresholdSyncResult:
        """
        Batch sync KM validations to belief network.

        Args:
            km_items: KM items with validation data
            min_confidence: Minimum confidence for applying validations

        Returns:
            BeliefThresholdSyncResult with sync details
        """
        import time

        self.__init_reverse_flow_state()

        start_time = time.time()
        result = BeliefThresholdSyncResult()
        errors = []

        # Group items by belief_id
        items_by_belief: dict[str, list[dict[str, Any]]] = {}
        for item in km_items:
            meta = item.get("metadata", {})
            belief_id = meta.get("belief_id") or meta.get("source_id")
            if belief_id:
                if belief_id not in items_by_belief:
                    items_by_belief[belief_id] = []
                items_by_belief[belief_id].append(item)

        # Validate each belief
        for belief_id, cross_refs in items_by_belief.items():
            try:
                # Check if this is a crux or belief
                if belief_id.startswith(self.CRUX_PREFIX) or any(
                    r.get("metadata", {}).get("is_crux") for r in cross_refs
                ):
                    result.cruxes_analyzed += 1
                else:
                    result.beliefs_analyzed += 1

                validation = await self.validate_belief_from_km(belief_id, cross_refs)
                result.validation_results.append(validation)

                # Apply if confidence is high enough
                if validation.km_confidence >= min_confidence and validation.adjustment != 0:
                    await self.apply_km_validation(validation)

            except (RuntimeError, ValueError, OSError, AttributeError) as e:
                errors.append(f"Error validating {belief_id}: {e}")

        # Also update thresholds
        try:
            threshold_update = await self.update_belief_thresholds_from_km(km_items, min_confidence)
            result.threshold_updates.append(threshold_update)
        except (RuntimeError, ValueError, OSError, AttributeError) as e:
            errors.append(f"Error updating thresholds: {e}")

        result.errors = errors
        result.duration_ms = (time.time() - start_time) * 1000

        return result

    def get_reverse_flow_stats(self) -> dict[str, Any]:
        """Get statistics about reverse flow operations."""
        self.__init_reverse_flow_state()

        return {
            "km_validations_applied": self._km_validations_applied,
            "km_threshold_updates": self._km_threshold_updates,
            "km_priors_computed": len(self._km_validated_priors),
            "validations_stored": len(self._km_validations),
            "outcome_history_size": sum(len(v) for v in self._outcome_history.values()),
            "current_belief_threshold": self.MIN_BELIEF_CONFIDENCE,
            "current_crux_threshold": self.MIN_CRUX_SCORE,
        }

    def clear_reverse_flow_state(self) -> None:
        """Clear all reverse flow state (for testing)."""
        self._km_validations_applied = 0
        self._km_threshold_updates = 0
        self._km_validated_priors = {}
        self._km_validations = []
        self._outcome_history = {}
        # Reset thresholds to defaults
        self.MIN_BELIEF_CONFIDENCE = 0.8
        self.MIN_CRUX_SCORE = 0.3


__all__ = [
    "BeliefAdapter",
    "BeliefSearchResult",
    "CruxSearchResult",
    # Reverse flow dataclasses
    "KMThresholdUpdate",
    "KMBeliefValidation",
    "KMPriorRecommendation",
    "BeliefThresholdSyncResult",
]
