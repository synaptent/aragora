"""
MCP Tools for Knowledge Mound operations.

Provides tools for querying and managing the Knowledge Mound:
- query_knowledge: Search the knowledge graph
- store_knowledge: Add new knowledge nodes
- get_knowledge_stats: Get knowledge base statistics
- get_decision_receipt: Get a formal decision receipt
- verify_decision_receipt: Verify receipt signature and integrity
"""

from __future__ import annotations

import logging
import time
from typing import Any, cast

from aragora.knowledge.mound import KnowledgeMound, get_knowledge_mound

logger = logging.getLogger(__name__)


async def query_knowledge_tool(
    query: str,
    node_types: str = "all",
    min_confidence: float = 0.0,
    limit: int = 10,
    include_relationships: bool = False,
) -> dict[str, Any]:
    """
    Query the Knowledge Mound for relevant information.

    Args:
        query: Search query text
        node_types: Comma-separated node types (fact, insight, claim, evidence, decision)
        min_confidence: Minimum confidence threshold (0-1)
        limit: Maximum results to return
        include_relationships: Whether to include related nodes

    Returns:
        Dict with nodes, count, and query metadata
    """
    results: list[dict[str, Any]] = []

    try:
        from aragora.knowledge.mound.types import QueryFilters

        mound: KnowledgeMound = get_knowledge_mound()

        # Build filters if needed
        filters = None
        if min_confidence > 0.0:
            filters = QueryFilters(min_importance=min_confidence)

        # Query the mound - returns QueryResult with items attribute
        try:
            query_result = await mound.query(
                query=query,
                filters=filters,
                limit=limit,
            )
        except RuntimeError as exc:
            if "not initialized" not in str(exc).lower() or not hasattr(mound, "initialize"):
                raise
            await mound.initialize()
            query_result = await mound.query(
                query=query,
                filters=filters,
                limit=limit,
            )

        # Iterate over items in the result
        for item in query_result.items:
            # Get node_type from metadata
            node_type = item.metadata.get("node_type", item.source.value)
            tier = item.metadata.get("tier", "medium")
            topics = item.metadata.get("topics", [])

            # Filter by node_types if specified
            if node_types != "all":
                types_filter = [t.strip() for t in node_types.split(",")]
                if node_type not in types_filter:
                    continue

            result_item = {
                "id": item.id,
                "content": item.content[:500] if len(item.content) > 500 else item.content,
                "node_type": node_type,
                "confidence": item.confidence.value
                if hasattr(item.confidence, "value")
                else item.confidence,
                "tier": tier,
                "created_at": (
                    item.created_at.isoformat()
                    if hasattr(item.created_at, "isoformat")
                    else str(item.created_at)
                ),
                "topics": topics[:5] if topics else [],
            }

            if include_relationships:
                # Get relationships via query_graph if available
                try:
                    graph_result = await mound.query_graph(start_id=item.id, depth=1, max_nodes=6)
                    result_item["relationships"] = [
                        {
                            "type": edge.relationship.value
                            if hasattr(edge.relationship, "value")
                            else str(edge.relationship),
                            "target_id": edge.target_id,
                            "weight": edge.confidence,
                        }
                        for edge in graph_result.edges[:5]
                    ]
                except (RuntimeError, ValueError, OSError, AttributeError) as exc:
                    logger.debug("Failed to retrieve knowledge relationships: %s", exc)
                    result_item["relationships"] = []

            results.append(result_item)

    except ImportError:
        logger.warning("Knowledge Mound not available")
    except (RuntimeError, ValueError, OSError, AttributeError) as e:
        logger.error("Knowledge query failed: %s", e)
        return {
            "error": "Knowledge query failed",
            "query": query,
        }

    return {
        "nodes": results,
        "count": len(results),
        "query": query,
        "filters": {
            "node_types": node_types,
            "min_confidence": min_confidence,
        },
    }


