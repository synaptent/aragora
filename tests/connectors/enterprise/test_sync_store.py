"""
Tests for SyncStore encryption and persistence.
"""

import pytest
import tempfile
import os
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, MagicMock
from urllib.parse import urlsplit
from uuid import uuid4

from aragora.storage.sync_store import (
    SyncStore,
    ConnectorConfig,
    SyncJob,
    _is_sensitive_key,
    _encrypt_config,
    _decrypt_config,
    CREDENTIAL_KEYWORDS,
)

import aiosqlite  # noqa: F401


class TestSensitiveKeyDetection:
    """Tests for sensitive key detection."""

    def test_api_key_detected(self):
        """Should detect api_key variants."""
        assert _is_sensitive_key("api_key") is True
        assert _is_sensitive_key("API_KEY") is True
        assert _is_sensitive_key("github_api_key") is True

    def test_secret_detected(self):
        """Should detect secret variants."""
        assert _is_sensitive_key("secret") is True
        assert _is_sensitive_key("client_secret") is True
        assert _is_sensitive_key("SECRET_KEY") is True

    def test_password_detected(self):
        """Should detect password variants."""
        assert _is_sensitive_key("password") is True
        assert _is_sensitive_key("db_password") is True

    def test_token_detected(self):
        """Should detect token variants."""
        assert _is_sensitive_key("token") is True
        assert _is_sensitive_key("auth_token") is True
        assert _is_sensitive_key("access_token") is True
        assert _is_sensitive_key("refresh_token") is True

    def test_non_sensitive_keys(self):
        """Should not flag non-sensitive keys."""
        assert _is_sensitive_key("name") is False
        assert _is_sensitive_key("url") is False
        assert _is_sensitive_key("host") is False
        assert _is_sensitive_key("port") is False


class TestConfigEncryption:
    """Tests for config encryption/decryption."""

    def test_encrypt_disabled_returns_unchanged(self):
        """Should return config unchanged when encryption disabled."""
        config = {"api_key": "secret-123", "name": "test"}
        result = _encrypt_config(config, use_encryption=False)
        assert result == config

    def test_encrypt_empty_config(self):
        """Should handle empty config."""
        result = _encrypt_config({}, use_encryption=True)
        assert result == {}

    def test_encrypt_no_sensitive_keys(self):
        """Should return unchanged if no sensitive keys."""
        config = {"name": "test", "url": "https://example.com"}
        result = _encrypt_config(config, use_encryption=True)
        # Without crypto available, returns unchanged
        assert result == config

    @patch("aragora.storage.sync_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.sync_store.get_encryption_service")
    def test_encrypt_with_crypto(self, mock_get_service):
        """Should encrypt sensitive fields when crypto available."""
        mock_service = MagicMock()
        mock_service.encrypt_fields.return_value = {
            "api_key": {"_encrypted": True, "ciphertext": "xxx"},
            "name": "test",
        }
        mock_get_service.return_value = mock_service

        config = {"api_key": "secret-123", "name": "test"}
        result = _encrypt_config(config, use_encryption=True, connector_id="conn-1")

        mock_service.encrypt_fields.assert_called_once()
        call_args = mock_service.encrypt_fields.call_args
        assert call_args[0][0] == config  # config
        assert "api_key" in call_args[0][1]  # sensitive_keys
        assert call_args[0][2] == "conn-1"  # AAD

    def test_decrypt_disabled_returns_unchanged(self):
        """Should return config unchanged when decryption disabled."""
        config = {"api_key": {"_encrypted": True}, "name": "test"}
        result = _decrypt_config(config, use_encryption=False)
        assert result == config

    def test_decrypt_legacy_plaintext(self):
        """Should return legacy plaintext unchanged."""
        config = {"api_key": "plaintext-secret", "name": "test"}
        result = _decrypt_config(config, use_encryption=True)
        # No _encrypted markers, returns as-is
        assert result == config

    @patch("aragora.storage.sync_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.sync_store.get_encryption_service")
    def test_decrypt_with_crypto(self, mock_get_service):
        """Should decrypt fields when crypto available."""
        mock_service = MagicMock()
        mock_service.decrypt_fields.return_value = {
            "api_key": "decrypted-secret",
            "name": "test",
        }
        mock_get_service.return_value = mock_service

        config = {"api_key": {"_encrypted": True}, "name": "test"}
        result = _decrypt_config(config, use_encryption=True, connector_id="conn-1")

        mock_service.decrypt_fields.assert_called_once()


