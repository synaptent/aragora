"""Tests for MCP verification tools execution logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.mcp.tools_module.verification import (
    generate_proof_tool,
    get_consensus_proofs_tool,
    verify_consensus_tool,
)


class TestGetConsensusProofsTool:
    """Tests for get_consensus_proofs_tool."""

    @pytest.mark.asyncio
    async def test_get_proofs_with_debate_id(self):
        """Test getting proofs for specific debate."""
        mock_debate = {
            "proofs": [
                {"type": "z3", "valid": True, "statement": "theorem1"},
                {"type": "lean", "valid": True, "statement": "theorem2"},
            ]
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_consensus_proofs_tool(debate_id="debate-123")

        assert result["count"] == 2
        assert result["debate_id"] == "debate-123"
        assert len(result["proofs"]) == 2

    @pytest.mark.asyncio
    async def test_get_proofs_filter_by_type(self):
        """Test filtering proofs by type."""
        mock_debate = {
            "proofs": [
                {"type": "z3", "valid": True},
                {"type": "lean", "valid": True},
            ]
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_consensus_proofs_tool(
                debate_id="debate-123",
                proof_type="z3",
            )

        assert result["count"] == 1
        assert result["proofs"][0]["type"] == "z3"
        assert result["proof_type"] == "z3"

    @pytest.mark.asyncio
    async def test_get_proofs_respects_limit(self):
        """Test that limit is respected."""
        mock_debate = {
            "proofs": [
                {"type": "z3", "id": 1},
                {"type": "z3", "id": 2},
                {"type": "z3", "id": 3},
            ]
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_consensus_proofs_tool(
                debate_id="debate-123",
                limit=2,
            )

        assert result["count"] == 2

    @pytest.mark.asyncio
    async def test_get_proofs_no_debate_id(self):
        """Test getting proofs without debate_id returns empty."""
        result = await get_consensus_proofs_tool()

        assert result["count"] == 0
        assert result["debate_id"] == "(all debates)"

    @pytest.mark.asyncio
    async def test_get_proofs_debate_not_found(self):
        """Test when debate doesn't exist."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_consensus_proofs_tool(debate_id="nonexistent")

        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_get_proofs_debate_no_proofs(self):
        """Test when debate has no proofs."""
        mock_debate = {"task": "test"}  # No proofs key

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with patch(
            "aragora.storage.debate_storage.get_debates_db",
            return_value=mock_db,
        ):
            result = await get_consensus_proofs_tool(debate_id="debate-123")

        assert result["count"] == 0


class TestVerifyConsensusTool:
    """Tests for verify_consensus_tool."""

    @pytest.mark.asyncio
    async def test_verify_missing_debate_id(self):
        """Test verify with missing debate_id."""
        result = await verify_consensus_tool(debate_id="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_success(self):
        """Test successful consensus verification."""
        mock_debate = {
            "final_answer": "PostgreSQL is better for complex queries",
        }

        mock_result = MagicMock()
        mock_result.status = MagicMock(value="verified")
        mock_result.is_verified = True
        mock_result.language = MagicMock(value="z3")
        mock_result.formal_statement = "theorem db_query_complexity"
        mock_result.proof_hash = "abc123"
        mock_result.translation_time_ms = 150
        mock_result.proof_search_time_ms = 300

        mock_manager = AsyncMock()
        mock_manager.attempt_formal_verification.return_value = mock_result

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with (
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
            ),
            patch(
                "aragora.verification.formal.FormalVerificationManager",
                return_value=mock_manager,
            ),
        ):
            result = await verify_consensus_tool(debate_id="debate-123")

        assert result["debate_id"] == "debate-123"
        assert result["is_verified"] is True
        assert result["status"] == "verified"
        assert result["proof_hash"] == "abc123"

    @pytest.mark.asyncio
    async def test_verify_storage_not_available(self):
        """Test verify when storage not available."""
        with (
            patch(
                "aragora.verification.formal.FormalVerificationManager",
            ),
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=None,
            ),
        ):
            result = await verify_consensus_tool(debate_id="debate-123")

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_debate_not_found(self):
        """Test verify when debate not found."""
        mock_db = MagicMock()
        mock_db.get.return_value = None

        with (
            patch(
                "aragora.verification.formal.FormalVerificationManager",
            ),
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
            ),
        ):
            result = await verify_consensus_tool(debate_id="nonexistent")

        assert "error" in result
        assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_no_consensus(self):
        """Test verify when debate has no consensus."""
        mock_debate = {
            "task": "test question",
            "final_answer": "",  # Empty answer
        }

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with (
            patch(
                "aragora.verification.formal.FormalVerificationManager",
            ),
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
            ),
        ):
            result = await verify_consensus_tool(debate_id="debate-123")

        assert "error" in result
        assert "no consensus" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_import_error(self):
        """Test graceful handling when verification module not available."""
        with patch(
            "aragora.verification.formal.FormalVerificationManager",
            side_effect=ImportError("Not installed"),
        ):
            result = await verify_consensus_tool(debate_id="debate-123")

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_verify_exception_handling(self):
        """Test exception handling during verification."""
        mock_debate = {"final_answer": "test answer"}

        mock_manager = AsyncMock()
        mock_manager.attempt_formal_verification.side_effect = RuntimeError("Z3 error")

        mock_db = MagicMock()
        mock_db.get.return_value = mock_debate

        with (
            patch(
                "aragora.storage.debate_storage.get_debates_db",
                return_value=mock_db,
            ),
            patch(
                "aragora.verification.formal.FormalVerificationManager",
                return_value=mock_manager,
            ),
        ):
            result = await verify_consensus_tool(debate_id="debate-123")

        assert "error" in result
        assert "failed" in result["error"].lower()


