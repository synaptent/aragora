"""Tests for NomicContextBuilder."""

from __future__ import annotations

import subprocess

import pytest
from pathlib import Path
from unittest.mock import AsyncMock

from aragora.nomic.context_builder import (
    CodebaseIndex,
    IndexedFile,
    NomicContextBuilder,
)


@pytest.fixture
def sample_tree(tmp_path):
    """Create a small file tree for indexing."""
    src = tmp_path / "aragora"
    src.mkdir()
    (src / "__init__.py").write_text("from .core import Arena\n")
    (src / "core.py").write_text('"""Core module."""\n\nclass Arena:\n    pass\n')
    sub = src / "debate"
    sub.mkdir()
    (sub / "__init__.py").write_text("")
    (sub / "protocol.py").write_text(
        '"""Protocol module."""\n\nclass DebateProtocol:\n    rounds = 9\n'
    )
    return tmp_path


class TestCodebaseIndex:
    """Tests for CodebaseIndex data structure."""

    def test_total_tokens_estimate(self):
        idx = CodebaseIndex(root_path=Path("."), total_bytes=4000)
        assert idx.total_tokens_estimate == 1000

    def test_get_file(self):
        f = IndexedFile(
            relative_path="aragora/core.py", size_bytes=100, line_count=10, extension=".py"
        )
        idx = CodebaseIndex(root_path=Path("."), files=[f])
        assert idx.get_file("aragora/core.py") is f
        assert idx.get_file("nonexistent.py") is None

    def test_search_files(self):
        files = [
            IndexedFile(
                relative_path="aragora/core.py", size_bytes=100, line_count=10, extension=".py"
            ),
            IndexedFile(
                relative_path="aragora/debate/protocol.py",
                size_bytes=200,
                line_count=20,
                extension=".py",
            ),
            IndexedFile(
                relative_path="tests/test_core.py", size_bytes=50, line_count=5, extension=".py"
            ),
        ]
        idx = CodebaseIndex(root_path=Path("."), files=files)
        results = idx.search_files("core")
        assert len(results) == 2  # core.py and test_core.py


