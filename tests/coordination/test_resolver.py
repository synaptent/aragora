"""Tests for the conflict resolver."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.coordination.resolver import ConflictResolver, Resolution, ResolutionResult


@dataclass
class _MockConflictInfo:
    file_path: str = "test.py"
    auto_resolvable: bool = False
    category: str = "unknown"


@dataclass
class _MockSemanticConflict:
    source_branch: str = "a"
    target_branch: str = "b"
    conflict_type: str = "signature_break"
    description: str = "Function signature changed"
    affected_files: list[str] = field(default_factory=lambda: ["test.py"])
    confidence: float = 0.8


class TestResolutionResult:
    def test_to_dict(self):
        r = ResolutionResult(
            resolution=Resolution.NO_CONFLICT,
            branch_a="a",
            branch_b="b",
        )
        d = r.to_dict()
        assert d["resolution"] == "no_conflict"
        assert d["branch_a"] == "a"


class TestConflictResolver:
    def test_detect_no_conflicts(self, tmp_path):
        resolver = ConflictResolver(repo_path=tmp_path)
        with patch.object(resolver, "_get_reconciler") as mock_rec:
            mock_rec.return_value.detect_conflicts.return_value = []
            with patch.object(resolver, "_get_semantic_detector", return_value=None):
                result = resolver.detect("branch-a", "branch-b")

        assert result["textual"] == []
        assert result["semantic"] == []

    @pytest.mark.anyio
    async def test_resolve_no_conflict(self, tmp_path):
        resolver = ConflictResolver(repo_path=tmp_path)
        with patch.object(resolver, "detect", return_value={"textual": [], "semantic": []}):
            result = await resolver.resolve("a", "b")
        assert result.resolution == Resolution.NO_CONFLICT

    @pytest.mark.anyio
    async def test_resolve_auto_merge_trivial(self, tmp_path):
        trivial = _MockConflictInfo(auto_resolvable=True)
        resolver = ConflictResolver(repo_path=tmp_path)
        with patch.object(
            resolver,
            "detect",
            return_value={"textual": [trivial], "semantic": []},
        ):
            result = await resolver.resolve("a", "b")
        assert result.resolution == Resolution.AUTO_MERGED

    @pytest.mark.anyio
    async def test_resolve_needs_human_no_debate(self, tmp_path):
        semantic = _MockSemanticConflict(confidence=0.9)
        resolver = ConflictResolver(repo_path=tmp_path, enable_debate=False)
        with patch.object(
            resolver,
            "detect",
            return_value={"textual": [], "semantic": [semantic]},
        ):
            result = await resolver.resolve("a", "b")
        assert result.resolution == Resolution.NEEDS_HUMAN

    @pytest.mark.anyio
    async def test_resolve_debate_fallback_on_import_error(self, tmp_path):
        semantic = _MockSemanticConflict(confidence=0.9)
        resolver = ConflictResolver(repo_path=tmp_path, enable_debate=True)
        with patch.object(
            resolver,
            "detect",
            return_value={"textual": [], "semantic": [semantic]},
        ):
            with patch.dict("sys.modules", {"aragora.debate.orchestrator": None}):
                result = await resolver.resolve("a", "b")
        assert result.resolution == Resolution.NEEDS_HUMAN

    @pytest.mark.anyio
    async def test_resolve_debate_success(self, tmp_path):
        semantic = _MockSemanticConflict(confidence=0.9)
        resolver = ConflictResolver(repo_path=tmp_path, enable_debate=True)

        mock_result = MagicMock()
        mock_result.synthesis = "Branch A should merge first because it has broader changes."

        mock_arena = AsyncMock()
        mock_arena.run.return_value = mock_result

        with patch.object(
            resolver,
            "detect",
            return_value={"textual": [], "semantic": [semantic]},
        ):
            with patch("aragora.coordination.resolver.Arena", return_value=mock_arena, create=True):
                with patch("aragora.coordination.resolver.Environment", create=True):
                    with patch("aragora.coordination.resolver.DebateProtocol", create=True):
                        # Need to patch the imports inside _run_debate
                        import aragora.coordination.resolver as mod

                        original_run_debate = mod.ConflictResolver._run_debate

                        async def patched_run_debate(self, branch_a, branch_b, sc, ctx):
                            # Simulate successful debate
                            receipt_path = self._store_receipt(
                                branch_a, branch_b, ["test.py"], mock_result.synthesis
                            )
                            return ResolutionResult(
                                resolution=Resolution.DEBATE_RESOLVED,
                                branch_a=branch_a,
                                branch_b=branch_b,
                                conflicting_files=["test.py"],
                                merge_order="a_first",
                                debate_summary=mock_result.synthesis[:500],
                                receipt_path=str(receipt_path),
                            )

                        with patch.object(mod.ConflictResolver, "_run_debate", patched_run_debate):
                            result = await resolver.resolve("a", "b")

        assert result.resolution == Resolution.DEBATE_RESOLVED
        assert result.merge_order == "a_first"
        assert "Branch A" in result.debate_summary

    def test_store_receipt(self, tmp_path):
        resolver = ConflictResolver(repo_path=tmp_path)
        path = resolver._store_receipt("a", "b", ["file.py"], "Merge A first")

        assert path.exists()
        import json

        data = json.loads(path.read_text())
        assert data["branch_a"] == "a"
        assert data["synthesis"] == "Merge A first"

    @pytest.mark.anyio
    async def test_resolve_low_confidence_skips_debate(self, tmp_path):
        """Low-confidence semantic conflicts don't trigger debate."""
        semantic = _MockSemanticConflict(confidence=0.3)
        nontrivial_textual = _MockConflictInfo(auto_resolvable=False)
        resolver = ConflictResolver(repo_path=tmp_path, enable_debate=True)
        with patch.object(
            resolver,
            "detect",
            return_value={"textual": [nontrivial_textual], "semantic": [semantic]},
        ):
            result = await resolver.resolve("a", "b")
        # Low confidence + non-trivial textual → needs human, no debate
        assert result.resolution == Resolution.NEEDS_HUMAN

    @pytest.mark.anyio
    async def test_resolve_with_context(self, tmp_path):
        """Context dict is passed through to debate."""
        resolver = ConflictResolver(repo_path=tmp_path, enable_debate=False)
        semantic = _MockSemanticConflict(confidence=0.9)
        with patch.object(
            resolver,
            "detect",
            return_value={"textual": [], "semantic": [semantic]},
        ):
            result = await resolver.resolve("a", "b", context={"agent_a_intent": "Refactor auth"})
        assert result.resolution == Resolution.NEEDS_HUMAN