async def store_knowledge_tool(
    content: str,
    node_type: str = "fact",
    confidence: float = 0.8,
    tier: str = "medium",
    topics: str = "",
    source_debate_id: str | None = None,
) -> dict[str, Any]:
    """
    Store a new knowledge node in the Knowledge Mound.

    Args:
        content: The knowledge content to store
        node_type: Type of node (fact, insight, claim, evidence, decision)
        confidence: Confidence level (0-1)
        tier: Storage tier (fast, medium, slow, glacial)
        topics: Comma-separated topics
        source_debate_id: Optional source debate ID

    Returns:
        Dict with stored node ID and metadata
    """
    valid_types = {"fact", "insight", "claim", "evidence", "decision", "opinion"}
    valid_tiers = {"fast", "medium", "slow", "glacial"}

    if node_type not in valid_types:
        return {"error": f"Invalid node_type. Must be one of: {valid_types}"}

    if tier not in valid_tiers:
        return {"error": f"Invalid tier. Must be one of: {valid_tiers}"}

    if not 0 <= confidence <= 1:
        return {"error": "Confidence must be between 0 and 1"}

    try:
        mound: KnowledgeMound = get_knowledge_mound()

        # Parse topics
        topics_list = [t.strip() for t in topics.split(",") if t.strip()] if topics else []

        # Build metadata
        metadata: dict[str, Any] = {
            "node_type": node_type,
            "tier": tier,
            "topics": topics_list,
            "stored_via": "mcp_tool",
        }
        if source_debate_id:
            metadata["source_debate_id"] = source_debate_id

        # Store the node using add() method
        node_id = await mound.add(
            content=content,
            metadata=metadata,
            node_type=node_type,
            confidence=confidence,
            tier=tier,
        )

        return {
            "node_id": node_id,
            "stored": True,
            "node_type": node_type,
            "confidence": confidence,
            "tier": tier,
            "topics": topics_list,
        }

    except ImportError:
        logger.warning("Knowledge Mound not available")
        return {"error": "Knowledge Mound module not available"}
    except (RuntimeError, ValueError, OSError) as e:
        logger.error("Failed to store knowledge: %s", e)
        return {"error": "Failed to store knowledge"}


async def get_knowledge_stats_tool() -> dict[str, Any]:
    """
    Get statistics about the Knowledge Mound.

    Returns:
        Dict with node counts, tier utilization, and health metrics
    """
    try:
        mound: KnowledgeMound = get_knowledge_mound()
        stats = await mound.get_stats()

        # get_stats returns a MoundStats dataclass, convert to dict
        if hasattr(stats, "total_nodes"):
            return {
                "total_nodes": stats.total_nodes,
                "total_relationships": stats.total_relationships,
                "nodes_by_type": stats.nodes_by_type,
                "nodes_by_tier": stats.nodes_by_tier,
                "avg_confidence": stats.average_confidence,
                "stale_nodes_count": stats.stale_nodes_count,
                "workspace_id": stats.workspace_id,
            }
        else:
            # Fallback if stats is a dict (legacy compatibility);
            # stats may be MoundStats or plain dict depending on backend version
            stats_dict: dict[str, Any] = cast(dict[str, Any], stats)
            return {
                "total_nodes": stats_dict.get("total_nodes", 0),
                "total_relationships": stats_dict.get("total_relationships", 0),
                "nodes_by_type": stats_dict.get("nodes_by_type", {}),
                "nodes_by_tier": stats_dict.get("nodes_by_tier", {}),
                "avg_confidence": stats_dict.get("avg_confidence", 0),
                "stale_nodes_count": stats_dict.get("stale_nodes_count", 0),
                "last_updated": stats_dict.get("last_updated", "unknown"),
            }

    except ImportError:
        logger.warning("Knowledge Mound not available")
        return {
            "error": "Knowledge Mound module not available",
            "total_nodes": 0,
        }
    except (RuntimeError, ValueError, OSError, AttributeError) as e:
        logger.error("Failed to get knowledge stats: %s", e)
        return {"error": "Failed to retrieve knowledge stats"}


async def get_decision_receipt_tool(
    debate_id: str,
    format: str = "json",
    include_proofs: bool = True,
    include_evidence: bool = True,
) -> dict[str, Any]:
    """
    Get a formal decision receipt for a completed debate.

    A decision receipt provides an auditable record of:
    - The question/decision made
    - Participating agents
    - Final consensus
    - Confidence level
    - Supporting evidence
    - Formal proofs (if available)

    Args:
        debate_id: ID of the debate
        format: Output format (json, markdown, pdf)
        include_proofs: Include formal verification proofs
        include_evidence: Include cited evidence

    Returns:
        Dict with the decision receipt
    """
    try:
        from aragora.storage.debate_storage import get_debates_db

        db = get_debates_db()
        if not db:
            return {"error": "Debates database not available"}

        debate = db.get(debate_id)
        if not debate:
            return {"error": f"Debate {debate_id} not found"}

        # Build the receipt
        receipt: dict[str, Any] = {
            "receipt_id": f"receipt_{debate_id}_{int(time.time())}",
            "debate_id": debate_id,
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S UTC"),
            "question": debate.get("task", "Unknown"),
            "decision": {
                "answer": debate.get("final_answer", "No answer"),
                "consensus_reached": debate.get("consensus_reached", False),
                "confidence": debate.get("confidence", 0),
                "confidence_percent": f"{debate.get('confidence', 0) * 100:.1f}%",
            },
            "process": {
                "rounds_used": debate.get("rounds_used", 0),
                "agents": debate.get("participants", []),
                "protocol": debate.get("protocol", "standard"),
            },
        }

        # Add proofs if requested
        if include_proofs:
            receipt["proofs"] = debate.get("proofs", [])

        # Add evidence if requested
        if include_evidence:
            receipt["evidence"] = debate.get("evidence", [])

        # Add verification status
        if debate.get("verified"):
            receipt["verification"] = {
                "verified": True,
                "verification_method": debate.get("verification_method", "unknown"),
                "verified_at": debate.get("verified_at", "unknown"),
            }

        # Format conversion
        if format == "markdown":
            receipt["formatted"] = _format_receipt_markdown(receipt)
        elif format == "pdf":
            receipt["note"] = "PDF generation requires additional processing"

        return receipt

    except (RuntimeError, ValueError, OSError, KeyError) as e:
        logger.error("Failed to generate decision receipt: %s", e)
        return {"error": "Receipt generation failed"}


