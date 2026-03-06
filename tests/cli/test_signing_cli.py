"""Tests for aragora signing CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest


class TestSigningCli:
    def test_sign_creates_manifest(self, tmp_path):
        """aragora signing sign <file> creates .aragora/context_manifest.json."""
        from aragora.cli.commands.signing import cmd_signing_sign

        f = tmp_path / "CLAUDE.md"
        f.write_text("# Test context")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)

        assert manifest_path.exists()
        data = json.loads(manifest_path.read_text())
        assert len(data["entries"]) == 1

    def test_verify_clean_returns_exit_code_0(self, tmp_path):
        """aragora signing verify returns 0 when manifest matches."""
        from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_verify

        f = tmp_path / "CLAUDE.md"
        f.write_text("# Test context")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)
        exit_code = cmd_signing_verify(manifest_path=manifest_path)
        assert exit_code == 0

    def test_verify_tampered_returns_exit_code_1(self, tmp_path):
        """aragora signing verify returns 1 when a file has been tampered."""
        from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_verify

        f = tmp_path / "CLAUDE.md"
        f.write_text("original")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)
        f.write_text("tampered")
        exit_code = cmd_signing_verify(manifest_path=manifest_path)
        assert exit_code == 1

    def test_show_prints_manifest(self, tmp_path, capsys):
        """aragora signing show prints manifest contents."""
        from aragora.cli.commands.signing import cmd_signing_sign, cmd_signing_show

        f = tmp_path / "CLAUDE.md"
        f.write_text("content")
        manifest_path = tmp_path / ".aragora" / "context_manifest.json"

        cmd_signing_sign([str(f)], manifest_path=manifest_path)
        cmd_signing_show(manifest_path=manifest_path)

        captured = capsys.readouterr()
        assert "CLAUDE.md" in captured.out
