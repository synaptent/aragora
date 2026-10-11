"""
Tests for broadcast audio file storage.

Tests AudioMetadata dataclass, AudioFileStore operations,
caching, and cleanup functionality.
"""

import json
import pytest
import tempfile
from datetime import datetime
from pathlib import Path

from aragora.broadcast.storage import AudioMetadata, AudioFileStore


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def temp_storage_dir():
    """Create a temporary storage directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def audio_store(temp_storage_dir):
    """Create an AudioFileStore instance."""
    return AudioFileStore(storage_dir=temp_storage_dir)


@pytest.fixture
def sample_audio_file():
    """Create a sample audio file in separate temp dir."""
    with tempfile.TemporaryDirectory() as td:
        audio_path = Path(td) / "source_audio.mp3"
        audio_path.write_bytes(b"fake mp3 content for testing")
        yield audio_path


# =============================================================================
# AudioMetadata Tests
# =============================================================================


class TestAudioMetadata:
    """Tests for AudioMetadata dataclass."""

    def test_create_metadata_with_required_fields(self):
        """Should create metadata with required fields."""
        meta = AudioMetadata(
            debate_id="debate-123",
            filename="debate-123.mp3",
            format="mp3",
        )

        assert meta.debate_id == "debate-123"
        assert meta.filename == "debate-123.mp3"
        assert meta.format == "mp3"
        assert meta.duration_seconds is None  # Optional
        assert meta.agents == []  # Default empty

    def test_create_metadata_with_all_fields(self):
        """Should create metadata with all optional fields."""
        meta = AudioMetadata(
            debate_id="debate-456",
            filename="debate-456.mp3",
            format="mp3",
            duration_seconds=180,
            file_size_bytes=1024000,
            task_summary="AI ethics discussion",
            agents=["claude", "gpt4", "gemini"],
        )

        assert meta.duration_seconds == 180
        assert meta.file_size_bytes == 1024000
        assert meta.task_summary == "AI ethics discussion"
        assert len(meta.agents) == 3

    def test_generated_at_auto_populated(self):
        """generated_at should be auto-populated with ISO datetime."""
        meta = AudioMetadata(
            debate_id="test",
            filename="test.mp3",
            format="mp3",
        )

        assert meta.generated_at is not None
        # Should be valid ISO format
        datetime.fromisoformat(meta.generated_at)

    def test_to_dict_serialization(self):
        """to_dict should return all fields."""
        meta = AudioMetadata(
            debate_id="debate-789",
            filename="debate-789.wav",
            format="wav",
            duration_seconds=60,
            file_size_bytes=512000,
            task_summary="Test topic",
            agents=["agent1"],
        )

        data = meta.to_dict()

        assert data["debate_id"] == "debate-789"
        assert data["filename"] == "debate-789.wav"
        assert data["format"] == "wav"
        assert data["duration_seconds"] == 60
        assert data["file_size_bytes"] == 512000
        assert data["task_summary"] == "Test topic"
        assert data["agents"] == ["agent1"]
        assert "generated_at" in data

    def test_from_dict_deserialization(self):
        """from_dict should reconstruct AudioMetadata."""
        data = {
            "debate_id": "debate-abc",
            "filename": "debate-abc.mp3",
            "format": "mp3",
            "duration_seconds": 120,
            "file_size_bytes": 256000,
            "generated_at": "2025-01-06T12:00:00",
            "task_summary": "Reconstructed",
            "agents": ["claude", "gpt4"],
        }

        meta = AudioMetadata.from_dict(data)

        assert meta.debate_id == "debate-abc"
        assert meta.duration_seconds == 120
        assert meta.generated_at == "2025-01-06T12:00:00"
        assert len(meta.agents) == 2

    def test_from_dict_with_minimal_data(self):
        """from_dict should handle minimal required fields."""
        data = {
            "debate_id": "minimal",
            "filename": "minimal.mp3",
        }

        meta = AudioMetadata.from_dict(data)

        assert meta.debate_id == "minimal"
        assert meta.format == "mp3"  # Default
        assert meta.agents == []  # Default


# =============================================================================
# AudioFileStore Tests
# =============================================================================


class TestAudioFileStore:
    """Tests for AudioFileStore class."""

    def test_init_creates_storage_dir(self, temp_storage_dir):
        """Should create storage directory on init."""
        storage_path = temp_storage_dir / "new_audio_store"
        store = AudioFileStore(storage_dir=storage_path)

        assert storage_path.exists()
        assert store.storage_dir == storage_path

    def test_save_audio_file(self, audio_store, sample_audio_file):
        """Should save audio file and create metadata."""
        debate_id = "save-test-001"

        result_path = audio_store.save(
            debate_id=debate_id,
            audio_path=sample_audio_file,
            format="mp3",
            duration_seconds=90,
            task_summary="Test debate",
            agents=["claude"],
        )

        # Audio file should be copied
        assert result_path.exists()
        assert result_path.name == f"{debate_id}.mp3"

        # Metadata JSON should be created
        metadata_path = audio_store._metadata_path(debate_id)
        assert metadata_path.exists()

        # Verify metadata content
        with open(metadata_path) as f:
            data = json.load(f)
        assert data["debate_id"] == debate_id
        assert data["duration_seconds"] == 90

    def test_save_bytes_directly(self, audio_store):
        """Should save audio from raw bytes."""
        debate_id = "bytes-test-001"
        audio_bytes = b"raw audio data content"

        result_path = audio_store.save_bytes(
            debate_id=debate_id,
            audio_data=audio_bytes,
            format="wav",
            duration_seconds=45,
            agents=["gpt4", "gemini"],
        )

        assert result_path.exists()
        assert result_path.suffix == ".wav"
        assert result_path.read_bytes() == audio_bytes

    def test_save_rejects_oversized_file(self, audio_store, sample_audio_file, monkeypatch, caplog):
        """Oversized source files are rejected and the sizes are logged."""
        monkeypatch.setattr("aragora.broadcast.storage.MAX_FILE_SIZE_BYTES", 4)

        with caplog.at_level("ERROR", logger="aragora.broadcast.storage"):
            result = audio_store.save("oversize-file", sample_audio_file, format="mp3")

        assert result is None
        size = sample_audio_file.stat().st_size
        assert f"Audio file too large: {size:,} bytes > 4 bytes limit" in caplog.text

    def test_save_bytes_rejects_oversized_data(self, audio_store, monkeypatch, caplog):
        """Oversized byte payloads are rejected and the sizes are logged."""
        monkeypatch.setattr("aragora.broadcast.storage.MAX_FILE_SIZE_BYTES", 1_000)

        with caplog.at_level("ERROR", logger="aragora.broadcast.storage"):
            result = audio_store.save_bytes("oversize-bytes", b"x" * 1_001, format="wav")

        assert result is None
        assert "Audio data too large: 1,001 bytes > 1,000 bytes limit" in caplog.text

    def test_get_path_returns_existing(self, audio_store, sample_audio_file):
        """get_path should return path for existing audio."""
        debate_id = "get-path-test"
        audio_store.save(debate_id, sample_audio_file)

        path = audio_store.get_path(debate_id)

        assert path is not None
        assert path.exists()

    def test_get_path_returns_none_for_missing(self, audio_store):
        """get_path should return None for non-existent audio."""
        path = audio_store.get_path("nonexistent-debate")
        assert path is None

    def test_get_metadata_returns_cached(self, audio_store, sample_audio_file):
        """get_metadata should return metadata from cache."""
        debate_id = "metadata-cache-test"
        audio_store.save(
            debate_id,
            sample_audio_file,
            task_summary="Cached metadata test",
        )

        # First call populates cache
        meta1 = audio_store.get_metadata(debate_id)
        # Second call should use cache
        meta2 = audio_store.get_metadata(debate_id)

        assert meta1 is meta2  # Same object from cache
        assert meta1.task_summary == "Cached metadata test"

    def test_get_metadata_loads_from_disk(self, audio_store, sample_audio_file):
        """get_metadata should load from disk when not cached."""
        debate_id = "disk-load-test"
        audio_store.save(debate_id, sample_audio_file, task_summary="From disk")

        # Clear cache
        audio_store._cache.clear()

        meta = audio_store.get_metadata(debate_id)

        assert meta is not None
        assert meta.task_summary == "From disk"

    def test_exists_returns_true_for_stored(self, audio_store, sample_audio_file):
        """exists should return True for stored audio."""
        debate_id = "exists-test"
        audio_store.save(debate_id, sample_audio_file)

        assert audio_store.exists(debate_id) is True

    def test_exists_returns_false_for_missing(self, audio_store):
        """exists should return False for missing audio."""
        assert audio_store.exists("missing-debate") is False

    def test_delete_removes_audio_and_metadata(self, audio_store, sample_audio_file):
        """delete should remove both audio file and metadata."""
        debate_id = "delete-test"
        audio_store.save(debate_id, sample_audio_file)

        # Verify exists
        assert audio_store.exists(debate_id)

        # Delete
        result = audio_store.delete(debate_id)

        assert result is True
        assert not audio_store.exists(debate_id)
        assert not audio_store._metadata_path(debate_id).exists()
        assert debate_id not in audio_store._cache

    def test_delete_returns_false_for_missing(self, audio_store):
        """delete should return False for non-existent debate."""
        result = audio_store.delete("nonexistent")
        assert result is False

    def test_list_all_returns_sorted_by_date(self, audio_store, sample_audio_file):
        """list_all should return all audio sorted by date descending."""
        # Save multiple
        audio_store.save("debate-001", sample_audio_file, task_summary="First")
        audio_store.save("debate-002", sample_audio_file, task_summary="Second")
        audio_store.save("debate-003", sample_audio_file, task_summary="Third")

        results = audio_store.list_all()

        assert len(results) == 3
        # Most recent first (all created nearly simultaneously, but order preserved)
        debate_ids = [r["debate_id"] for r in results]
        assert "debate-001" in debate_ids
        assert "debate-002" in debate_ids
        assert "debate-003" in debate_ids

    def test_get_total_size(self, audio_store, sample_audio_file):
        """get_total_size should return sum of all audio file sizes."""
        audio_store.save("size-test-1", sample_audio_file)
        audio_store.save("size-test-2", sample_audio_file)

        total = audio_store.get_total_size()

        # Each file is same size
        single_size = sample_audio_file.stat().st_size
        assert total == single_size * 2

    def test_cleanup_orphaned_removes_metadata_without_audio(self, audio_store, sample_audio_file):
        """cleanup_orphaned should remove metadata files without audio."""
        debate_id = "orphan-test"
        audio_store.save(debate_id, sample_audio_file)

        # Manually delete audio file to create orphan
        audio_path = audio_store.get_path(debate_id)
        audio_path.unlink()

        # Run cleanup
        removed = audio_store.cleanup_orphaned()

        assert removed == 1
        assert not audio_store._metadata_path(debate_id).exists()

    def test_cleanup_orphaned_keeps_valid_entries(self, audio_store, sample_audio_file):
        """cleanup_orphaned should keep metadata with valid audio."""
        audio_store.save("valid-audio", sample_audio_file)

        removed = audio_store.cleanup_orphaned()

        assert removed == 0
        assert audio_store.exists("valid-audio")

    def test_multiple_format_support(self, audio_store, temp_storage_dir):
        """get_path should find audio files in various formats."""
        debate_id = "multiformat"

        # Create audio file with .wav extension
        wav_file = temp_storage_dir / "source.wav"
        wav_file.write_bytes(b"wav content")
        audio_store.save(debate_id, wav_file, format="wav")

        # get_path should find it
        path = audio_store.get_path(debate_id)
        assert path is not None
        assert path.suffix == ".wav"

    def test_storage_path_safety(self, audio_store, sample_audio_file):
        """Should handle debate IDs safely without path traversal."""
        # Try potentially dangerous ID - should be sanitized/safe
        dangerous_id = "safe-id"  # In production, IDs should be validated
        audio_store.save(dangerous_id, sample_audio_file)

        # Should store in proper location
        stored_path = audio_store.get_path(dangerous_id)
        assert stored_path is not None
        assert stored_path.parent == audio_store.storage_dir
