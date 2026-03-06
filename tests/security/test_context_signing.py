"""Tests for aragora.security.context_signing."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from aragora.security.context_signing import (
    ManifestEntry,
    VerificationResult,
    create_manifest,
    get_signing_key,
    sign_file,
    verify_manifest,
)


@pytest.fixture
def tmp_context_file(tmp_path):
    f = tmp_path / "CLAUDE.md"
    f.write_text("# Test context\nThis is test content.\n")
    return f


class TestSignFile:
    def test_returns_manifest_entry(self, tmp_context_file):
        entry = sign_file(tmp_context_file)
        assert isinstance(entry, ManifestEntry)
        assert entry.path == str(tmp_context_file)
        assert len(entry.sha256) == 64  # 32 bytes hex
        assert entry.hmac_sha256 is None  # no key = hash-only

    def test_with_key_sets_hmac(self, tmp_context_file):
        key = b"test-secret-key-32-bytes-padding"
        entry = sign_file(tmp_context_file, key=key)
        assert entry.hmac_sha256 is not None
        assert len(entry.hmac_sha256) == 64

    def test_sha256_changes_on_content_change(self, tmp_context_file):
        entry1 = sign_file(tmp_context_file)
        tmp_context_file.write_text("# Modified content\n")
        entry2 = sign_file(tmp_context_file)
        assert entry1.sha256 != entry2.sha256


class TestCreateAndVerifyManifest:
    def test_create_writes_manifest_json(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert "entries" in data
        assert len(data["entries"]) == 1

    def test_verify_unchanged_file_is_ok(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        result = verify_manifest(manifest_path)
        assert result.ok
        assert result.violations == []

    def test_verify_tampered_file_fails(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("original content")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        # Tamper
        f.write_text("tampered content")
        result = verify_manifest(manifest_path)
        assert not result.ok
        assert len(result.violations) == 1
        assert "hash mismatch" in result.violations[0]

    def test_verify_missing_file_reported(self, tmp_path):
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        f.unlink()
        result = verify_manifest(manifest_path)
        assert not result.ok
        assert len(result.missing_files) == 1

    def test_hmac_verification_with_correct_key(self, tmp_path):
        key = b"test-secret-key-32-bytes-padding"
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], key=key, manifest_path=manifest_path)
        result = verify_manifest(manifest_path, key=key)
        assert result.ok

    def test_hmac_verification_wrong_key_fails(self, tmp_path):
        key = b"correct-secret-key-32-bytes-padx"
        wrong_key = b"wrong-secret-key-32-bytes-padddx"
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], key=key, manifest_path=manifest_path)
        result = verify_manifest(manifest_path, key=wrong_key)
        assert not result.ok
        assert any("HMAC" in v for v in result.violations)

    def test_no_manifest_returns_manifest_missing(self, tmp_path):
        missing = tmp_path / ".aragora" / "context_manifest.json"
        result = verify_manifest(missing)
        # Non-existent manifest: manifest_missing=True, ok=True
        assert result.manifest_missing is True
        assert result.ok is True

    def test_verify_with_key_fails_when_entry_has_no_hmac(self, tmp_path):
        """When verifying with key but entry was signed without key, result is not ok."""
        f = tmp_path / "ctx.md"
        f.write_text("hello")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        # Sign WITHOUT key
        create_manifest([f], key=None, manifest_path=manifest_path)
        # Verify WITH key
        key = b"test-secret-key-32-bytes-padding"
        result = verify_manifest(manifest_path, key=key)
        assert not result.ok
        assert len(result.unsigned_files) == 1


class TestGetSigningKey:
    def test_returns_none_when_env_absent(self, monkeypatch):
        monkeypatch.delenv("ARAGORA_CONTEXT_SIGNING_KEY", raising=False)
        assert get_signing_key() is None

    def test_decodes_base64_env_var(self, monkeypatch):
        raw = b"test-secret-key-32-bytes-padding"
        monkeypatch.setenv("ARAGORA_CONTEXT_SIGNING_KEY", base64.b64encode(raw).decode())
        assert get_signing_key() == raw
