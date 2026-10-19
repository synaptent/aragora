"""Tests for presence-only secrets CLI commands."""

from __future__ import annotations

import json
from types import SimpleNamespace

from aragora.cli.commands.secrets import cmd_secrets_health
from aragora.cli.parser import build_parser
from aragora.config.secrets import clear_secret_cache, reset_secret_manager


class TestSecretsParser:
    def test_health_parses(self):
        args = build_parser().parse_args(
            ["secrets", "health", "--json", "--name", "GEMINI_API_KEY"]
        )

        assert args.command == "secrets"
        assert args.secrets_command == "health"
        assert args.json is True
        assert args.name == ["GEMINI_API_KEY"]

    def test_hydrate_parses(self):
        args = build_parser().parse_args(["secrets", "hydrate", "--overwrite"])

        assert args.command == "secrets"
        assert args.secrets_command == "hydrate"
        assert args.overwrite is True


class TestSecretsHealthCommand:
    def setup_method(self):
        reset_secret_manager()
        clear_secret_cache()

    def teardown_method(self):
        reset_secret_manager()
        clear_secret_cache()

    def test_health_json_reports_presence_without_value(self, monkeypatch, capsys):
        monkeypatch.setenv("OPENROUTER_API_KEY", "do-not-print")
        monkeypatch.setenv("ARAGORA_SECRETS_STRICT", "false")

        args = SimpleNamespace(name=["OPENROUTER_API_KEY"], json=True, require_all=False)
        assert cmd_secrets_health(args) == 0

        output = capsys.readouterr().out
        payload = json.loads(output)
        assert payload["secrets"][0]["source"] == "env"
        assert "do-not-print" not in output

    def test_require_all_fails_for_missing_secret(self, monkeypatch, capsys):
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.setenv("ARAGORA_SECRETS_STRICT", "false")

        args = SimpleNamespace(name=["GEMINI_API_KEY"], json=True, require_all=True)
        assert cmd_secrets_health(args) == 1

        output = capsys.readouterr().out
        payload = json.loads(output)
        assert payload["secrets"][0]["source"] == "missing"

    @staticmethod
    def _mount(tmp_path, monkeypatch):
        rejected = tmp_path / "ANTHROPIC_API_KEY"
        rejected.write_text("unsafe-mounted-value", encoding="utf-8")
        rejected.chmod(0o644)
        valid = tmp_path / "OPENAI_API_KEY"
        valid.write_text("mounted-openai-value", encoding="utf-8")
        valid.chmod(0o600)
        monkeypatch.setenv("ARAGORA_SECRETS_DIR", str(tmp_path))
        monkeypatch.setenv("ARAGORA_SECRETS_STRICT", "false")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fallback-must-not-win")

    def test_health_json_names_rejected_mounted_file(self, tmp_path, monkeypatch, capsys):
        self._mount(tmp_path, monkeypatch)

        args = SimpleNamespace(
            name=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], json=True, require_all=False
        )
        assert cmd_secrets_health(args) == 0

        output = capsys.readouterr().out
        payload = json.loads(output)
        sources = {row["name"]: row["source"] for row in payload["secrets"]}
        assert sources == {
            "ANTHROPIC_API_KEY": "mounted_file_rejected",
            "OPENAI_API_KEY": "mounted_file",
        }
        assert list(payload["mounted_file_problems"]) == ["ANTHROPIC_API_KEY"]
        assert "ANTHROPIC_API_KEY" in payload["mounted_file_problems"]["ANTHROPIC_API_KEY"]
        for value in ("unsafe-mounted-value", "mounted-openai-value", "fallback-must-not-win"):
            assert value not in output

    def test_health_table_names_rejected_file_and_require_all_fails(
        self, tmp_path, monkeypatch, capsys
    ):
        self._mount(tmp_path, monkeypatch)

        args = SimpleNamespace(
            name=["ANTHROPIC_API_KEY", "OPENAI_API_KEY"], json=False, require_all=True
        )
        assert cmd_secrets_health(args) == 1

        output = capsys.readouterr().out
        assert "mounted_file_rejected" in output
        assert "Rejected mounted secret files" in output
        assert "must use owner-readable, owner-only permissions" in output
        for value in ("unsafe-mounted-value", "mounted-openai-value", "fallback-must-not-win"):
            assert value not in output