class TestGenerateProofTool:
    """Tests for generate_proof_tool."""

    @pytest.mark.asyncio
    async def test_generate_missing_claim(self):
        """Test generate with missing claim."""
        result = await generate_proof_tool(claim="")
        assert "error" in result
        assert "required" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_generate_lean4_success(self):
        """Test successful Lean4 proof generation."""
        mock_backend = AsyncMock()
        mock_backend.translate.return_value = "theorem test : 1 + 1 = 2 := rfl"

        with patch(
            "aragora.verification.formal.LeanBackend",
            return_value=mock_backend,
        ):
            result = await generate_proof_tool(
                claim="One plus one equals two",
                output_format="lean4",
            )

        assert result["success"] is True
        assert result["format"] == "lean4"
        assert "theorem" in result["formal_statement"]
        assert result["confidence"] == 0.7

    @pytest.mark.asyncio
    async def test_generate_z3_success(self):
        """Test successful Z3 proof generation."""
        mock_backend = AsyncMock()
        mock_backend.translate.return_value = "(assert (= (+ 1 1) 2))"

        with patch(
            "aragora.verification.formal.Z3Backend",
            return_value=mock_backend,
        ):
            result = await generate_proof_tool(
                claim="One plus one equals two",
                output_format="z3_smt",
            )

        assert result["success"] is True
        assert result["format"] == "z3_smt"
        assert "assert" in result["formal_statement"]

    @pytest.mark.asyncio
    async def test_generate_with_context(self):
        """Test proof generation with context."""
        mock_backend = AsyncMock()
        mock_backend.translate.return_value = "theorem"

        with patch(
            "aragora.verification.formal.LeanBackend",
            return_value=mock_backend,
        ):
            await generate_proof_tool(
                claim="Test claim",
                context="Mathematical context",
            )

        mock_backend.translate.assert_called_once_with("Test claim", "Mathematical context")

    @pytest.mark.asyncio
    async def test_generate_translation_fails(self):
        """Test when translation returns None."""
        mock_backend = AsyncMock()
        mock_backend.translate.return_value = None

        with patch(
            "aragora.verification.formal.LeanBackend",
            return_value=mock_backend,
        ):
            result = await generate_proof_tool(claim="Complex claim")

        assert result["success"] is False
        assert result["formal_statement"] is None
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_generate_import_error(self):
        """Test graceful handling when verification module not available."""
        with patch(
            "aragora.verification.formal.LeanBackend",
            side_effect=ImportError("Not installed"),
        ):
            result = await generate_proof_tool(claim="Test claim")

        assert "error" in result
        assert "not available" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_generate_exception_handling(self):
        """Test exception handling during proof generation."""
        mock_backend = AsyncMock()
        mock_backend.translate.side_effect = RuntimeError("Backend error")

        with patch(
            "aragora.verification.formal.LeanBackend",
            return_value=mock_backend,
        ):
            result = await generate_proof_tool(claim="Test claim")

        assert "error" in result
        assert "failed" in result["error"].lower()