class TestSyncStoreBasics:
    """Tests for SyncStore basic operations."""

    def test_default_db_url_uses_data_dir(self, tmp_path, monkeypatch):
        """Default database URL should resolve under DATA_DIR."""
        expected_db = str(tmp_path / "connectors.db")
        monkeypatch.setattr(
            "aragora.storage.sync_store.resolve_db_path",
            lambda p: expected_db,
        )
        monkeypatch.delenv("ARAGORA_SYNC_DATABASE_URL", raising=False)
        store = SyncStore(use_encryption=False)
        assert store._database_url.startswith("sqlite:///")
        db_path = store._database_url.replace("sqlite:///", "")
        assert Path(db_path).resolve().relative_to(tmp_path.resolve())

    @pytest.fixture
    def store(self, tmp_path):
        """Create a store with temp database."""
        db_path = tmp_path / "test_sync.db"
        return SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,  # Disable for basic tests
        )

    @pytest.mark.asyncio
    async def test_initialize(self, store):
        """Should initialize database."""
        await store.initialize()
        assert store._initialized is True

    @pytest.mark.asyncio
    async def test_save_and_get_connector(self, store):
        """Should save and retrieve connector."""
        await store.initialize()

        connector = await store.save_connector(
            connector_id="test-1",
            connector_type="github",
            name="Test Connector",
            config={"repo": "test/repo"},
        )

        assert connector.id == "test-1"
        assert connector.connector_type == "github"
        assert connector.name == "Test Connector"

        retrieved = await store.get_connector("test-1")
        assert retrieved is not None
        assert retrieved.id == "test-1"

    @pytest.mark.asyncio
    async def test_list_connectors(self, store):
        """Should list all connectors."""
        await store.initialize()

        await store.save_connector("c1", "github", "Conn 1", {})
        await store.save_connector("c2", "s3", "Conn 2", {})

        connectors = await store.list_connectors()
        assert len(connectors) == 2

    @pytest.mark.asyncio
    async def test_delete_connector(self, store):
        """Should delete connector."""
        await store.initialize()

        await store.save_connector("c1", "github", "Conn 1", {})
        deleted = await store.delete_connector("c1")
        assert deleted is True

        retrieved = await store.get_connector("c1")
        assert retrieved is None


