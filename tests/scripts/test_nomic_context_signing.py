"""Unit tests for Nomic Loop Phase 0 context manifest verification integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestNomicLoopContextManifestVerification:
    """Tests for context manifest verification behavior."""

    def test_no_manifest_proceeds_cleanly(self, tmp_path):
        """When no manifest file exists, verify_manifest returns ok=True with manifest_missing=True."""
        from aragora.security.context_signing import VerificationResult, verify_manifest

        result = verify_manifest(tmp_path / ".aragora" / "context_manifest.json")
        assert result.manifest_missing is True
        assert result.ok is True

    def test_valid_manifest_passes_verification(self, tmp_path):
        """Valid manifest -> ok=True, verified_files populated."""
        from aragora.security.context_signing import create_manifest, verify_manifest

        f = tmp_path / "CLAUDE.md"
        f.write_text("# Context")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)

        result = verify_manifest(manifest_path)
        assert result.ok
        assert str(f) in result.verified_files
        assert result.violations == []

    def test_tampered_file_fails_verification(self, tmp_path):
        """Tampered file -> ok=False, violations contain 'hash mismatch'."""
        from aragora.security.context_signing import create_manifest, verify_manifest

        f = tmp_path / "CLAUDE.md"
        f.write_text("original")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"
        create_manifest([f], manifest_path=manifest_path)
        f.write_text("tampered")

        result = verify_manifest(manifest_path)
        assert not result.ok
        assert any("hash mismatch" in v for v in result.violations)
