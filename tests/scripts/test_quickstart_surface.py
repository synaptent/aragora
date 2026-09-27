from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import check_quickstart_surface as quickstart_surface
from scripts.check_quickstart_surface import (
    DEFAULT_DOCS,
    _display_path,
    build_installed_manifest,
    check_documents,
    extract_python_blocks,
)


def _write(path: Path, content: str) -> Path:
    path.write_text(textwrap.dedent(content).strip() + "\n", encoding="utf-8")
    return path


def _manifest() -> dict[str, object]:
    return {
        "version": "2.8.0",
        "clients": {
            "AragoraAsyncClient": {
                "context_managers": {"async": True, "sync": False},
                "methods": ["close"],
                "namespaces": {"debates": ["create", "list"], "agents": ["list"]},
            },
            "AragoraClient": {
                "context_managers": {"async": False, "sync": True},
                "methods": ["close"],
                "namespaces": {"debates": ["create", "list"], "agents": ["list"]},
            },
        },
    }


def test_default_docs_cover_public_sdk_guides() -> None:
    assert Path("docs/SDK_QUICKSTART_PYTHON.md") in DEFAULT_DOCS
    assert Path("docs-site/docs/guides/sdk.md") in DEFAULT_DOCS


def test_extract_python_blocks_preserves_source_line(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        # Guide

        ```bash
        pip install aragora-sdk
        ```

        ```python
        print("hello")
        ```
        """,
    )

    blocks = extract_python_blocks(path)

    assert len(blocks) == 1
    assert blocks[0].start_line == 8
    assert blocks[0].source == 'print("hello")'


def test_extract_python_blocks_accepts_parameterized_fence(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        ```python title="quickstart.py" {line-numbers}
        from aragora_sdk import AragoraAsyncClient
        ```
        """,
    )

    blocks = extract_python_blocks(path)

    assert len(blocks) == 1
    assert blocks[0].source == "from aragora_sdk import AragoraAsyncClient"


def test_checker_ignores_invalid_unrelated_python_block(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        ```python
        this is illustrative pseudocode, not valid Python
        ```
        """,
    )

    assert check_documents([path], _manifest()) == []


def test_display_path_preserves_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "released-surface.json"

    assert _display_path(root, outside) == outside


def test_checker_accepts_released_async_quickstart(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        ```python
        import asyncio
        from aragora_sdk import AragoraAsyncClient

        async def main():
            async with AragoraAsyncClient(demo=True) as client:
                created = await client.debates.create(task="Test")
                debates = await client.debates.list(limit=5)
                agents = await client.agents.list()
                print(created, debates, agents)

        asyncio.run(main())
        ```
        """,
    )

    assert check_documents([path], _manifest()) == []


def test_checker_rejects_missing_released_call(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        ```python
        from aragora_sdk import AragoraAsyncClient

        async def main():
            async with AragoraAsyncClient() as client:
                await client.debates.run(task="Test")
        ```
        """,
    )

    findings = check_documents([path], _manifest())

    assert len(findings) == 1
    assert findings[0].line == 6
    assert "AragoraAsyncClient.debates.run()" in findings[0].message


def test_checker_rejects_sync_client_in_async_context(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        ```python
        from aragora_sdk import AragoraClient

        async def main():
            async with AragoraClient() as client:
                await client.debates.create(task="Test")
        ```
        """,
    )

    findings = check_documents([path], _manifest())

    assert len(findings) == 1
    assert findings[0].line == 5
    assert findings[0].message == "AragoraClient does not support async context management"


def test_checker_ignores_other_client_packages(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "guide.md",
        """
        ```python
        from aragora.client import AragoraClient

        client = AragoraClient()
        client.debates.run(task="Test")
        ```
        """,
    )

    assert check_documents([path], _manifest()) == []


def test_installed_manifest_closes_clients(monkeypatch) -> None:
    closed: list[str] = []

    class Namespace:
        def list(self) -> None:
            pass

    class SyncClient:
        def __init__(self, *, demo: bool) -> None:
            assert demo is True
            self.agents = Namespace()
            self.debates = Namespace()

        def close(self) -> None:
            closed.append("sync")

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            self.close()

    class AsyncClient:
        def __init__(self, *, demo: bool) -> None:
            assert demo is True
            self.agents = Namespace()
            self.debates = Namespace()

        async def close(self) -> None:
            closed.append("async")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args) -> None:
            await self.close()

    sdk = SimpleNamespace(AragoraClient=SyncClient, AragoraAsyncClient=AsyncClient)
    monkeypatch.setattr(quickstart_surface.importlib, "import_module", lambda _: sdk)
    monkeypatch.setattr(quickstart_surface.importlib.metadata, "version", lambda _: "2.8.0")

    manifest = build_installed_manifest()

    assert closed == ["sync", "async"]
    assert manifest["clients"]["AragoraClient"]["context_managers"] == {
        "async": False,
        "sync": True,
    }
    assert manifest["clients"]["AragoraAsyncClient"]["context_managers"] == {
        "async": True,
        "sync": False,
    }


def test_installed_manifest_closes_client_when_introspection_fails(monkeypatch) -> None:
    closed = False

    class BrokenClient:
        def __init__(self, *, demo: bool) -> None:
            assert demo is True

        @property
        def agents(self):
            raise RuntimeError("broken namespace")

        def close(self) -> None:
            nonlocal closed
            closed = True

    sdk = SimpleNamespace(AragoraClient=BrokenClient)
    monkeypatch.setattr(quickstart_surface.importlib, "import_module", lambda _: sdk)

    with pytest.raises(RuntimeError, match="broken namespace"):
        build_installed_manifest()

    assert closed is True
