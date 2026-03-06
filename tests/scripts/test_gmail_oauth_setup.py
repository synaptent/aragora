"""Tests for scripts/gmail_oauth_setup.py.

Only tests offline logic (credential checking, instructions, token storage).
Does NOT test the actual OAuth browser flow.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from unittest import mock

import pytest


# ---------------------------------------------------------------------------
# Import helpers -- the script lives outside the package tree, so we import
# the module directly via importlib or sys.path manipulation.
# ---------------------------------------------------------------------------


@pytest.fixture()
def gmail_setup():
    """Import the gmail_oauth_setup module."""
    import importlib
    import sys

    scripts_dir = str(Path(__file__).resolve().parents[2] / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)

    mod = importlib.import_module("gmail_oauth_setup")
    yield mod

    # Clean up sys.path addition
    if scripts_dir in sys.path:
        sys.path.remove(scripts_dir)


# ---------------------------------------------------------------------------
# Credential checking
# ---------------------------------------------------------------------------


class TestCheckCredentials:
    """Tests for get_client_credentials / check_credentials."""

    def test_missing_both(self, gmail_setup, monkeypatch):
        """When no env vars are set, check_credentials returns (False, '', '')."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        ok, cid, csecret = gmail_setup.check_credentials()
        assert ok is False
        assert cid == ""
        assert csecret == ""

    def test_only_client_id(self, gmail_setup, monkeypatch):
        """Having only client ID is not enough."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("GMAIL_CLIENT_ID", "test-id")
        ok, cid, csecret = gmail_setup.check_credentials()
        assert ok is False
        assert cid == "test-id"

    def test_only_client_secret(self, gmail_setup, monkeypatch):
        """Having only client secret is not enough."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("GMAIL_CLIENT_SECRET", "test-secret")
        ok, cid, csecret = gmail_setup.check_credentials()
        assert ok is False

    def test_both_present_gmail_prefix(self, gmail_setup, monkeypatch):
        """GMAIL_CLIENT_ID + GMAIL_CLIENT_SECRET works."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("GMAIL_CLIENT_ID", "my-id")
        monkeypatch.setenv("GMAIL_CLIENT_SECRET", "my-secret")

        ok, cid, csecret = gmail_setup.check_credentials()
        assert ok is True
        assert cid == "my-id"
        assert csecret == "my-secret"

    def test_both_present_google_prefix(self, gmail_setup, monkeypatch):
        """GOOGLE_CLIENT_ID + GOOGLE_CLIENT_SECRET also works."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("GOOGLE_CLIENT_ID", "gid")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "gsecret")

        ok, cid, csecret = gmail_setup.check_credentials()
        assert ok is True
        assert cid == "gid"
        assert csecret == "gsecret"

    def test_gmail_takes_priority(self, gmail_setup, monkeypatch):
        """GMAIL_CLIENT_ID takes priority over GOOGLE_CLIENT_ID."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("GMAIL_CLIENT_ID", "gmail-id")
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "google-id")
        monkeypatch.setenv("GMAIL_CLIENT_SECRET", "s")

        ok, cid, _ = gmail_setup.check_credentials()
        assert cid == "gmail-id"


# ---------------------------------------------------------------------------
# Instructions output
# ---------------------------------------------------------------------------


class TestInstructions:
    """Tests for print_missing_credentials."""

    def test_prints_setup_instructions(self, gmail_setup, capsys):
        """Missing creds should print setup guide."""
        gmail_setup.print_missing_credentials()
        captured = capsys.readouterr()
        assert "Gmail OAuth Setup" in captured.out
        assert "console.cloud.google.com" in captured.out
        assert "Gmail API" in captured.out
        assert "GMAIL_CLIENT_ID" in captured.out
        assert "GMAIL_CLIENT_SECRET" in captured.out
        assert "Authorized redirect URIs" in captured.out
        assert f"localhost:{gmail_setup.CALLBACK_PORT}" in captured.out

    def test_instructions_contain_scopes(self, gmail_setup, capsys):
        """Instructions mention the required scopes."""
        gmail_setup.print_missing_credentials()
        captured = capsys.readouterr()
        assert "gmail.readonly" in captured.out
        assert "gmail.modify" in captured.out


# ---------------------------------------------------------------------------
# Auth URL building
# ---------------------------------------------------------------------------


class TestBuildAuthUrl:
    """Tests for build_auth_url."""

    def test_contains_required_params(self, gmail_setup):
        url = gmail_setup.build_auth_url("test-client-id", "test-state")
        assert "client_id=test-client-id" in url
        assert "state=test-state" in url
        assert "access_type=offline" in url
        assert "prompt=consent" in url
        assert "response_type=code" in url
        assert "gmail.readonly" in url
        assert "gmail.modify" in url
        assert url.startswith("https://accounts.google.com/")


# ---------------------------------------------------------------------------
# Token storage
# ---------------------------------------------------------------------------


class TestTokenStorage:
    """Tests for save_refresh_token / load_refresh_token."""

    def test_save_and_load(self, gmail_setup, tmp_path, monkeypatch):
        """Token round-trips through save/load."""
        token_file = tmp_path / "gmail_refresh_token"
        monkeypatch.setattr(gmail_setup, "TOKEN_DIR", tmp_path)
        monkeypatch.setattr(gmail_setup, "TOKEN_FILE", token_file)

        gmail_setup.save_refresh_token("my-refresh-token-123")

        assert token_file.exists()
        assert gmail_setup.load_refresh_token() == "my-refresh-token-123"

    def test_file_permissions(self, gmail_setup, tmp_path, monkeypatch):
        """Saved token file has 0600 permissions."""
        token_file = tmp_path / "gmail_refresh_token"
        monkeypatch.setattr(gmail_setup, "TOKEN_DIR", tmp_path)
        monkeypatch.setattr(gmail_setup, "TOKEN_FILE", token_file)

        gmail_setup.save_refresh_token("token")

        file_stat = token_file.stat()
        mode = stat.S_IMODE(file_stat.st_mode)
        assert mode == 0o600

    def test_load_missing_returns_none(self, gmail_setup, tmp_path, monkeypatch):
        """load_refresh_token returns None when file doesn't exist."""
        monkeypatch.setattr(gmail_setup, "TOKEN_FILE", tmp_path / "nonexistent")
        assert gmail_setup.load_refresh_token() is None

    def test_creates_parent_directory(self, gmail_setup, tmp_path, monkeypatch):
        """save_refresh_token creates ~/.aragora/ if missing."""
        nested = tmp_path / "sub" / "dir"
        token_file = nested / "gmail_refresh_token"
        monkeypatch.setattr(gmail_setup, "TOKEN_DIR", nested)
        monkeypatch.setattr(gmail_setup, "TOKEN_FILE", token_file)

        gmail_setup.save_refresh_token("tok")
        assert nested.is_dir()
        assert token_file.exists()