class TestNomicContextBuilder:
    """Tests for NomicContextBuilder."""

    @pytest.mark.asyncio
    async def test_build_index(self, sample_tree):
        builder = NomicContextBuilder(aragora_path=sample_tree)
        index = await builder.build_index()
        assert index.total_files >= 3  # __init__.py, core.py, protocol.py
        assert index.total_bytes > 0
        assert index.total_lines > 0

    @pytest.mark.asyncio
    async def test_build_index_falls_back_without_git_binary(self, sample_tree, monkeypatch):
        monkeypatch.setenv("PATH", "")

        index = await NomicContextBuilder(aragora_path=sample_tree).build_index()

        assert index.get_file("aragora/core.py") is not None

    @pytest.mark.asyncio
    async def test_build_index_falls_back_for_unborn_repository(self, tmp_path):
        subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
        (tmp_path / "source.py").write_text("value = 1\n", encoding="utf-8")

        index = await NomicContextBuilder(aragora_path=tmp_path).build_index()

        assert index.get_file("source.py") is not None

    @pytest.mark.asyncio
    async def test_build_index_falls_back_for_untracked_directory_in_outer_repository(
        self, tmp_path
    ):
        subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "index@example.test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Index Test"],
            check=True,
        )
        (tmp_path / "tracked.txt").write_text("tracked\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True)
        target = tmp_path / "untracked-target"
        target.mkdir()
        (target / "source.py").write_text("value = 1\n", encoding="utf-8")

        index = await NomicContextBuilder(aragora_path=target).build_index()

        assert index.get_file("source.py") is not None

    @pytest.mark.asyncio
    async def test_build_index_handles_non_ascii_tracked_paths(self, tmp_path):
        subprocess.run(["git", "-C", str(tmp_path), "init"], check=True, capture_output=True)
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.email", "index@example.test"],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(tmp_path), "config", "user.name", "Index Test"],
            check=True,
        )
        (tmp_path / "café.py").write_text("value = 1\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
        subprocess.run(["git", "-C", str(tmp_path), "commit", "-m", "initial"], check=True)

        index = await NomicContextBuilder(aragora_path=tmp_path).build_index()

        assert index.get_file("café.py") is not None

    @pytest.mark.asyncio
    async def test_build_index_skips_tests(self, sample_tree):
        """Default: test files are excluded (directory named 'test')."""
        # The builder filters on "test" in path.parts (exact match)
        test_dir = sample_tree / "test"
        test_dir.mkdir()
        (test_dir / "test_foo.py").write_text("def test_x(): pass\n")

        builder = NomicContextBuilder(aragora_path=sample_tree, include_tests=False)
        index = await builder.build_index()
        paths = [f.relative_path for f in index.files]
        assert not any("test_foo" in p for p in paths)

    @pytest.mark.asyncio
    async def test_build_index_includes_tests(self, sample_tree):
        """With include_tests=True, test files are included."""
        test_dir = sample_tree / "test"
        test_dir.mkdir()
        (test_dir / "test_bar.py").write_text("def test_y(): pass\n")

        builder = NomicContextBuilder(aragora_path=sample_tree, include_tests=True)
        index = await builder.build_index()
        paths = [f.relative_path for f in index.files]
        assert any("test_bar" in p for p in paths)

    @pytest.mark.asyncio
    async def test_build_debate_context(self, sample_tree):
        builder = NomicContextBuilder(aragora_path=sample_tree, full_corpus=False)
        context = await builder.build_debate_context()
        assert "Aragora Codebase Context" in context
        assert "files" in context

    @pytest.mark.asyncio
    async def test_query_fallback_to_index(self, sample_tree):
        builder = NomicContextBuilder(aragora_path=sample_tree)
        await builder.build_index()
        result = await builder.query("core module")
        assert "core" in result.lower()

    @pytest.mark.asyncio
    async def test_empty_dir(self, tmp_path):
        builder = NomicContextBuilder(aragora_path=tmp_path)
        index = await builder.build_index()
        assert index.total_files == 0
        assert index.total_bytes == 0

    @pytest.mark.asyncio
    async def test_build_debate_context_empty_root_returns_empty(self, tmp_path):
        builder = NomicContextBuilder(aragora_path=tmp_path, full_corpus=False)
        context = await builder.build_debate_context()
        assert context == ""

    @pytest.mark.asyncio
    async def test_build_debate_context_nonexistent_root_returns_empty(self, tmp_path):
        builder = NomicContextBuilder(aragora_path=tmp_path / "does-not-exist", full_corpus=False)
        context = await builder.build_debate_context()
        assert context == ""

    @pytest.mark.asyncio
    async def test_knowledge_mound_integration(self, sample_tree):
        mock_mound = AsyncMock()
        mock_mound.query_semantic = AsyncMock(return_value=[])
        builder = NomicContextBuilder(
            aragora_path=sample_tree,
            knowledge_mound=mock_mound,
            full_corpus=False,
        )
        context = await builder.build_debate_context()
        assert isinstance(context, str)

    @pytest.mark.asyncio
    async def test_index_search_no_matches(self, sample_tree):
        builder = NomicContextBuilder(aragora_path=sample_tree)
        await builder.build_index()
        result = await builder.query("zzzznonexistentkeyword")
        assert "No matching files found" in result

    def test_module_path_derivation(self):
        f = IndexedFile(
            relative_path="aragora/debate/protocol.py",
            size_bytes=100,
            line_count=10,
            extension=".py",
            module_path="aragora.debate.protocol",
        )
        assert f.module_path == "aragora.debate.protocol"

    @pytest.mark.asyncio
    async def test_build_index_prefers_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ARAGORA_CONTEXT_USE_MANIFEST", "1")

        context_dir = tmp_path / ".nomic" / "context"
        context_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = context_dir / "codebase_manifest.tsv"
        manifest_path.write_text(
            "# Aragora codebase manifest\n"
            "# format=path\\tlines\\tbytes\\textension\\tmodule\n"
            "aragora/example.py\t10\t100\t.py\taragora.example\n",
            encoding="utf-8",
        )

        builder = NomicContextBuilder(aragora_path=tmp_path)
        index = await builder.build_index()
        assert index.total_files == 1
        assert index.get_file("aragora/example.py") is not None
