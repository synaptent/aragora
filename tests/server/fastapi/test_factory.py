from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from aragora.server.fastapi import create_app
from aragora.server.fastapi import factory
from aragora.storage.connection_factory import DatabaseConfig, StorageBackendType


@contextmanager
def _patched_startup_dependencies(*, patch_storage: bool = True):
    with ExitStack() as stack:
        mocked = {}
        if patch_storage:
            mocked["storage"] = stack.enter_context(
                patch("aragora.storage.debate_storage.DebateStorage")
            )
        mocked["get_user_store"] = stack.enter_context(
            patch("aragora.storage.user_store.get_user_store", return_value=MagicMock())
        )
        mocked["init_postgres_pool"] = stack.enter_context(
            patch("aragora.server.startup.database.init_postgres_pool", new_callable=AsyncMock)
        )
        mocked["close_postgres_pool"] = stack.enter_context(
            patch("aragora.server.startup.database.close_postgres_pool", new_callable=AsyncMock)
        )
        stack.enter_context(patch("aragora.ranking.elo.EloSystem", return_value=MagicMock()))
        mocked["get_continuum_memory"] = stack.enter_context(
            patch("aragora.memory.continuum.get_continuum_memory", return_value=MagicMock())
        )
        mock_cross_config = stack.enter_context(
            patch("aragora.memory.cross_debate_rlm.CrossDebateConfig")
        )
        mock_cross_config.return_value = MagicMock()
        stack.enter_context(
            patch("aragora.memory.cross_debate_rlm.CrossDebateMemory", return_value=MagicMock())
        )
        stack.enter_context(
            patch("aragora.knowledge.mound.get_knowledge_mound", return_value=MagicMock())
        )
        stack.enter_context(
            patch("aragora.rbac.checker.get_permission_checker", return_value=MagicMock())
        )
        stack.enter_context(
            patch("aragora.debate.decision_service.get_decision_service", return_value=MagicMock())
        )
        stack.enter_context(
            patch("aragora.server.middleware.deprecation_enforcer.register_default_deprecations")
        )
        yield mocked


def test_build_server_context_initializes_debate_storage_in_nomic_dir(tmp_path: Path):
    with _patched_startup_dependencies() as mocked:
        ctx = factory._build_server_context(tmp_path)

    mocked["storage"].assert_called_once_with(str(tmp_path / "debates.db"))
    mocked["get_continuum_memory"].assert_called_once_with(
        db_path=str(tmp_path / "continuum_memory.db")
    )
    assert ctx["storage"] is mocked["storage"].return_value


def test_create_app_lifespan_starts_with_fastapi_context(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("ARAGORA_NOMIC_DIR", str(tmp_path))

    with _patched_startup_dependencies() as mocked:
        mocked["storage"].return_value = object()
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/healthz")

    assert response.status_code == 200
    mocked["storage"].assert_called_once_with(str(tmp_path / "debates.db"))
    mocked["init_postgres_pool"].assert_awaited_once()
    mocked["close_postgres_pool"].assert_awaited_once()


@pytest.mark.parametrize("env_nomic_dir", [None, "elsewhere"])
def test_create_app_nomic_dir_is_used_by_the_lifespan(
    tmp_path: Path, monkeypatch, env_nomic_dir: str | None
):
    nomic_dir = tmp_path / "nomic"
    if env_nomic_dir is None:
        monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    else:
        monkeypatch.setenv("ARAGORA_NOMIC_DIR", str(tmp_path / env_nomic_dir))

    with _patched_startup_dependencies() as mocked:
        with TestClient(create_app(nomic_dir=nomic_dir)) as client:
            assert client.get("/healthz").status_code == 200

    mocked["storage"].assert_called_once_with(str(nomic_dir / "debates.db"))


def test_fastapi_saved_debate_is_listed_by_the_legacy_store(tmp_path: Path, monkeypatch):
    from aragora.storage.debate_storage import DebateStorage

    nomic_dir = tmp_path / "nomic"
    nomic_dir.mkdir()
    monkeypatch.delenv("ARAGORA_NOMIC_DIR", raising=False)
    monkeypatch.setenv("ARAGORA_DATA_DIR", str(tmp_path / "data"))
    app = create_app(nomic_dir=nomic_dir)

    with _patched_startup_dependencies(patch_storage=False):
        with TestClient(app):
            app.state.context["storage"].save_dict(
                {"id": "fastapi-debate", "task": "Adopt a four-day week?", "agents": []},
                org_id="org-a",
            )

    legacy = DebateStorage(str(nomic_dir / "debates.db"))
    assert [d.debate_id for d in legacy.list_recent(org_id="org-a")] == ["fastapi-debate"]
    assert legacy.list_recent(org_id="org-b") == []


def test_lifespan_registers_webhook_store_before_context_construction():
    """FastAPI startup wires durable webhooks before optional context work."""
    order: list[str] = []
    app = MagicMock()

    def build_context(_nomic_dir):
        order.append("context")
        return {}

    with (
        patch(
            "aragora.server.startup.event_subscribers.register_webhook_store",
            side_effect=lambda: order.append("webhook_store"),
        ),
        patch(
            "aragora.server.startup.database.init_postgres_pool",
            new_callable=AsyncMock,
        ),
        patch(
            "aragora.server.startup.database.close_postgres_pool",
            new_callable=AsyncMock,
        ),
        patch.object(factory, "_build_server_context", side_effect=build_context),
        patch("aragora.server.middleware.deprecation_enforcer.register_default_deprecations"),
    ):
        asyncio.run(_exercise_lifespan(app))

    assert order == ["webhook_store", "context"]


def test_build_server_context_defers_postgres_user_store_in_async_context(tmp_path: Path):
    config = DatabaseConfig(
        backend_type=StorageBackendType.POSTGRES,
        dsn="postgresql://example",
        is_supabase=False,
    )

    with (
        _patched_startup_dependencies() as mocked,
        patch(
            "aragora.storage.connection_factory.resolve_database_config",
            return_value=config,
        ),
        patch(
            "aragora.storage.pool_manager.is_pool_initialized",
            return_value=False,
        ),
    ):
        ctx = asyncio.run(_async_build_server_context(tmp_path))

    assert ctx["user_store"] is None
    mocked["get_user_store"].assert_not_called()


async def _async_build_server_context(tmp_path: Path):
    return factory._build_server_context(tmp_path)


async def _exercise_lifespan(app):
    async with factory.lifespan(app):
        pass
