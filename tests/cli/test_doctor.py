"""
Tests for aragora.cli.doctor module.

Tests health check CLI commands.
"""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.utils.async_helpers import close_coroutine_then

from aragora.cli.doctor import (
    check_api_keys,
    check_environment,
    check_icon,
    check_packages,
    check_server,
    check_storage,
    main,
    print_section,
)

from aragora.config.provider_readiness import PROVIDER_CREDENTIAL_SPECS


def _clear_provider_env(monkeypatch):
    for spec in PROVIDER_CREDENTIAL_SPECS:
        for env_var in spec.env_vars:
            monkeypatch.setenv(env_var, "")
    monkeypatch.setenv("ARAGORA_USE_SECRETS_MANAGER", "false")


# ===========================================================================
# Tests: check_icon
# ===========================================================================


class TestCheckIcon:
    """Tests for check_icon function."""

    def test_true_returns_green(self):
        """Test True returns green checkmark."""
        result = check_icon(True)
        assert "✓" in result
        assert "92m" in result  # Green ANSI code

    def test_false_returns_red(self):
        """Test False returns red X."""
        result = check_icon(False)
        assert "✗" in result
        assert "91m" in result  # Red ANSI code

    def test_none_returns_yellow(self):
        """Test None returns yellow circle."""
        result = check_icon(None)
        assert "○" in result
        assert "93m" in result  # Yellow ANSI code


# ===========================================================================
# Tests: print_section
# ===========================================================================


class TestPrintSection:
    """Tests for print_section function."""

    def test_prints_section(self, capsys):
        """Test printing section header."""
        print_section("Test Section")
        captured = capsys.readouterr()
        assert "Test Section" in captured.out
        assert "-" * 40 in captured.out


# ===========================================================================
# Tests: check_packages
# ===========================================================================


