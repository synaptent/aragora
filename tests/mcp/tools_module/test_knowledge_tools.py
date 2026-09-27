"""Tests for MCP knowledge tools execution logic."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.mcp.tools_module.knowledge import (
    build_decision_integrity_tool,
    get_decision_receipt_tool,
    get_knowledge_stats_tool,
    query_knowledge_tool,
    store_knowledge_tool,
    verify_decision_receipt_tool,
)


class TestQueryKnowledgeTool:
    """Tests for query_knowledge_tool."""

    @pytest.mark.asyncio
    async def test_query_success(self):
        """Test successful knowledge query."""
        mock_item = MagicMock()
        mock_item.id = "node-123"
        mock_item.content = "Test knowledge content"
        mock_item.confidence = MagicMock(value=0.9)
        mock_item.source = MagicMock(value="debate")
        mock_item.metadata = {"node_type": "fact", "tier": "medium", "topics": ["AI"]}
        mock_item.created_at = datetime.now()

        mock_query_result = MagicMock()
        mock_query_result.items = [mock_item]

        mock_mound = AsyncMock()
        mock_mound.query.return_value = mock_query_result

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await query_knowledge_tool(query="test query")

        assert result["count"] == 1
        assert result["query"] == "test query"
        assert len(result["nodes"]) == 1
        assert result["nodes"][0]["id"] == "node-123"
        assert result["nodes"][0]["node_type"] == "fact"
        assert result["nodes"][0]["confidence"] == 0.9

    @pytest.mark.asyncio
    async def test_query_with_filters(self):
        """Test query with filters."""
        mock_query_result = MagicMock()
        mock_query_result.items = []

        mock_mound = AsyncMock()
        mock_mound.query.return_value = mock_query_result

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await query_knowledge_tool(
                query="test",
                node_types="fact,insight",
                min_confidence=0.5,
                limit=5,
            )

        assert result["filters"]["node_types"] == "fact,insight"
        assert result["filters"]["min_confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_query_with_relationships(self):
        """Test query including relationships."""
        mock_edge = MagicMock()
        mock_edge.relationship = MagicMock(value="supports")
        mock_edge.target_id = "node-456"
        mock_edge.confidence = 0.8

        mock_graph_result = MagicMock()
        mock_graph_result.edges = [mock_edge]

        mock_item = MagicMock()
        mock_item.id = "node-123"
        mock_item.content = "Content"
        mock_item.confidence = MagicMock(value=0.9)
        mock_item.source = MagicMock(value="debate")
        mock_item.metadata = {"node_type": "fact", "tier": "medium", "topics": []}
        mock_item.created_at = datetime.now()

        mock_query_result = MagicMock()
        mock_query_result.items = [mock_item]

        mock_mound = AsyncMock()
        mock_mound.query.return_value = mock_query_result
        mock_mound.query_graph.return_value = mock_graph_result

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await query_knowledge_tool(
                query="test",
                include_relationships=True,
            )

        assert len(result["nodes"]) == 1
        assert "relationships" in result["nodes"][0]
        assert len(result["nodes"][0]["relationships"]) == 1
        assert result["nodes"][0]["relationships"][0]["type"] == "supports"

    @pytest.mark.asyncio
    async def test_query_filters_by_node_type(self):
        """Test that node_types filter is applied."""
        mock_item_fact = MagicMock()
        mock_item_fact.id = "node-1"
        mock_item_fact.content = "Fact content"
        mock_item_fact.confidence = MagicMock(value=0.9)
        mock_item_fact.source = MagicMock(value="debate")
        mock_item_fact.metadata = {"node_type": "fact", "tier": "medium", "topics": []}
        mock_item_fact.created_at = datetime.now()

        mock_item_insight = MagicMock()
        mock_item_insight.id = "node-2"
        mock_item_insight.content = "Insight content"
        mock_item_insight.confidence = MagicMock(value=0.8)
        mock_item_insight.source = MagicMock(value="debate")
        mock_item_insight.metadata = {"node_type": "insight", "tier": "medium", "topics": []}
        mock_item_insight.created_at = datetime.now()

        mock_query_result = MagicMock()
        mock_query_result.items = [mock_item_fact, mock_item_insight]

        mock_mound = AsyncMock()
        mock_mound.query.return_value = mock_query_result

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await query_knowledge_tool(query="test", node_types="fact")

        # Only the fact should be returned
        assert result["count"] == 1
        assert result["nodes"][0]["node_type"] == "fact"

    @pytest.mark.asyncio
    async def test_query_truncates_long_content(self):
        """Test that long content is truncated."""
        long_content = "x" * 1000

        mock_item = MagicMock()
        mock_item.id = "node-123"
        mock_item.content = long_content
        mock_item.confidence = MagicMock(value=0.9)
        mock_item.source = MagicMock(value="debate")
        mock_item.metadata = {"node_type": "fact", "tier": "medium", "topics": []}
        mock_item.created_at = datetime.now()

        mock_query_result = MagicMock()
        mock_query_result.items = [mock_item]

        mock_mound = AsyncMock()
        mock_mound.query.return_value = mock_query_result

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await query_knowledge_tool(query="test")

        assert len(result["nodes"][0]["content"]) == 500

    @pytest.mark.asyncio
    async def test_query_import_error(self):
        """Test graceful handling when KnowledgeMound not available."""
        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            side_effect=ImportError("Not installed"),
        ):
            result = await query_knowledge_tool(query="test")

        assert result["count"] == 0
        assert result["nodes"] == []

    @pytest.mark.asyncio
    async def test_query_exception_returns_error(self):
        """Test that exceptions return error dict."""
        mock_mound = AsyncMock()
        mock_mound.query.side_effect = RuntimeError("Database error")

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await query_knowledge_tool(query="test")

        assert "error" in result


class TestDecisionIntegrityTool:
    """Tests for build_decision_integrity_tool."""

    @pytest.mark.asyncio
    async def test_build_decision_integrity_missing_db(self):
        """Returns error when debate DB is unavailable."""
        with patch("aragora.storage.debate_storage.get_debates_db", return_value=None):
            result = await build_decision_integrity_tool(debate_id="debate_1")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_build_decision_integrity_not_found(self):
        """Returns error when debate does not exist."""
        mock_db = MagicMock()
        mock_db.get.return_value = None
        with patch("aragora.storage.debate_storage.get_debates_db", return_value=mock_db):
            result = await build_decision_integrity_tool(debate_id="missing")
        assert "error" in result


class TestDecisionReceiptVerificationTool:
    """Tests for verify_decision_receipt_tool."""

    @pytest.mark.asyncio
    async def test_verify_receipt_missing_id(self):
        """Requires receipt_id."""
        result = await verify_decision_receipt_tool(receipt_id="")
        assert "error" in result

    @pytest.mark.asyncio
    async def test_verify_receipt_signature_and_integrity(self):
        """Returns signature + integrity when enabled."""
        from aragora.storage.receipt_store import SignatureVerificationResult

        mock_store = MagicMock()
        mock_store.verify_signature.return_value = SignatureVerificationResult(
            receipt_id="receipt-1",
            is_valid=True,
            algorithm="Ed25519",
            key_id="key-1",
            signed_at=123.0,
        )
        mock_store.verify_integrity.return_value = {
            "receipt_id": "receipt-1",
            "integrity_valid": True,
            "stored_checksum": "abc",
            "computed_checksum": "abc",
        }

        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=mock_store):
            result = await verify_decision_receipt_tool(receipt_id="receipt-1")

        assert result["receipt_id"] == "receipt-1"
        assert result["signature"]["signature_valid"] is True
        assert result["integrity"]["integrity_valid"] is True

    @pytest.mark.asyncio
    async def test_verify_receipt_no_checks(self):
        """Warns when no verification is requested."""
        mock_store = MagicMock()
        with patch("aragora.storage.receipt_store.get_receipt_store", return_value=mock_store):
            result = await verify_decision_receipt_tool(
                receipt_id="receipt-2",
                verify_signature=False,
                verify_integrity=False,
            )

        assert result["receipt_id"] == "receipt-2"
        assert "warning" in result

    @pytest.mark.asyncio
    async def test_build_decision_integrity_success(self):
        """Returns decision integrity package for existing debate."""
        mock_db = MagicMock()
        mock_db.get.return_value = {
            "debate_id": "debate_1",
            "task": "Test task",
            "final_answer": "Test answer",
            "consensus_reached": True,
            "confidence": 0.8,
        }

        mock_package = MagicMock()
        mock_package.to_dict.return_value = {
            "debate_id": "debate_1",
            "receipt": {"receipt_id": "r1"},
            "plan": None,
        }

        with (
            patch("aragora.storage.debate_storage.get_debates_db", return_value=mock_db),
            patch(
                "aragora.pipeline.decision_integrity.build_decision_integrity_package",
                new=AsyncMock(return_value=mock_package),
            ),
        ):
            result = await build_decision_integrity_tool(debate_id="debate_1")

        assert result["debate_id"] == "debate_1"


class TestStoreKnowledgeTool:
    """Tests for store_knowledge_tool."""

    @pytest.mark.asyncio
    async def test_store_success(self):
        """Test successful knowledge storage."""
        mock_mound = AsyncMock()
        mock_mound.add.return_value = "node-new-123"

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await store_knowledge_tool(
                content="This is new knowledge",
                node_type="fact",
                confidence=0.85,
            )

        assert result["stored"] is True
        assert result["node_id"] == "node-new-123"
        assert result["node_type"] == "fact"
        assert result["confidence"] == 0.85

    @pytest.mark.asyncio
    async def test_store_invalid_node_type(self):
        """Test store with invalid node type."""
        result = await store_knowledge_tool(
            content="Test",
            node_type="invalid_type",
        )

        assert "error" in result
        assert "Invalid node_type" in result["error"]

    @pytest.mark.asyncio
    async def test_store_invalid_tier(self):
        """Test store with invalid tier."""
        result = await store_knowledge_tool(
            content="Test",
            node_type="fact",
            tier="invalid_tier",
        )

        assert "error" in result
        assert "Invalid tier" in result["error"]

    @pytest.mark.asyncio
    async def test_store_invalid_confidence(self):
        """Test store with invalid confidence."""
        result = await store_knowledge_tool(
            content="Test",
            node_type="fact",
            confidence=1.5,  # Out of range
        )

        assert "error" in result
        assert "Confidence must be between" in result["error"]

        result = await store_knowledge_tool(
            content="Test",
            node_type="fact",
            confidence=-0.1,  # Out of range
        )

        assert "error" in result
        assert "Confidence must be between" in result["error"]

    @pytest.mark.asyncio
    async def test_store_with_topics(self):
        """Test store with topics."""
        mock_mound = AsyncMock()
        mock_mound.add.return_value = "node-123"

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await store_knowledge_tool(
                content="Test",
                topics="AI, Machine Learning, NLP",
            )

        assert result["topics"] == ["AI", "Machine Learning", "NLP"]

    @pytest.mark.asyncio
    async def test_store_with_source_debate(self):
        """Test store with source debate ID."""
        mock_mound = AsyncMock()
        mock_mound.add.return_value = "node-123"

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await store_knowledge_tool(
                content="Test",
                source_debate_id="debate-456",
            )

        assert result["stored"] is True
        # Check that metadata was passed correctly
        call_kwargs = mock_mound.add.call_args.kwargs
        assert call_kwargs["metadata"]["source_debate_id"] == "debate-456"

    @pytest.mark.asyncio
    async def test_store_import_error(self):
        """Test graceful handling when KnowledgeMound not available."""
        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            side_effect=ImportError("Not installed"),
        ):
            result = await store_knowledge_tool(content="Test")

        assert "error" in result
        assert "not available" in result["error"].lower()


class TestGetKnowledgeStatsTool:
    """Tests for get_knowledge_stats_tool."""

    @pytest.mark.asyncio
    async def test_get_stats_success_dataclass(self):
        """Test getting stats when MoundStats is returned."""
        mock_stats = MagicMock()
        mock_stats.total_nodes = 100
        mock_stats.total_relationships = 50
        mock_stats.nodes_by_type = {"fact": 60, "insight": 40}
        mock_stats.nodes_by_tier = {"fast": 10, "medium": 80, "slow": 10}
        mock_stats.average_confidence = 0.85
        mock_stats.stale_nodes_count = 5
        mock_stats.workspace_id = "ws-123"

        mock_mound = AsyncMock()
        mock_mound.get_stats.return_value = mock_stats

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await get_knowledge_stats_tool()

        assert result["total_nodes"] == 100
        assert result["total_relationships"] == 50
        assert result["avg_confidence"] == 0.85
        assert result["stale_nodes_count"] == 5

    @pytest.mark.asyncio
    async def test_get_stats_success_dict_fallback(self):
        """Test getting stats when dict is returned (legacy)."""
        mock_stats = {
            "total_nodes": 50,
            "total_relationships": 25,
            "nodes_by_type": {"fact": 30, "insight": 20},
            "nodes_by_tier": {"medium": 50},
            "avg_confidence": 0.75,
            "stale_nodes_count": 2,
            "last_updated": "2024-01-01",
        }

        mock_mound = AsyncMock()
        mock_mound.get_stats.return_value = mock_stats

        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            return_value=mock_mound,
        ):
            result = await get_knowledge_stats_tool()

        assert result["total_nodes"] == 50
        assert result["avg_confidence"] == 0.75

    @pytest.mark.asyncio
    async def test_get_stats_import_error(self):
        """Test graceful handling when KnowledgeMound not available."""
        with patch(
            "aragora.mcp.tools_module.knowledge.get_knowledge_mound",
            side_effect=ImportError("Not installed"),
        ):
            result = await get_knowledge_stats_tool()

        assert "error" in result
        assert result["total_nodes"] == 0


class TestGetDecisionReceiptTool:
    """Tests for get_decision_receipt_tool."""

    @pytest.mark.asyncio
    async def test_get_receipt_success(self):
        """Test successful receipt generation."""
        mock_debate = {
            "task": "Which database to use?",
            "final_answer": "PostgreSQL",
            "consensus_reached": True,
            "confidence": 0.9,
            "rounds_used": 3,
            "participants": ["claude", "gpt4"],
            "protocol": "majority",
            "proofs": [{"type": "z3", "valid": True}],
            "evidence": [{"id": "ev-1", "title": "DB comparison"}],
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_decision_receipt_tool(debate_id="debate-123")

        assert "receipt_id" in result
        assert result["debate_id"] == "debate-123"
        assert result["question"] == "Which database to use?"
        assert result["decision"]["answer"] == "PostgreSQL"
        assert result["decision"]["consensus_reached"] is True
        assert result["decision"]["confidence"] == 0.9
        assert len(result["proofs"]) == 1
        assert len(result["evidence"]) == 1

    @pytest.mark.asyncio
    async def test_get_receipt_without_proofs(self):
        """Test receipt without including proofs."""
        mock_debate = {
            "task": "Test",
            "final_answer": "Answer",
            "proofs": [{"type": "z3"}],
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_decision_receipt_tool(
                debate_id="debate-123",
                include_proofs=False,
            )

        assert "proofs" not in result

    @pytest.mark.asyncio
    async def test_get_receipt_markdown_format(self):
        """Test receipt in markdown format."""
        mock_debate = {
            "task": "Test",
            "final_answer": "Answer",
            "consensus_reached": True,
            "confidence": 0.9,
            "rounds_used": 3,
            "participants": ["claude"],
            "protocol": "majority",
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_decision_receipt_tool(
                debate_id="debate-123",
                format="markdown",
            )

        assert "formatted" in result
        assert "# Decision Receipt" in result["formatted"]

    @pytest.mark.asyncio
    async def test_get_receipt_storage_not_available(self):
        """Test receipt when storage not available."""
        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=None,
        ):
            result = await get_decision_receipt_tool(debate_id="debate-123")

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_receipt_debate_not_found(self):
        """Test receipt when debate not found."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_decision_receipt_tool(debate_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_get_receipt_with_verification(self):
        """Test receipt includes verification info."""
        mock_debate = {
            "task": "Test",
            "final_answer": "Answer",
            "verified": True,
            "verification_method": "z3",
            "verified_at": "2024-01-01",
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_decision_receipt_tool(debate_id="debate-123")

        assert "verification" in result
        assert result["verification"]["verified"] is True
        assert result["verification"]["verification_method"] == "z3"
