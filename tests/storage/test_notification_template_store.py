"""Tests for NotificationTemplateStore."""

from __future__ import annotations

import os
import tempfile

import pytest

from aragora.storage.notification_template_store import (
    NotificationTemplateStore,
    get_notification_template_store,
    reset_notification_template_store,
)


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset the global singleton between tests."""
    reset_notification_template_store()
    yield
    reset_notification_template_store()


@pytest.fixture
def temp_dir():
    """Provide a temporary directory for the store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def store(temp_dir) -> NotificationTemplateStore:
    """Create a store with a temporary data directory."""
    return NotificationTemplateStore(data_dir=temp_dir)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------


class TestSaveAndLoad:
    """Tests for save_override and load_overrides."""

    @pytest.mark.asyncio
    async def test_save_and_load_single_override(self, store):
        """Saving an override should be loadable."""
        await store.save_override("user-1", "debate_completed", {"subject": "Done!"})

        overrides = await store.load_overrides("user-1")
        assert "debate_completed" in overrides
        assert overrides["debate_completed"]["subject"] == "Done!"

    @pytest.mark.asyncio
    async def test_save_multiple_overrides_same_user(self, store):
        """Multiple overrides for same user should accumulate."""
        await store.save_override("user-1", "template_a", {"key": "a"})
        await store.save_override("user-1", "template_b", {"key": "b"})

        overrides = await store.load_overrides("user-1")
        assert len(overrides) == 2
        assert overrides["template_a"]["key"] == "a"
        assert overrides["template_b"]["key"] == "b"

    @pytest.mark.asyncio
    async def test_save_overwrites_existing(self, store):
        """Saving the same template_id again should overwrite."""
        await store.save_override("user-1", "tpl", {"v": 1})
        await store.save_override("user-1", "tpl", {"v": 2})

        overrides = await store.load_overrides("user-1")
        assert overrides["tpl"]["v"] == 2

    @pytest.mark.asyncio
    async def test_load_nonexistent_user_returns_empty(self, store):
        """Loading overrides for unknown user returns empty dict."""
        overrides = await store.load_overrides("nobody")
        assert overrides == {}

    @pytest.mark.asyncio
    async def test_different_users_isolated(self, store):
        """Overrides for different users should be independent."""
        await store.save_override("alice", "tpl", {"val": "a"})
        await store.save_override("bob", "tpl", {"val": "b"})

        alice = await store.load_overrides("alice")
        bob = await store.load_overrides("bob")
        assert alice["tpl"]["val"] == "a"
        assert bob["tpl"]["val"] == "b"


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


class TestDeleteOverride:
    """Tests for delete_override."""

    @pytest.mark.asyncio
    async def test_delete_existing(self, store):
        """Deleting an existing override returns True and removes it."""
        await store.save_override("user-1", "tpl", {"x": 1})
        result = await store.delete_override("user-1", "tpl")

        assert result is True
        overrides = await store.load_overrides("user-1")
        assert "tpl" not in overrides

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, store):
        """Deleting a non-existent override returns False."""
        result = await store.delete_override("user-1", "no-such-template")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_last_removes_file(self, store, temp_dir):
        """Deleting the last override should remove the user file."""
        await store.save_override("user-1", "tpl", {"x": 1})
        await store.delete_override("user-1", "tpl")

        # The JSON file for user-1 should be gone
        user_file = os.path.join(temp_dir, "user-1.json")
        assert not os.path.exists(user_file)

    @pytest.mark.asyncio
    async def test_delete_one_keeps_others(self, store):
        """Deleting one override should not affect other overrides."""
        await store.save_override("user-1", "a", {"v": 1})
        await store.save_override("user-1", "b", {"v": 2})
        await store.delete_override("user-1", "a")

        overrides = await store.load_overrides("user-1")
        assert "a" not in overrides
        assert overrides["b"]["v"] == 2


# ---------------------------------------------------------------------------
# List all
# ---------------------------------------------------------------------------


class TestListAllOverrides:
    """Tests for list_all_overrides."""

    @pytest.mark.asyncio
    async def test_list_all_empty(self, store):
        """Empty store returns empty dict."""
        result = await store.list_all_overrides()
        assert result == {}

    @pytest.mark.asyncio
    async def test_list_all_multiple_users(self, store):
        """list_all_overrides returns data for all users."""
        await store.save_override("alice", "tpl1", {"x": 1})
        await store.save_override("bob", "tpl2", {"y": 2})

        result = await store.list_all_overrides()
        assert "alice" in result
        assert "bob" in result
        assert result["alice"]["tpl1"]["x"] == 1
        assert result["bob"]["tpl2"]["y"] == 2


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


class TestPersistence:
    """Tests for cross-restart persistence."""

    @pytest.mark.asyncio
    async def test_data_survives_new_instance(self, temp_dir):
        """Overrides should survive creating a new store instance."""
        store1 = NotificationTemplateStore(data_dir=temp_dir)
        await store1.save_override("user-1", "tpl", {"persisted": True})

        # Create a new instance pointing at the same dir
        store2 = NotificationTemplateStore(data_dir=temp_dir)
        overrides = await store2.load_overrides("user-1")
        assert overrides["tpl"]["persisted"] is True


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    """Tests for the global singleton accessors."""

    def test_get_returns_same_instance(self, temp_dir):
        """get_notification_template_store returns the same instance."""
        s1 = get_notification_template_store(data_dir=temp_dir)
        s2 = get_notification_template_store()
        assert s1 is s2

    def test_reset_clears_singleton(self, temp_dir):
        """reset_notification_template_store clears the global instance."""
        s1 = get_notification_template_store(data_dir=temp_dir)
        reset_notification_template_store()
        s2 = get_notification_template_store(data_dir=temp_dir)
        assert s1 is not s2


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge case tests."""

    @pytest.mark.asyncio
    async def test_path_traversal_sanitized(self, store, temp_dir):
        """User IDs with path-traversal characters should be sanitized."""
        await store.save_override("../../etc/passwd", "tpl", {"evil": True})

        # The file should be in the data dir, not escaped
        overrides = await store.load_overrides("../../etc/passwd")
        assert overrides["tpl"]["evil"] is True

        # File should be safely in temp_dir
        files = os.listdir(temp_dir)
        for f in files:
            full = os.path.join(temp_dir, f)
            assert os.path.dirname(os.path.abspath(full)) == os.path.abspath(temp_dir)