class TestCheckPackages:
    """Tests for check_packages function."""

    def test_returns_list(self):
        """Test returns a list of tuples."""
        result = check_packages()
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 3 for item in result)

    def test_checks_required_packages(self):
        """Test checks required packages."""
        result = check_packages()
        names = [name for name, _, _ in result]

        # These should be checked
        assert "aiohttp" in names
        assert "pydantic" in names
        assert "sqlite3" in names
        assert "asyncio" in names

    def test_checks_optional_ml_packages(self):
        """Test checks optional ML packages."""
        result = check_packages()
        names = [name for name, _, _ in result]

        # At least one ML package should be checked
        ml_pkgs = [n for n in names if "(ML)" in n]
        assert len(ml_pkgs) >= 1

    def test_checks_optional_integrations(self):
        """Test checks optional integrations."""
        result = check_packages()
        names = [name for name, _, _ in result]

        # At least one integration package should be checked
        int_pkgs = [n for n in names if "(integration)" in n]
        assert len(int_pkgs) >= 1

    def test_optional_packages_are_not_imported(self, monkeypatch):
        """Optional probes detect presence without importing heavy native stacks."""
        blocked = {
            "asyncpg",
            "boto3",
            "opentelemetry",
            "redis",
            "sentence_transformers",
            "torch",
            "transformers",
        }
        real_import = builtins.__import__

        def guarded_import(name, *args, **kwargs):
            if name.split(".", 1)[0] in blocked:
                raise AssertionError(f"optional package was imported: {name}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded_import)

        result = check_packages()
        names = [name for name, _, _ in result]

        assert "torch (ML)" in names
        assert "redis (integration)" in names


# ===========================================================================
# Tests: check_api_keys
# ===========================================================================


class TestCheckApiKeys:
    """Tests for check_api_keys function."""

    def test_returns_list(self, monkeypatch):
        """Test returns a list of tuples."""
        _clear_provider_env(monkeypatch)

        result = check_api_keys()
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 3 for item in result)

    def test_no_llm_keys_shows_warning(self, monkeypatch):
        """Test warning when no LLM keys are set."""
        _clear_provider_env(monkeypatch)

        result = check_api_keys()
        names = [name for name, _, _ in result]
        statuses = [status for _, status, _ in result]

        # Should have a warning about no LLM provider
        assert "LLM Provider" in names or any("NO API KEY" in s for s in statuses)

    def test_anthropic_key_configured(self, monkeypatch):
        """Test Anthropic key detection."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        result = check_api_keys()
        anthropic = [item for item in result if item[0] == "ANTHROPIC_API_KEY"]

        assert len(anthropic) == 1
        assert anthropic[0][1] == "configured"
        assert anthropic[0][2] is True

    def test_openai_key_configured(self, monkeypatch):
        """Test OpenAI key detection."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("OPENAI_API_KEY", "test-key")

        result = check_api_keys()
        openai = [item for item in result if item[0] == "OPENAI_API_KEY"]

        assert len(openai) == 1
        assert openai[0][1] == "configured"
        assert openai[0][2] is True

    def test_optional_keys_detected(self, monkeypatch):
        """Test optional API keys are detected."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")

        result = check_api_keys()
        openrouter = [item for item in result if item[0] == "OPENROUTER_API_KEY"]

        assert len(openrouter) == 1
        assert openrouter[0][1] == "configured"
        assert openrouter[0][2] is True

    def test_gemini_only_counts_as_llm_provider(self, monkeypatch):
        """Gemini must satisfy the same provider requirement as validate-env."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        result = check_api_keys()
        llm_provider = [item for item in result if item[0] == "LLM Provider"]

        assert llm_provider == [("LLM Provider", "configured: gemini", True)]

    def test_google_and_grok_aliases_count_as_llm_providers(self, monkeypatch):
        """Provider aliases should not produce a doctor/validate-env disagreement."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
        monkeypatch.setenv("GROK_API_KEY", "test-key")

        result = check_api_keys()
        gemini = [item for item in result if item[0] == "GEMINI_API_KEY/GOOGLE_API_KEY"]
        xai = [item for item in result if item[0] == "XAI_API_KEY/GROK_API_KEY"]
        llm_provider = [item for item in result if item[0] == "LLM Provider"]

        assert gemini == [("GEMINI_API_KEY/GOOGLE_API_KEY", "configured", True)]
        assert xai == [("XAI_API_KEY/GROK_API_KEY", "configured", True)]
        assert llm_provider == [("LLM Provider", "configured: gemini, xai", True)]

    def test_aws_secrets_posture_recognized_when_no_env_keys(self, monkeypatch):
        """Canonical local posture (keys in AWS Secrets Manager, not env) must not FAIL.

        Per project policy, provider keys live in AWS Secrets Manager and are
        loaded via aragora.config.secrets. When the AWS posture is configured and
        a provider key is resolvable there, doctor must report OK/INFO, not FAIL.
        """
        _clear_provider_env(monkeypatch)

        def fake_posture():
            return SimpleNamespace(
                available=True,
                providers=("anthropic",),
                detail="via AWS Secrets Manager",
                honored_by_runtime=True,
            )

        monkeypatch.setattr(
            "aragora.cli.doctor._aws_secrets_provider_posture",
            fake_posture,
        )

        result = check_api_keys()
        llm_provider = [item for item in result if item[0] == "LLM Provider"]

        assert len(llm_provider) == 1
        _name, status, ok = llm_provider[0]
        # Must NOT be a hard failure.
        assert ok is not False
        assert "NO API KEY SET" not in status
        assert "AWS Secrets Manager" in status

    def test_no_env_keys_and_no_aws_posture_is_offline_ready(self, monkeypatch):
        """A keyless machine remains ready for the advertised offline demo path."""
        _clear_provider_env(monkeypatch)

        def fake_posture():
            return SimpleNamespace(
                available=False, providers=(), detail="", honored_by_runtime=False
            )

        monkeypatch.setattr(
            "aragora.cli.doctor._aws_secrets_provider_posture",
            fake_posture,
        )

        result = check_api_keys()
        llm_provider = [item for item in result if item[0] == "LLM Provider"]

        assert llm_provider == [
            (
                "LLM Provider",
                "not configured (offline/demo mode available; required for live debates)",
                None,
            )
        ]

    def test_no_env_keys_still_fail_live_validation(self, monkeypatch):
        """Explicit live validation must fail when no provider can be tested."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setattr(
            "aragora.cli.doctor._aws_secrets_provider_posture",
            lambda: SimpleNamespace(
                available=False, providers=(), detail="", honored_by_runtime=False
            ),
        )

        result = check_api_keys(validate_live=True)

        assert [item for item in result if item[0] == "LLM Provider"] == [
            ("LLM Provider", "NO API KEY SET; live validation unavailable", False)
        ]

    def test_provider_discovery_errors_remain_fail_closed(self, monkeypatch):
        """Offline readiness must not hide malformed credential configuration."""
        monkeypatch.setattr(
            "aragora.cli.doctor.discover_provider_credentials",
            lambda: SimpleNamespace(
                providers=(),
                any_configured=False,
                configured_providers=(),
                discovery_errors=("invalid .env entry",),
            ),
        )
        monkeypatch.setattr(
            "aragora.cli.doctor._aws_secrets_provider_posture",
            lambda: SimpleNamespace(
                available=False, providers=(), detail="", honored_by_runtime=False
            ),
        )

        result = check_api_keys()

        assert [item for item in result if item[0] == "LLM Provider"] == [
            ("LLM Provider", "credential discovery failed (invalid .env entry)", False)
        ]

    def test_aws_posture_present_but_runtime_disabled_warns_not_ok(self, monkeypatch):
        """Keys in AWS but use_aws disabled => WARN (None), not a green OK.

        Guards the P1 finding: doctor must not green-light a posture that
        hydrate_env_from_secrets will not actually honor.
        """
        _clear_provider_env(monkeypatch)

        def fake_posture():
            return SimpleNamespace(
                available=True,
                providers=("anthropic",),
                detail="via AWS Secrets Manager: anthropic",
                honored_by_runtime=False,
            )

        monkeypatch.setattr("aragora.cli.doctor._aws_secrets_provider_posture", fake_posture)

        result = check_api_keys()
        _name, status, ok = [i for i in result if i[0] == "LLM Provider"][0]
        assert ok is None  # optional/warn, not True and not False
        assert "not enabled for this runtime" in status

    def _patch_secrets(self, monkeypatch, *, base, source_for):
        """Patch the secrets layer used by _aws_secrets_provider_posture."""
        manager = MagicMock()
        manager.presence.side_effect = lambda env_var: SimpleNamespace(source=source_for(env_var))
        secrets_mod = MagicMock()
        secrets_mod.SecretsConfig.from_env.return_value = base
        secrets_mod.SecretsConfig.side_effect = lambda **kw: SimpleNamespace(**kw)
        secrets_mod.SecretManager.return_value = manager
        monkeypatch.setitem(sys.modules, "aragora.config.secrets", secrets_mod)
        return secrets_mod

    def _base(self, **over):
        defaults = dict(
            aws_region="us-east-1",
            aws_regions=["us-east-1"],
            secret_name="aragora/production",
            use_aws=True,
            cache_ttl_seconds=60,
            aws_connect_timeout_seconds=2.0,
            aws_read_timeout_seconds=2.0,
            aws_max_attempts=1,
        )
        defaults.update(over)
        return SimpleNamespace(**defaults)

    def test_probe_honored_when_runtime_use_aws_true(self, monkeypatch):
        from aragora.cli.doctor import _aws_secrets_provider_posture

        self._patch_secrets(monkeypatch, base=self._base(use_aws=True), source_for=lambda e: "aws")
        posture = _aws_secrets_provider_posture()
        assert posture.available is True
        assert posture.honored_by_runtime is True

    def test_probe_available_but_not_honored_when_use_aws_false(self, monkeypatch):
        from aragora.cli.doctor import _aws_secrets_provider_posture

        monkeypatch.setenv("AWS_REGION", "us-east-1")
        self._patch_secrets(monkeypatch, base=self._base(use_aws=False), source_for=lambda e: "aws")
        posture = _aws_secrets_provider_posture()
        assert posture.available is True
        assert posture.honored_by_runtime is False

    def test_probe_skips_default_local_without_explicit_aws_signal(self, monkeypatch):
        from aragora.cli.doctor import _aws_secrets_provider_posture

        for env_var in (
            "ARAGORA_USE_SECRETS_MANAGER",
            "ARAGORA_SECRET_NAME",
            "ARAGORA_SECRET_REGIONS",
            "AWS_REGION",
            "AWS_DEFAULT_REGION",
            "AWS_PROFILE",
            "AWS_ACCESS_KEY_ID",
            "AWS_WEB_IDENTITY_TOKEN_FILE",
            "AWS_ROLE_ARN",
            "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
            "AWS_CONTAINER_CREDENTIALS_FULL_URI",
            "AWS_EXECUTION_ENV",
            "AWS_LAMBDA_FUNCTION_NAME",
        ):
            monkeypatch.delenv(env_var, raising=False)

        secrets_mod = self._patch_secrets(
            monkeypatch,
            base=self._base(use_aws=False),
            source_for=lambda e: "aws",
        )

        posture = _aws_secrets_provider_posture()

        assert posture.available is False
        secrets_mod.SecretManager.assert_not_called()

    def test_probe_skips_when_no_region_configured(self, monkeypatch):
        from aragora.cli.doctor import _aws_secrets_provider_posture

        self._patch_secrets(
            monkeypatch,
            base=self._base(aws_region="", aws_regions=[], secret_name=""),
            source_for=lambda e: "aws",
        )
        posture = _aws_secrets_provider_posture()
        assert posture.available is False

    def test_probe_unavailable_when_no_provider_present(self, monkeypatch):
        from aragora.cli.doctor import _aws_secrets_provider_posture

        self._patch_secrets(monkeypatch, base=self._base(), source_for=lambda e: "env")
        posture = _aws_secrets_provider_posture()
        assert posture.available is False

    def test_live_validation_marks_rejected_provider_unready(self, monkeypatch):
        """doctor --validate should not treat an expired configured key as ready."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        def fake_validate_provider_key(provider: str) -> SimpleNamespace:
            assert provider == "gemini"
            return SimpleNamespace(
                remote_status="invalid",
                is_valid=False,
                message="Provider rejected the API key",
            )

        monkeypatch.setattr(
            "aragora.cli.api_keys.validate_provider_key",
            fake_validate_provider_key,
        )

        result = check_api_keys(validate_live=True)
        gemini = [item for item in result if item[0] == "GEMINI_API_KEY/GOOGLE_API_KEY"]
        llm_provider = [item for item in result if item[0] == "LLM Provider"]

        assert gemini == [
            (
                "GEMINI_API_KEY/GOOGLE_API_KEY",
                "configured; live invalid: Provider rejected the API key",
                False,
            )
        ]
        assert llm_provider == [("LLM Provider", "invalid provider(s): gemini", False)]

    def test_live_validation_unverified_key_is_not_a_green_pass(self, monkeypatch):
        """A configured key whose live validation is skipped must render as
        optional/unverified (ok is None), never a green pass (ok is True).

        Regression: a fabricated DeepSeek key previously showed a green
        ``✓ configured; live skipped`` check counting toward "ready to use".
        """
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-totallyfakekey1234567890abcdef")

        def fake_validate_provider_key(provider: str) -> SimpleNamespace:
            assert provider == "deepseek"
            return SimpleNamespace(
                remote_status="skipped",
                is_valid=False,
                unverified=True,
                message="live validation is unavailable",
            )

        monkeypatch.setattr(
            "aragora.cli.api_keys.validate_provider_key",
            fake_validate_provider_key,
        )

        result = check_api_keys(validate_live=True)
        deepseek = [item for item in result if item[0] == "DEEPSEEK_API_KEY"]

        assert len(deepseek) == 1
        label, status, ok = deepseek[0]
        # Must NOT be a green pass.
        assert ok is not True
        # Optional/unverified — yellow circle, not green check, not red X.
        assert ok is None
        assert "unverified" in status.lower()

    def test_live_validation_marks_rejected_deepseek_unready(self, monkeypatch):
        """A bogus DeepSeek key rejected by a real live probe is a failure,
        not a pass — DeepSeek now makes an actual test call."""
        _clear_provider_env(monkeypatch)
        monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-totallyfakekey1234567890abcdef")

        def fake_validate_provider_key(provider: str) -> SimpleNamespace:
            assert provider == "deepseek"
            return SimpleNamespace(
                remote_status="invalid",
                is_valid=False,
                unverified=False,
                message="Provider rejected the API key",
            )

        monkeypatch.setattr(
            "aragora.cli.api_keys.validate_provider_key",
            fake_validate_provider_key,
        )

        result = check_api_keys(validate_live=True)
        deepseek = [item for item in result if item[0] == "DEEPSEEK_API_KEY"]
        llm_provider = [item for item in result if item[0] == "LLM Provider"]

        assert deepseek[0][2] is False
        assert llm_provider == [("LLM Provider", "invalid provider(s): deepseek", False)]


# ===========================================================================
# Tests: check_storage
# ===========================================================================


class TestCheckStorage:
    """Tests for check_storage function."""

    def test_returns_list(self):
        """Test returns a list of tuples."""
        result = check_storage()
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 3 for item in result)

    def test_checks_sqlite(self):
        """Test checks SQLite."""
        result = check_storage()
        sqlite = [item for item in result if "SQLite" in item[0]]

        assert len(sqlite) >= 1
        # SQLite should work
        assert sqlite[0][2] is True

    def test_checks_data_directory(self):
        """Test checks data directory."""
        result = check_storage()
        data_dir = [item for item in result if "Data directory" in item[0]]

        assert len(data_dir) == 1

    def test_database_url_configured(self, monkeypatch):
        """Test DATABASE_URL detection when asyncpg available."""
        monkeypatch.setenv("DATABASE_URL", "postgresql://localhost/test")

        result = check_storage()
        db_url = [item for item in result if item[0] == "DATABASE_URL"]

        # Only checked if asyncpg is available
        if db_url:
            assert db_url[0][1] == "configured"

    def test_redis_url_configured(self, monkeypatch):
        """Test ARAGORA_REDIS_URL detection when redis available."""
        monkeypatch.setenv("ARAGORA_REDIS_URL", "redis://localhost:6379")

        result = check_storage()
        redis_url = [item for item in result if item[0] == "ARAGORA_REDIS_URL"]

        # Only checked if redis is available
        if redis_url:
            assert redis_url[0][1] == "configured"


# ===========================================================================
# Tests: check_server
# ===========================================================================


class TestCheckServer:
    """Tests for check_server function."""

    @pytest.mark.asyncio
    async def test_server_not_running(self):
        """Test server not running detection."""
        mock_session = MagicMock()
        mock_context = MagicMock()
        mock_context.__aenter__ = AsyncMock(side_effect=ConnectionError("Connection refused"))
        mock_context.__aexit__ = AsyncMock(return_value=False)
        mock_session.get.return_value = mock_context

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_client_session):
            result = await check_server()

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_server_running_healthy(self):
        """Test healthy server detection."""
        mock_response = MagicMock()
        mock_response.status = 200

        mock_response_ctx = MagicMock()
        mock_response_ctx.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_response_ctx

        mock_client_session = MagicMock()
        mock_client_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_client_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_client_session):
            result = await check_server()

        assert isinstance(result, list)
        # Check for running status
        server_check = [item for item in result if "Server" in item[0]]
        if server_check:
            assert server_check[0][2] is True
            assert "running" in server_check[0][1]


# ===========================================================================
# Tests: check_environment
# ===========================================================================


class TestCheckEnvironment:
    """Tests for check_environment function."""

    def test_returns_list(self):
        """Test returns a list of tuples."""
        result = check_environment()
        assert isinstance(result, list)
        assert all(isinstance(item, tuple) and len(item) == 3 for item in result)

    def test_checks_python_version(self):
        """Test checks Python version."""
        result = check_environment()
        python = [item for item in result if item[0] == "Python"]

        assert len(python) == 1
        # Should contain version string
        assert "." in python[0][1]

    def test_checks_environment_name(self, monkeypatch):
        """Test checks ARAGORA_ENV."""
        monkeypatch.setenv("ARAGORA_ENV", "production")

        result = check_environment()
        env = [item for item in result if item[0] == "Environment"]

        assert len(env) == 1
        assert env[0][1] == "production"

    def test_checks_debug_mode_enabled(self, monkeypatch):
        """Test checks debug mode when enabled."""
        monkeypatch.setenv("ARAGORA_DEBUG", "true")

        result = check_environment()
        debug = [item for item in result if item[0] == "Debug mode"]

        assert len(debug) == 1
        assert debug[0][1] == "enabled"

    def test_checks_debug_mode_disabled(self, monkeypatch):
        """Test checks debug mode when disabled."""
        monkeypatch.setenv("ARAGORA_DEBUG", "false")

        result = check_environment()
        debug = [item for item in result if item[0] == "Debug mode"]

        assert len(debug) == 1
        assert debug[0][1] == "disabled"


# ===========================================================================
# Tests: main
# ===========================================================================


class TestMain:
    """Tests for main function."""

    def test_runs_all_checks(self, capsys, monkeypatch):
        """Test main runs all check sections."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        # Mock server check to avoid network calls
        with patch("aragora.cli.doctor.check_server", new=AsyncMock(return_value=[])):
            result = main()

        captured = capsys.readouterr()

        # Check all sections are printed
        assert "ARAGORA HEALTH CHECK" in captured.out
        assert "Environment" in captured.out
        assert "Packages" in captured.out
        assert "API Keys" in captured.out
        assert "Storage" in captured.out
        assert "Server" in captured.out
        assert "Summary" in captured.out

    def test_returns_0_when_all_ok(self, monkeypatch):
        """Test returns 0 when all checks pass."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("aragora.cli.doctor.check_server", new=AsyncMock(return_value=[])):
            result = main()

        assert result == 0

    def test_returns_0_for_keyless_offline_readiness(self, monkeypatch):
        """Default doctor succeeds when only live-provider capability is absent."""
        _clear_provider_env(monkeypatch)

        with patch("aragora.cli.doctor.check_server", new=AsyncMock(return_value=[])):
            result = main()

        assert result == 0

    def test_returns_1_when_live_validation_has_no_provider(self, monkeypatch):
        """Explicit live-provider validation remains fail-closed without a key."""
        _clear_provider_env(monkeypatch)

        with patch("aragora.cli.doctor.check_server", new=AsyncMock(return_value=[])):
            result = main(validate_keys=True)

        assert result == 1

    def test_shows_summary(self, capsys, monkeypatch):
        """Test shows summary at end."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        with patch("aragora.cli.doctor.check_server", new=AsyncMock(return_value=[])):
            main()

        captured = capsys.readouterr()
        assert "passed" in captured.out
        assert "failed" in captured.out
        assert "optional" in captured.out

    def test_handles_server_check_exception(self, capsys, monkeypatch):
        """Test handles server check exception gracefully."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        # Make asyncio.run raise an exception
        with patch(
            "asyncio.run",
            side_effect=close_coroutine_then(raise_=RuntimeError("Test error")),
        ):
            result = main()

        captured = capsys.readouterr()
        assert "skipped" in captured.out
