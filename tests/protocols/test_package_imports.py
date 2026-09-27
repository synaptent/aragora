"""Regression coverage for optional package import boundaries."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path


def test_protocols_a2a_import_survives_missing_httpx() -> None:
    """Importing A2A protocol types should not require the optional httpx client."""
    project_root = Path(__file__).resolve().parents[2]
    script = textwrap.dedent(
        """
        import importlib.abc
        import importlib
        import sys

        class BlockHTTPX(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "httpx" or fullname.startswith("httpx."):
                    raise ImportError("httpx unavailable")
                return None

        sys.meta_path.insert(0, BlockHTTPX())

        module = importlib.import_module("aragora.protocols.a2a")
        assert module.TaskRequest is not None
        assert module.A2AServer is not None
        """
    )

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr or result.stdout


_IMPORT_BLOCKER = textwrap.dedent(
    """
    import importlib.abc
    import sys

    class BlockImports(importlib.abc.MetaPathFinder):
        def __init__(self, names, message):
            self.names = names
            self.message = message
            self.attempted = []

        def find_spec(self, fullname, path=None, target=None):
            for name in self.names:
                if fullname == name or fullname.startswith(name + "."):
                    self.attempted.append(fullname)
                    raise ImportError(self.message)
            return None
    """
)


def _run_in_fresh_interpreter(script: str) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[2]
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_BLOCKER + textwrap.dedent(script)],
        cwd=project_root,
        capture_output=True,
        text=True,
        check=False,
    )


def test_memory_import_survives_missing_aiohttp() -> None:
    """The memory package and SemanticRetriever import without aiohttp.

    aragora.memory.embeddings defers aiohttp until a remote embedding is
    fetched, so the package exports the real embedding classes and the
    offline hash-embedding path keeps working when aiohttp is absent.
    """
    result = _run_in_fresh_interpreter(
        """
        import asyncio
        import importlib
        import os
        import tempfile

        blocker = BlockImports(["aiohttp"], "aiohttp unavailable")
        sys.meta_path.insert(0, blocker)

        memory = importlib.import_module("aragora.memory")
        embeddings = importlib.import_module("aragora.memory.embeddings")

        assert memory.CritiqueStore is not None
        for name in ("SemanticRetriever", "OpenAIEmbedding", "GeminiEmbedding", "OllamaEmbedding"):
            assert getattr(memory, name) is getattr(embeddings, name), name
        assert blocker.attempted == [], blocker.attempted

        with tempfile.TemporaryDirectory() as tmp:
            retriever = memory.SemanticRetriever(
                os.path.join(tmp, "embeddings.db"),
                provider=embeddings.EmbeddingProvider(dimension=8),
            )
            vector = asyncio.run(retriever.embed_and_store("pattern-1", "offline text"))
            assert len(vector) == 8
        """
    )

    assert result.returncode == 0, result.stderr or result.stdout


def test_memory_import_does_not_mask_embeddings_import_errors() -> None:
    """A broken embeddings module must fail the package import, not become None."""
    result = _run_in_fresh_interpreter(
        """
        import importlib

        sys.meta_path.insert(
            0, BlockImports(["aragora.memory.embeddings"], "embeddings-import-sentinel")
        )

        try:
            importlib.import_module("aragora.memory")
        except ImportError as exc:
            assert "embeddings-import-sentinel" in str(exc), exc
        else:
            raise AssertionError("aragora.memory imported despite a broken embeddings module")
        """
    )

    assert result.returncode == 0, result.stderr or result.stdout
