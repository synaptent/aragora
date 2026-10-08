"""Tests for ObsidianFileWatcher — real-time vault monitoring.

Also includes backward-compatibility tests for the legacy VaultWatcher API.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aragora.connectors.knowledge.obsidian_watcher import (
    ObsidianFileWatcher,
    WatcherConfig,
    FileChangeEvent,
    ChangeType,
    # Legacy API
    VaultChangeEvent,
    VaultWatcher,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "test_vault"
    vault.mkdir()
    (vault / ".obsidian").mkdir()
    return vault


@pytest.fixture
def watcher_config(temp_vault: Path) -> WatcherConfig:
    return WatcherConfig(
        vault_path=str(temp_vault),
        debounce_ms=50,
        watch_tags=["#aragora", "#debate"],
        ignore_folders=[".obsidian", ".trash"],
    )


# =============================================================================
# New Config-Object API Tests
# =============================================================================


class TestWatcherConfig:
    def test_default_debounce(self) -> None:
        config = WatcherConfig(vault_path="/tmp/vault")
        assert config.debounce_ms == 500

    def test_custom_watch_tags(self) -> None:
        config = WatcherConfig(vault_path="/tmp/vault", watch_tags=["#custom"])
        assert config.watch_tags == ["#custom"]

    def test_default_watch_tags(self) -> None:
        config = WatcherConfig(vault_path="/tmp/vault")
        assert config.watch_tags == ["#aragora", "#debate"]

    def test_default_ignore_folders(self) -> None:
        config = WatcherConfig(vault_path="/tmp/vault")
        assert ".obsidian" in config.ignore_folders
        assert ".trash" in config.ignore_folders

    def test_custom_ignore_folders(self) -> None:
        config = WatcherConfig(vault_path="/tmp/vault", ignore_folders=["private"])
        assert config.ignore_folders == ["private"]


class TestFileChangeEvent:
    def test_create_event(self) -> None:
        event = FileChangeEvent(
            path="notes/test.md",
            change_type=ChangeType.MODIFIED,
        )
        assert event.change_type == ChangeType.MODIFIED
        assert event.path == "notes/test.md"

    def test_event_has_timestamp(self) -> None:
        event = FileChangeEvent(
            path="notes/test.md",
            change_type=ChangeType.CREATED,
        )
        assert isinstance(event.timestamp, float)
        assert event.timestamp > 0

    def test_change_type_values(self) -> None:
        assert ChangeType.CREATED.value == "created"
        assert ChangeType.MODIFIED.value == "modified"
        assert ChangeType.DELETED.value == "deleted"


class TestObsidianFileWatcher:
    def test_init(self, watcher_config: WatcherConfig) -> None:
        watcher = ObsidianFileWatcher(watcher_config)
        assert not watcher.is_running

    def test_should_ignore_non_markdown(self, watcher_config: WatcherConfig) -> None:
        watcher = ObsidianFileWatcher(watcher_config)
        assert watcher._should_ignore("image.png")
        assert not watcher._should_ignore("note.md")

    def test_should_ignore_obsidian_folder(self, watcher_config: WatcherConfig) -> None:
        watcher = ObsidianFileWatcher(watcher_config)
        assert watcher._should_ignore(".obsidian/config.json")
        assert watcher._should_ignore(".trash/deleted.md")

    @pytest.mark.asyncio
    async def test_callback_on_file_change(
        self, watcher_config: WatcherConfig, temp_vault: Path
    ) -> None:
        callback = AsyncMock()
        watcher = ObsidianFileWatcher(watcher_config, on_change=callback)

        note = temp_vault / "test_note.md"
        note.write_text("---\ntags: [aragora]\n---\n# Test")

        watcher._handle_file_event(str(note), ChangeType.CREATED)
        await watcher._flush_debounce()

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, FileChangeEvent)
        assert event.change_type == ChangeType.CREATED

    @pytest.mark.asyncio
    async def test_debounce_coalesces_rapid_changes(
        self, watcher_config: WatcherConfig, temp_vault: Path
    ) -> None:
        callback = AsyncMock()
        watcher = ObsidianFileWatcher(watcher_config, on_change=callback)

        note = temp_vault / "rapid.md"
        watcher._handle_file_event(str(note), ChangeType.MODIFIED)
        watcher._handle_file_event(str(note), ChangeType.MODIFIED)
        watcher._handle_file_event(str(note), ChangeType.MODIFIED)

        await watcher._flush_debounce()

        assert callback.call_count == 1

    @pytest.mark.asyncio
    async def test_no_callback_means_no_error(
        self, watcher_config: WatcherConfig, temp_vault: Path
    ) -> None:
        """Flushing without a callback should not raise."""
        watcher = ObsidianFileWatcher(watcher_config)

        note = temp_vault / "silent.md"
        watcher._handle_file_event(str(note), ChangeType.MODIFIED)
        await watcher._flush_debounce()  # Should not raise

    @pytest.mark.asyncio
    async def test_ignored_file_not_queued(
        self, watcher_config: WatcherConfig, temp_vault: Path
    ) -> None:
        """Files that should be ignored are not added to pending."""
        callback = AsyncMock()
        watcher = ObsidianFileWatcher(watcher_config, on_change=callback)

        png = temp_vault / "photo.png"
        watcher._handle_file_event(str(png), ChangeType.CREATED)
        await watcher._flush_debounce()

        callback.assert_not_called()


# =============================================================================
# Legacy VaultWatcher API Tests (backward compatibility)
# =============================================================================


class TestVaultWatcherInit:
    """Tests for VaultWatcher initialization."""

    def test_init_with_valid_vault(self, temp_vault: Path) -> None:
        watcher = VaultWatcher(vault_path=str(temp_vault))
        assert watcher.vault_path == Path(temp_vault)
        assert watcher.debounce_ms == 500
        assert watcher.watch_tags is None
        assert set(watcher.ignore_folders) == {".obsidian", ".trash", "templates"}
        assert watcher.is_running is False

    def test_init_with_custom_debounce(self, temp_vault: Path) -> None:
        watcher = VaultWatcher(vault_path=str(temp_vault), debounce_ms=200)
        assert watcher.debounce_ms == 200

    def test_init_with_tag_filter(self, temp_vault: Path) -> None:
        tags = ["#debate", "#decision"]
        watcher = VaultWatcher(vault_path=str(temp_vault), watch_tags=tags)
        assert watcher.watch_tags == ["#debate", "#decision"]

    def test_init_with_ignore_folders(self, temp_vault: Path) -> None:
        folders = [".obsidian", "archive"]
        watcher = VaultWatcher(vault_path=str(temp_vault), ignore_folders=folders)
        assert watcher.ignore_folders == [".obsidian", "archive"]


class TestShouldProcess:
    """Tests for _should_process path filtering."""

    def test_should_process_markdown_file(self, temp_vault: Path) -> None:
        watcher = VaultWatcher(vault_path=str(temp_vault))
        md_path = str(temp_vault / "notes" / "my-note.md")
        assert watcher._should_process(md_path) is True

    def test_should_process_ignores_configured_folders(self, temp_vault: Path) -> None:
        watcher = VaultWatcher(vault_path=str(temp_vault))
        assert watcher._should_process(str(temp_vault / ".obsidian" / "config.json")) is False
        assert watcher._should_process(str(temp_vault / ".trash" / "old.md")) is False
        assert watcher._should_process(str(temp_vault / "templates" / "daily.md")) is False

    def test_should_process_non_vault_path(self, temp_vault: Path) -> None:
        watcher = VaultWatcher(vault_path=str(temp_vault))
        assert watcher._should_process(str(temp_vault / "notes" / "image.png")) is False
        assert watcher._should_process(str(temp_vault / "data.json")) is False
        assert watcher._should_process(str(temp_vault / "readme.txt")) is False


class TestChangeHandling:
    """Tests for async change handling and debouncing (legacy API)."""

    @pytest.mark.asyncio
    async def test_on_change_calls_callback(self, temp_vault: Path) -> None:
        callback = AsyncMock()
        watcher = VaultWatcher(vault_path=str(temp_vault), on_change=callback)

        file_path = str(temp_vault / "notes" / "test.md")
        await watcher._handle_change(file_path, "created")
        await watcher._flush_pending()

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert isinstance(event, VaultChangeEvent)
        assert event.path == file_path
        assert event.change_type == "created"
        assert isinstance(event.timestamp, float)

    @pytest.mark.asyncio
    async def test_debounce_coalesces_rapid_changes(self, temp_vault: Path) -> None:
        callback = AsyncMock()
        watcher = VaultWatcher(vault_path=str(temp_vault), on_change=callback)

        file_path = str(temp_vault / "notes" / "test.md")
        await watcher._handle_change(file_path, "modified")
        await watcher._handle_change(file_path, "modified")
        await watcher._handle_change(file_path, "modified")

        await watcher._flush_pending()

        callback.assert_called_once()
        event = callback.call_args[0][0]
        assert event.change_type == "modified"


class TestLifecycle:
    """Tests for start/stop lifecycle (legacy API)."""

    def test_start_stop_lifecycle(self, temp_vault: Path) -> None:
        pytest.importorskip("watchdog")
        with patch("aragora.connectors.knowledge.obsidian_watcher.Observer") as MockObserver:
            mock_observer = MagicMock()
            MockObserver.return_value = mock_observer

            watcher = VaultWatcher(vault_path=str(temp_vault))

            assert watcher.is_running is False

            watcher.start()
            assert watcher.is_running is True
            mock_observer.schedule.assert_called_once()
            mock_observer.start.assert_called_once()

            watcher.stop()
            assert watcher.is_running is False
            mock_observer.stop.assert_called_once()
            mock_observer.join.assert_called_once()