# ---------------------------------------------------------------------------
# main() exit codes
# ---------------------------------------------------------------------------


class TestMainExitCodes:
    """Tests for main() return values."""

    def test_exits_1_without_credentials(self, gmail_setup, monkeypatch, capsys):
        """main() returns 1 and prints instructions when creds missing."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        result = gmail_setup.main([])
        assert result == 1

        captured = capsys.readouterr()
        assert "Credentials Not Found" in captured.out

    def test_exits_0_keeping_existing_token(self, gmail_setup, monkeypatch, tmp_path):
        """main() returns 0 when user declines to re-authorize."""
        for var in (
            "GMAIL_CLIENT_ID",
            "GOOGLE_GMAIL_CLIENT_ID",
            "GOOGLE_CLIENT_ID",
            "GMAIL_CLIENT_SECRET",
            "GOOGLE_GMAIL_CLIENT_SECRET",
            "GOOGLE_CLIENT_SECRET",
        ):
            monkeypatch.delenv(var, raising=False)

        monkeypatch.setenv("GMAIL_CLIENT_ID", "id")
        monkeypatch.setenv("GMAIL_CLIENT_SECRET", "secret")

        token_file = tmp_path / "gmail_refresh_token"
        token_file.write_text("existing-token\n")
        monkeypatch.setattr(gmail_setup, "TOKEN_DIR", tmp_path)
        monkeypatch.setattr(gmail_setup, "TOKEN_FILE", token_file)

        # Simulate user typing "n"
        monkeypatch.setattr("builtins.input", lambda _: "n")

        result = gmail_setup.main([])
        assert result == 0
