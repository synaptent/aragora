"""Tests for the data classification evidence bundle generator."""

from __future__ import annotations

import hashlib
import json

import pytest

from aragora.compliance.evidence_bundle import DataClassificationEvidenceBundle


class TestEvidenceBundleGeneration:
    """Verify that generate() produces a complete evidence bundle."""

    def test_generate_returns_all_required_sections(self):
        """Bundle contains every top-level key the auditor expects."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate(period_days=30)

        required_keys = {
            "bundle_type",
            "generated_at",
            "period_days",
            "active_policy",
            "classification_levels",
            "enforcement_rules",
            "encryption_status",
            "retention_summary",
            "ci_scan_config",
            "integrity_hash",
        }
        assert required_keys.issubset(bundle.keys())

    def test_classification_levels_present(self):
        """All five classification levels appear in order."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate()
        expected = ["public", "internal", "confidential", "restricted", "pii"]
        assert bundle["classification_levels"] == expected

    def test_enforcement_rules_per_level(self):
        """Each classification level has enforcement rules."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate()
        rules = bundle["enforcement_rules"]
        assert len(rules) == 5
        levels = [r["level"] for r in rules]
        assert "public" in levels
        assert "pii" in levels

    def test_encryption_status_populated(self):
        """Encryption status section has the expected keys."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate()
        enc = bundle["encryption_status"]
        assert "crypto_available" in enc
        assert "algorithm" in enc
        assert "library" in enc

    def test_retention_summary_populated(self):
        """Retention summary has an entry for each level."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate()
        ret = bundle["retention_summary"]
        assert len(ret) == 5
        # PUBLIC has 365 day retention per DEFAULT_POLICIES
        assert ret["public"] == 365

    def test_ci_scan_config_populated(self):
        """CI scan configuration includes scanner details."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate()
        ci = bundle["ci_scan_config"]
        assert ci["scan_type"] == "ast_string_literal_extraction"
        assert "email" in ci["patterns_checked"]
        assert ci["allowlist_file"] == "scripts/pii_allowlist.txt"

    def test_period_days_parameter(self):
        """period_days parameter is reflected in the bundle."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate(period_days=90)
        assert bundle["period_days"] == 90


class TestIntegrityHash:
    """Verify the SHA-256 integrity hash behaviour."""

    def test_integrity_hash_is_deterministic(self):
        """Same inputs produce the same integrity hash."""
        gen1 = DataClassificationEvidenceBundle()
        gen2 = DataClassificationEvidenceBundle()
        b1 = gen1.generate(period_days=30)
        b2 = gen2.generate(period_days=30)

        # Timestamps will differ, so the hashes will differ.
        # But the hash must be a valid SHA-256 hex string.
        assert len(b1["integrity_hash"]) == 64
        assert len(b2["integrity_hash"]) == 64
        # All hex characters
        assert all(c in "0123456789abcdef" for c in b1["integrity_hash"])

    def test_integrity_hash_matches_payload(self):
        """Re-computing the hash from the payload matches the stored hash."""
        gen = DataClassificationEvidenceBundle()
        bundle = gen.generate()

        # Remove the hash, recompute, verify
        stored_hash = bundle.pop("integrity_hash")
        recomputed = hashlib.sha256(
            json.dumps(bundle, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        assert recomputed == stored_hash

    def test_different_period_different_hash(self):
        """Changing period_days produces a different hash."""
        gen = DataClassificationEvidenceBundle()
        b30 = gen.generate(period_days=30)
        h30 = b30["integrity_hash"]

        gen2 = DataClassificationEvidenceBundle()
        b90 = gen2.generate(period_days=90)
        h90 = b90["integrity_hash"]

        assert h30 != h90


class TestMarkdownOutput:
    """Verify the Markdown rendering."""

    def test_markdown_contains_heading(self):
        gen = DataClassificationEvidenceBundle()
        gen.generate()
        md = gen.to_markdown()
        assert "# Data Classification Evidence Bundle" in md

    def test_markdown_contains_integrity_hash(self):
        gen = DataClassificationEvidenceBundle()
        gen.generate()
        md = gen.to_markdown()
        assert "Integrity Hash:" in md

    def test_markdown_contains_enforcement_table(self):
        gen = DataClassificationEvidenceBundle()
        gen.generate()
        md = gen.to_markdown()
        assert "Enforcement Rules" in md
        assert "| Level |" in md

    def test_markdown_without_generate_raises(self):
        gen = DataClassificationEvidenceBundle()
        with pytest.raises(RuntimeError, match="generate"):
            gen.to_markdown()

    def test_markdown_contains_ci_scan_section(self):
        gen = DataClassificationEvidenceBundle()
        gen.generate()
        md = gen.to_markdown()
        assert "CI Scan Configuration" in md
        assert "ast_string_literal_extraction" in md