class TestSyncStoreEncryption:
    """Tests for SyncStore with encryption enabled."""

    @pytest.mark.asyncio
    @patch("aragora.storage.sync_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.sync_store.get_encryption_service")
    async def test_encrypt_config_uses_aad(self, mock_get_service):
        """Should encrypt credentials with connector_id as AAD."""
        mock_service = MagicMock()
        mock_service.encrypt_fields.return_value = {
            "api_key": {"_encrypted": True, "ciphertext": "encrypted-key"},
            "repo": "test/repo",
        }
        mock_get_service.return_value = mock_service

        config = {"api_key": "secret-token", "repo": "test/repo"}

        # Directly test _encrypt_config with AAD
        result = _encrypt_config(config, use_encryption=True, connector_id="secure-1")

        # Verify encryption was called with connector_id as AAD
        mock_service.encrypt_fields.assert_called_once()
        call_args = mock_service.encrypt_fields.call_args
        assert call_args[0][0] == config  # config
        assert "api_key" in call_args[0][1]  # sensitive_keys
        assert call_args[0][2] == "secure-1"  # AAD = connector_id

    @pytest.mark.asyncio
    @patch("aragora.storage.sync_store.CRYPTO_AVAILABLE", True)
    @patch("aragora.storage.sync_store.get_encryption_service")
    async def test_decrypt_config_uses_aad(self, mock_get_service):
        """Should decrypt credentials with connector_id as AAD."""
        mock_service = MagicMock()
        mock_service.decrypt_fields.return_value = {
            "api_key": "decrypted-secret",
            "repo": "test/repo",
        }
        mock_get_service.return_value = mock_service

        config = {"api_key": {"_encrypted": True}, "repo": "test/repo"}

        # Directly test _decrypt_config with AAD
        result = _decrypt_config(config, use_encryption=True, connector_id="secure-1")

        # Verify decryption was called with connector_id as AAD
        mock_service.decrypt_fields.assert_called_once()
        call_args = mock_service.decrypt_fields.call_args
        assert call_args[0][2] == "secure-1"  # AAD = connector_id


class TestSyncJobOperations:
    """Tests for sync job recording."""

    @pytest.fixture
    def store(self, tmp_path):
        """Create a store with temp database."""
        db_path = tmp_path / "test_jobs.db"
        return SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )

    @pytest.mark.asyncio
    async def test_record_sync_lifecycle(self, store):
        """Should record full sync lifecycle."""
        await store.initialize()

        # Create connector
        await store.save_connector("c1", "github", "Test", {})

        # Start sync
        job = await store.record_sync_start("c1")
        assert job.status == "running"
        assert job.connector_id == "c1"

        # Update progress
        await store.record_sync_progress(job.id, items_synced=50)

        # Complete sync
        completed = await store.record_sync_complete(
            job.id,
            status="completed",
            items_synced=100,
        )

        assert completed is not None
        assert completed.status == "completed"
        assert completed.items_synced == 100
        assert completed.duration_seconds > 0

    @pytest.mark.asyncio
    async def test_get_sync_history(self, store):
        """Should return sync history."""
        await store.initialize()

        await store.save_connector("c1", "github", "Test", {})

        job1 = await store.record_sync_start("c1")
        await store.record_sync_complete(job1.id, status="completed", items_synced=10)

        job2 = await store.record_sync_start("c1")
        await store.record_sync_complete(job2.id, status="completed", items_synced=20)

        history = await store.get_sync_history("c1")
        assert len(history) >= 2

    @pytest.mark.asyncio
    async def test_get_sync_stats(self, store):
        """Should return aggregate statistics."""
        await store.initialize()

        await store.save_connector("c1", "github", "Test", {})

        for i in range(3):
            job = await store.record_sync_start("c1")
            await store.record_sync_complete(
                job.id,
                status="completed" if i < 2 else "failed",
                items_synced=10 * (i + 1),
            )

        stats = await store.get_sync_stats("c1")
        assert stats["total_syncs"] == 3
        assert stats["successful_syncs"] == 2
        assert stats["failed_syncs"] == 1
        assert stats["total_items_synced"] == 60  # 10 + 20 + 30


class TestConnectorConfig:
    """Tests for ConnectorConfig dataclass."""

    def test_default_status(self):
        """Should have default status 'configured'."""
        config = ConnectorConfig(
            id="c1",
            connector_type="github",
            name="Test",
            config={},
        )
        assert config.status == "configured"

    def test_default_items_indexed(self):
        """Should default to 0 items indexed."""
        config = ConnectorConfig(
            id="c1",
            connector_type="github",
            name="Test",
            config={},
        )
        assert config.items_indexed == 0