async def verify_decision_receipt_tool(
    receipt_id: str,
    verify_signature: bool = True,
    verify_integrity: bool = True,
) -> dict[str, Any]:
    """
    Verify a decision receipt's signature and integrity checksum.

    Args:
        receipt_id: Receipt ID to verify
        verify_signature: Whether to verify cryptographic signature
        verify_integrity: Whether to verify checksum integrity

    Returns:
        Dict with verification results
    """
    if not receipt_id:
        return {"error": "receipt_id is required"}

    try:
        from aragora.storage.receipt_store import get_receipt_store

        store = get_receipt_store()
        if not store:
            return {"error": "Receipt store not available"}

        result: dict[str, Any] = {"receipt_id": receipt_id}

        if verify_signature:
            signature_result = store.verify_signature(receipt_id)
            result["signature"] = (
                signature_result.to_dict()
                if hasattr(signature_result, "to_dict")
                else signature_result
            )

        if verify_integrity:
            result["integrity"] = store.verify_integrity(receipt_id)

        if not verify_signature and not verify_integrity:
            result["warning"] = "No verification requested"

        return result

    except (RuntimeError, ValueError, OSError) as e:
        logger.error("Receipt verification failed: %s", e)
        return {"error": "Receipt verification failed"}


async def build_decision_integrity_tool(
    debate_id: str,
    include_receipt: bool = True,
    include_plan: bool = True,
    include_context: bool = False,
    plan_strategy: str = "single_task",
) -> dict[str, Any]:
    """
    Build a Decision Integrity package for a completed debate.

    This bundles:
    - Decision receipt (audit trail)
    - Implementation plan (task breakdown)
    - Optional context snapshot (memory/knowledge state)

    Args:
        debate_id: ID of the debate
        include_receipt: Include decision receipt
        include_plan: Include implementation plan
        include_context: Include context snapshot
        plan_strategy: "single_task" (default) or "gemini" (best-effort)

    Returns:
        Dict with the Decision Integrity package
    """
    try:
        from aragora.storage.debate_storage import get_debates_db
        from aragora.pipeline.decision_integrity import build_decision_integrity_package

        db = get_debates_db()
        if not db:
            return {"error": "Debates database not available"}

        debate = db.get(debate_id)
        if not debate:
            return {"error": f"Debate {debate_id} not found"}

        package = await build_decision_integrity_package(
            debate,
            include_receipt=include_receipt,
            include_plan=include_plan,
            include_context=include_context,
            plan_strategy=plan_strategy,
        )
        return package.to_dict()

    except (RuntimeError, ValueError, OSError, ImportError) as e:
        logger.error("Failed to build decision integrity package: %s", e)
        return {"error": "Decision integrity build failed"}


def _format_receipt_markdown(receipt: dict[str, Any]) -> str:
    """Format a decision receipt as markdown."""
    md = f"""# Decision Receipt

**Receipt ID:** {receipt["receipt_id"]}
**Generated:** {receipt["generated_at"]}

## Decision

**Question:** {receipt["question"]}

**Answer:** {receipt["decision"]["answer"]}

- Consensus Reached: {"Yes" if receipt["decision"]["consensus_reached"] else "No"}
- Confidence: {receipt["decision"]["confidence_percent"]}

## Process

- Rounds Used: {receipt["process"]["rounds_used"]}
- Agents: {", ".join(receipt["process"]["agents"])}
- Protocol: {receipt["process"]["protocol"]}
"""

    if receipt.get("proofs"):
        md += f"\n## Proofs\n\n{len(receipt['proofs'])} formal proofs available\n"

    if receipt.get("evidence"):
        md += f"\n## Evidence\n\n{len(receipt['evidence'])} evidence items cited\n"

    if receipt.get("verification"):
        md += (
            f"\n## Verification\n\nVerified via {receipt['verification']['verification_method']}\n"
        )

    return md


# Export all tools
__all__ = [
    "query_knowledge_tool",
    "store_knowledge_tool",
    "get_knowledge_stats_tool",
    "get_decision_receipt_tool",
    "verify_decision_receipt_tool",
    "build_decision_integrity_tool",
]