class TestSyncJobRecovery:
    """Tests for sync job recovery on startup."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Create a temp database path."""
        return tmp_path / "test_recovery.db"

    @pytest.mark.asyncio
    async def test_recovery_marks_running_jobs_as_interrupted(self, db_path):
        """Should mark running jobs as interrupted on startup."""
        # Create store and start a sync job
        store1 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store1.initialize()

        await store1.save_connector("c1", "github", "Test", {})
        job = await store1.record_sync_start("c1")

        # Close without completing - simulates server crash
        await store1.close()

        # Create new store instance - simulates server restart
        store2 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store2.initialize()

        # Job should be marked as interrupted
        history = await store2.get_sync_history("c1")
        assert len(history) == 1
        assert history[0].status == "interrupted"
        assert history[0].error_message == "Job interrupted by server restart"
        assert history[0].completed_at is not None

        await store2.close()

    @pytest.mark.asyncio
    async def test_recovery_updates_connector_status(self, db_path):
        """Should update connector status from active to configured."""
        store1 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store1.initialize()

        await store1.save_connector("c1", "github", "Test", {})
        await store1.record_sync_start("c1")

        # Connector should be active
        conn = await store1.get_connector("c1")
        assert conn.status == "active"

        await store1.close()

        # Restart
        store2 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store2.initialize()

        # Connector should be back to configured with interrupted status
        conn = await store2.get_connector("c1")
        assert conn.status == "configured"
        assert conn.last_sync_status == "interrupted"

        await store2.close()

    @pytest.mark.asyncio
    async def test_recovery_ignores_completed_jobs(self, db_path):
        """Should not affect already completed jobs."""
        store1 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store1.initialize()

        await store1.save_connector("c1", "github", "Test", {})
        job = await store1.record_sync_start("c1")
        await store1.record_sync_complete(job.id, status="completed", items_synced=100)

        await store1.close()

        # Restart
        store2 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store2.initialize()

        # Job should still be completed
        history = await store2.get_sync_history("c1")
        assert len(history) == 1
        assert history[0].status == "completed"
        assert history[0].items_synced == 100

        await store2.close()

    @pytest.mark.asyncio
    async def test_recovery_handles_multiple_running_jobs(self, db_path):
        """Should recover all running jobs."""
        store1 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store1.initialize()

        await store1.save_connector("c1", "github", "Test 1", {})
        await store1.save_connector("c2", "s3", "Test 2", {})

        await store1.record_sync_start("c1")
        await store1.record_sync_start("c2")

        await store1.close()

        # Restart
        store2 = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store2.initialize()

        # Both jobs should be interrupted
        history1 = await store2.get_sync_history("c1")
        history2 = await store2.get_sync_history("c2")

        assert len(history1) == 1
        assert len(history2) == 1
        assert history1[0].status == "interrupted"
        assert history2[0].status == "interrupted"

        await store2.close()

    @pytest.mark.asyncio
    async def test_recovery_can_be_disabled_for_a_store_opened_beside_a_live_owner(self, db_path):
        """A second store opened with recovery disabled leaves running jobs alone."""
        owner = SyncStore(database_url=f"sqlite:///{db_path}", use_encryption=False)
        await owner.initialize()
        await owner.save_connector("c1", "github", "Test", {})
        await owner.record_sync_start("c1")

        side_store = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
            recover_jobs_on_init=False,
        )
        await side_store.initialize()

        history = await side_store.get_sync_history("c1")
        assert len(history) == 1
        assert history[0].status == "running"
        assert history[0].completed_at is None
        assert (await side_store.get_connector("c1")).status == "active"

        await side_store.close()
        await owner.close()

    @pytest.mark.asyncio
    async def test_explicit_recovery_call(self, db_path):
        """Should be able to call recovery explicitly."""

        # Manually insert a running job directly into DB
        async with aiosqlite.connect(str(db_path)) as conn:
            await conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS connectors (
                    id TEXT PRIMARY KEY,
                    connector_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_sync_at TEXT,
                    last_sync_status TEXT,
                    items_indexed INTEGER DEFAULT 0,
                    error_message TEXT
                );

                CREATE TABLE IF NOT EXISTS sync_jobs (
                    id TEXT PRIMARY KEY,
                    connector_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    items_synced INTEGER DEFAULT 0,
                    items_failed INTEGER DEFAULT 0,
                    error_message TEXT,
                    duration_seconds REAL
                );
                """
            )
            await conn.execute(
                """
                INSERT INTO connectors
                (id, connector_type, name, config_json, status, created_at, updated_at)
                VALUES ('c1', 'github', 'Test', '{}', 'active', '2024-01-01T00:00:00+00:00', '2024-01-01T00:00:00+00:00')
                """
            )
            await conn.execute(
                """
                INSERT INTO sync_jobs (id, connector_id, status, started_at)
                VALUES ('job-1', 'c1', 'running', '2024-01-01T00:00:00+00:00')
                """
            )
            await conn.commit()

        # Create store and initialize
        store = SyncStore(
            database_url=f"sqlite:///{db_path}",
            use_encryption=False,
        )
        await store.initialize()

        # Job should already be recovered during init
        history = await store.get_sync_history("c1")
        assert len(history) == 1
        assert history[0].status == "interrupted"

        await store.close()


@pytest.fixture(params=["sqlite", "postgresql"])
async def status_store_url(request, tmp_path):
    """A fresh SQLite file, or a throwaway database on ARAGORA_TEST_DATABASE_URL."""
    if request.param == "sqlite":
        yield f"sqlite:///{tmp_path / 'status.db'}"
        return
    dsn = os.environ.get("ARAGORA_TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set ARAGORA_TEST_DATABASE_URL to run live PostgreSQL tests")
    asyncpg = pytest.importorskip("asyncpg")
    database = "sync_store_test_" + uuid4().hex
    admin = await asyncpg.connect(dsn)
    await admin.execute(f'CREATE DATABASE "{database}"')
    try:
        yield urlsplit(dsn)._replace(path=f"/{database}").geturl()
    finally:
        await admin.execute(f'DROP DATABASE "{database}" WITH (FORCE)')
        await admin.close()


async def test_update_connector_status_persists_on_every_backend(status_store_url):
    store = SyncStore(database_url=status_store_url, use_encryption=False)
    await store.initialize()
    await store._connection.execute(
        "INSERT INTO connectors (id, connector_type, name, config_json, status, created_at,"
        " updated_at, error_message) VALUES ('c1', 'github', 'Seeded', '{}', 'error',"
        " '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00', 'token expired')"
    )
    if status_store_url.startswith("sqlite"):
        await store._connection.commit()
    await store.close()

    store = SyncStore(database_url=status_store_url, use_encryption=False)
    await store.initialize()
    assert await store.update_connector_status("c1", "configuring") is None
    assert await store.update_connector_status("missing", "error", "boom") is None
    await store.close()

    reopened = SyncStore(database_url=status_store_url, use_encryption=False)
    await reopened.initialize()
    try:
        row = await reopened.get_connector("c1")
        assert row is not None
        assert (row.status, row.error_message) == ("configuring", None)
        assert row.updated_at > datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert [c.id for c in await reopened.list_connectors()] == ["c1"]
    finally:
        await reopened.close()


async def test_save_connector_creates_and_edits_on_every_backend(status_store_url):
    store = SyncStore(database_url=status_store_url, use_encryption=True)
    await store.initialize()
    try:
        await store.save_connector("c1", "github", "Repo", {"org": "a", "api_key": "sk-1"})
        await store.save_connector("c1", "github", "Renamed", {"org": "b", "api_key": "sk-2"})
    finally:
        await store.close()

    reopened = SyncStore(database_url=status_store_url, use_encryption=True)
    await reopened.initialize()
    try:
        row = await reopened.get_connector("c1")
        assert row is not None
        assert (row.name, row.config) == ("Renamed", {"org": "b", "api_key": "sk-2"})
    finally:
        await reopened.close()
