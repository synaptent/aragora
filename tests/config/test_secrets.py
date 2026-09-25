"""
Tests for aragora.config.secrets module.

Tests cover:
- Secret retrieval from environment variables
- Secret retrieval from AWS Secrets Manager (mocked)
- Fallback behavior when secrets are not found
- Required secret validation
- Secret manager initialization
- AWS client lazy initialization
- Helper methods for auth and billing secrets
- Cache management
"""

import json
import logging
import os
from pathlib import Path
import time
from unittest.mock import MagicMock, patch

import pytest

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from aragora.config.secrets import (
    CRITICAL_SECRETS,
    MANAGED_SECRETS,
    SecretPresence,
    SecretManager,
    SecretSourceError,
    SecretsConfig,
    _fail_fast_mfa_prompter,
    _has_controlling_tty,
    _mfa_prompt_allowed,
    SecretNotFoundError,
    clear_secret_cache,
    get_required_secret,
    get_secret,
    get_secret_presence,
    get_secret_presence_report,
    hydrate_env_from_secrets,
    is_critical_secret,
    is_secret_presence_available,
    is_secret_usable,
    is_strict_mode,
    get_secret_manager,
    reset_secret_manager,
)


class TestSecretsConfig:
    """Tests for SecretsConfig dataclass."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = SecretsConfig()
        assert config.secrets_dir is None
        assert config.aws_region == "us-east-1"
        assert config.secret_name == "aragora/production"
        assert config.use_aws is False
        assert config.cache_ttl_seconds == 300
        assert config.aws_connect_timeout_seconds == 2.0
        assert config.aws_read_timeout_seconds == 2.0
        assert config.aws_max_attempts == 1

    def test_from_env_defaults(self):
        """Config defaults to local-only secrets in development environments."""
        with patch.dict(os.environ, {}, clear=True):
            config = SecretsConfig.from_env()
            assert config.aws_region == "us-east-1"
            assert config.secret_name == "aragora/production"
            assert config.use_aws is False

    def test_mounted_directory_disables_production_auto_aws(self, tmp_path):
        """A mounted source prevents implicit production AWS probing."""
        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "ARAGORA_SECRETS_DIR": str(tmp_path)},
            clear=True,
        ):
            config = SecretsConfig.from_env()

        assert config.secrets_dir == str(tmp_path)
        assert config.use_aws is False

    def test_mounted_directory_allows_explicit_aws(self, tmp_path):
        """AWS can remain an explicit secondary source with mounted files."""
        with patch.dict(
            os.environ,
            {
                "ARAGORA_ENV": "production",
                "ARAGORA_SECRETS_DIR": str(tmp_path),
                "ARAGORA_USE_SECRETS_MANAGER": "true",
            },
            clear=True,
        ):
            config = SecretsConfig.from_env()

        assert config.secrets_dir == str(tmp_path)
        assert config.use_aws is True

    def test_production_name_does_not_auto_enable_retired_aws(self, caplog):
        """Provider-neutral production never probes AWS solely from its env name."""
        caplog.set_level(logging.WARNING, logger="aragora.config.secrets")
        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True):
            config = SecretsConfig.from_env()
            assert config.use_aws is False
        assert "no managed custody backend is configured" in caplog.text

    def test_aragora_environment_alias_enables_strict_mode(self):
        with patch.dict(os.environ, {"ARAGORA_ENVIRONMENT": "production"}, clear=True):
            assert is_strict_mode() is True

    def test_from_env_defaults_to_use_aws_in_aws_runtime(self):
        """AWS-managed runtimes auto-enable Secrets Manager when unset."""
        with patch.dict(
            os.environ,
            {"AWS_EXECUTION_ENV": "AWS_Lambda_python3.11"},
            clear=True,
        ):
            config = SecretsConfig.from_env()
            assert config.use_aws is True

    def test_from_env_with_values(self):
        """Config loads values from environment."""
        env = {
            "AWS_REGION": "eu-west-1",
            "ARAGORA_SECRET_NAME": "aragora/staging",
            "ARAGORA_USE_SECRETS_MANAGER": "true",
            "ARAGORA_AWS_SECRET_CONNECT_TIMEOUT_SECONDS": "0.5",
            "ARAGORA_AWS_SECRET_READ_TIMEOUT_SECONDS": "1.5",
            "ARAGORA_AWS_SECRET_MAX_ATTEMPTS": "3",
        }
        with patch.dict(os.environ, env, clear=True):
            config = SecretsConfig.from_env()
            assert config.aws_region == "eu-west-1"
            assert config.secret_name == "aragora/staging"
            assert config.use_aws is True
            assert config.aws_connect_timeout_seconds == 0.5
            assert config.aws_read_timeout_seconds == 1.5
            assert config.aws_max_attempts == 3

    @pytest.mark.parametrize("value", ["true", "1", "yes", "TRUE", "Yes"])
    def test_use_aws_truthy_values(self, value):
        """Config recognizes various truthy values for use_aws."""
        with patch.dict(os.environ, {"ARAGORA_USE_SECRETS_MANAGER": value}, clear=True):
            config = SecretsConfig.from_env()
            assert config.use_aws is True

    @pytest.mark.parametrize("value", ["false", "0", "no", "invalid"])
    def test_use_aws_falsy_values(self, value):
        """Config treats non-truthy values as False for use_aws."""
        with patch.dict(os.environ, {"ARAGORA_USE_SECRETS_MANAGER": value}, clear=True):
            config = SecretsConfig.from_env()
            assert config.use_aws is False

    def test_use_aws_default_when_unset(self):
        """Config defaults to use_aws=False when env var is not set in dev."""
        with patch.dict(os.environ, {}, clear=True):
            config = SecretsConfig.from_env()
            assert config.use_aws is False


class TestSecretManager:
    """Tests for SecretManager class."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reset global manager before and after each test."""
        reset_secret_manager()
        clear_secret_cache()
        yield
        reset_secret_manager()
        clear_secret_cache()

    def test_get_from_environment(self):
        """Secrets are retrieved from environment variables."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {"TEST_SECRET": "env_value"}):
            result = manager.get("TEST_SECRET")
            assert result == "env_value"

    def test_get_returns_default_when_not_found(self):
        """Default value is returned when secret not found."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {}, clear=True):
            result = manager.get("NONEXISTENT_SECRET", "default_value")
            assert result == "default_value"

    def test_get_returns_none_when_not_found_no_default(self):
        """None is returned when secret not found and no default."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {}, clear=True):
            result = manager.get("NONEXISTENT_SECRET")
            assert result is None

    def test_get_required_raises_when_missing(self):
        """Required secrets raise ValueError when not found."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Required secret 'MISSING_SECRET' not found"):
                manager.get_required("MISSING_SECRET")

    def test_get_required_returns_value_when_found(self):
        """Required secrets return value when found."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {"FOUND_SECRET": "found_value"}):
            result = manager.get_required("FOUND_SECRET")
            assert result == "found_value"

    def test_get_secrets_batch(self):
        """Multiple secrets can be retrieved at once."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {"SECRET_A": "value_a", "SECRET_B": "value_b"}):
            result = manager.get_secrets(["SECRET_A", "SECRET_B", "SECRET_C"])
            assert result == {
                "SECRET_A": "value_a",
                "SECRET_B": "value_b",
                "SECRET_C": None,
            }

    def test_is_configured_true(self):
        """is_configured returns True when secret exists."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {"CONFIGURED_SECRET": "value"}):
            assert manager.is_configured("CONFIGURED_SECRET") is True

    def test_is_configured_false(self):
        """is_configured returns False when secret missing."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        with patch.dict(os.environ, {}, clear=True):
            assert manager.is_configured("UNCONFIGURED_SECRET") is False


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("mounted_file", True),
        ("aws", True),
        ("env", True),
        ("missing", False),
        ("none", False),
        ("blocked_by_strict_mode", False),
        ("unknown_backend", False),
    ],
)
def test_secret_presence_availability_is_fail_closed(source, expected):
    presence = SecretPresence(name="TEST", source=source, critical=False, managed=False)
    assert is_secret_presence_available(presence) is expected
    assert presence.available is expected


@pytest.mark.parametrize(
    ("module_name", "helper_name"),
    [
        ("aragora.cli.review", "_has_api_key"),
        ("aragora.config.minimal", "_secret_available"),
        ("aragora.inbox.triage_runner", "_has_api_key"),
        ("aragora.rlm.bridge", "_secret_configured"),
        ("aragora.swarm.boss_loop_selection", "_has_api_key"),
    ],
)
def test_availability_helpers_accept_mounted_custody(monkeypatch, module_name, helper_name):
    import importlib

    module = importlib.import_module(module_name)
    mounted = SecretPresence(
        name="OPENROUTER_API_KEY",
        source="mounted_file",
        critical=True,
        managed=True,
    )
    monkeypatch.setattr(module, "get_secret_presence", lambda _name: mounted)
    helper = getattr(module, helper_name)
    assert helper("OPENROUTER_API_KEY") is True


def test_stream_executor_honors_strict_presence(monkeypatch):
    from aragora.server.stream import debate_executor

    blocked = SecretPresence(
        name="OPENROUTER_API_KEY",
        source="blocked_by_strict_mode",
        critical=True,
        managed=True,
    )
    monkeypatch.setattr(debate_executor, "get_secret_presence", lambda _name: blocked)
    assert debate_executor._openrouter_key_available() is False


def test_domain_detector_passes_mounted_key_to_sdk(monkeypatch):
    import anthropic

    from aragora.routing import domain_matcher

    mounted = SecretPresence(
        name="ANTHROPIC_API_KEY",
        source="mounted_file",
        critical=True,
        managed=True,
    )
    client = MagicMock()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(domain_matcher, "get_secret_presence", lambda _name: mounted)
    monkeypatch.setattr(domain_matcher, "get_secret", lambda _name: "mounted-key")
    monkeypatch.setattr(anthropic, "Anthropic", constructor)

    detector = domain_matcher.DomainDetector()
    assert detector.client is client
    constructor.assert_called_once_with(api_key="mounted-key")


class TestSecretManagerMountedFiles:
    """Tests for protected mounted-directory secret custody."""

    @staticmethod
    def _write_secret(
        directory: Path,
        name: str,
        value: str | bytes,
        mode: int = 0o600,
    ) -> Path:
        path = directory / name
        payload = value.encode() if isinstance(value, str) else value
        path.write_bytes(payload)
        path.chmod(mode)
        return path

    def test_mounted_file_precedes_explicit_aws_and_environment(self, tmp_path):
        """Mounted custody wins while AWS remains an explicit secondary source."""
        self._write_secret(tmp_path, "OPENAI_API_KEY", "mounted-value")
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path), use_aws=True))

        with (
            patch.object(manager, "_load_from_aws", return_value={"OPENAI_API_KEY": "aws-value"}),
            patch.dict(os.environ, {"OPENAI_API_KEY": "env-value"}, clear=True),
        ):
            assert manager.get("OPENAI_API_KEY") == "mounted-value"

        assert manager.presence("OPENAI_API_KEY", strict=False).source == "mounted_file"
        assert manager.get_access_log()[0]["source"] == "mounted_file"

    def test_missing_mounted_file_falls_back_to_explicit_aws_then_environment(self, tmp_path):
        """The configured secondary and local fallback order remains intact."""
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path), use_aws=True))
        with (
            patch.object(manager, "_load_from_aws", return_value={"OPENAI_API_KEY": "aws-value"}),
            patch.dict(
                os.environ,
                {"OPENAI_API_KEY": "env-value", "SENTRY_DSN": "env-sentry-value"},
                clear=True,
            ),
        ):
            assert manager.get("OPENAI_API_KEY", strict=False) == "aws-value"
            assert manager.get("SENTRY_DSN", strict=False) == "env-sentry-value"

    def test_strict_mode_accepts_mounted_critical_secret(self, tmp_path):
        """Protected mounted files satisfy strict production custody."""
        self._write_secret(tmp_path, "JWT_SECRET_KEY", "mounted-jwt-value")
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True):
            assert manager.get("JWT_SECRET_KEY") == "mounted-jwt-value"
            presence = manager.presence("JWT_SECRET_KEY")
            assert presence.available is True
            assert manager.is_usable("JWT_SECRET_KEY") is True

        assert presence.source == "mounted_file"
        assert is_secret_presence_available(presence) is True
        assert any(entry["source"] == "usable_mounted_file" for entry in manager.get_access_log())

    def test_strict_mode_rejects_env_when_file_is_absent(self, tmp_path):
        """An empty valid directory does not weaken critical-secret strict mode."""
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "JWT_SECRET_KEY": "env-value"},
            clear=True,
        ):
            with pytest.raises(SecretNotFoundError):
                manager.get("JWT_SECRET_KEY")

    def test_refresh_reloads_rotated_mounted_secret(self, tmp_path):
        """Manual refresh observes atomic secret rotation at the same filename."""
        secret_path = self._write_secret(tmp_path, "OPENAI_API_KEY", "first-value")
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))

        assert manager.get("OPENAI_API_KEY", strict=False) == "first-value"
        secret_path.write_text("rotated-value", encoding="utf-8")
        secret_path.chmod(0o600)
        manager.refresh()

        assert manager.get("OPENAI_API_KEY", strict=False) == "rotated-value"

    def test_hydration_uses_mounted_value_and_records_source(self, tmp_path):
        """Legacy hydration inherits mounted custody with truthful audit provenance."""
        self._write_secret(tmp_path, "SENTRY_DSN", "mounted-sentry-value")
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))

        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {}, clear=True),
        ):
            hydrated = hydrate_env_from_secrets(["SENTRY_DSN"])
            assert hydrated == {"SENTRY_DSN": "mounted-sentry-value"}
            assert os.environ["SENTRY_DSN"] == "mounted-sentry-value"

        assert any(entry["source"] == "hydrate_mounted_file" for entry in manager.get_access_log())

    def test_strict_hydration_overwrites_env_with_managed_value_by_default(self, tmp_path):
        self._write_secret(tmp_path, "OPENAI_API_KEY", "mounted-value")
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_ENV": "production", "OPENAI_API_KEY": "raw-env-value"},
                clear=True,
            ),
        ):
            hydrated = hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=False)
            assert hydrated == {"OPENAI_API_KEY": "mounted-value"}
            assert os.environ["OPENAI_API_KEY"] == "mounted-value"

    @pytest.mark.parametrize("configured", ["relative/secrets", ""])
    def test_directory_must_be_absolute(self, configured):
        """Relative or empty configured paths fail closed before fallback."""
        manager = SecretManager(SecretsConfig(secrets_dir=configured or "."))
        with pytest.raises(SecretSourceError, match="absolute"):
            manager.get("SENTRY_DSN", strict=False)

    def test_directory_rejects_filesystem_root(self):
        manager = SecretManager(SecretsConfig(secrets_dir=os.path.sep))
        with pytest.raises(SecretSourceError, match="filesystem root"):
            manager.get("SENTRY_DSN", strict=False)

    @pytest.mark.parametrize("configured", ["/var/./run/secrets", "/var/run/../secrets"])
    def test_directory_rejects_dot_components(self, configured):
        manager = SecretManager(SecretsConfig(secrets_dir=configured))
        with pytest.raises(SecretSourceError, match="dot components"):
            manager.get("SENTRY_DSN", strict=False)

    def test_directory_symlink_is_rejected(self, tmp_path):
        """No component of the configured directory may be a symlink."""
        target = tmp_path / "target"
        target.mkdir(mode=0o700)
        link = tmp_path / "secrets-link"
        link.symlink_to(target, target_is_directory=True)

        manager = SecretManager(SecretsConfig(secrets_dir=str(link)))
        with pytest.raises(SecretSourceError, match="without following symlinks"):
            manager.get("SENTRY_DSN", strict=False)

    def test_group_writable_directory_is_rejected(self, tmp_path):
        """The configured directory itself may not be writable by peers."""
        tmp_path.chmod(0o770)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        try:
            with pytest.raises(SecretSourceError, match="writable by peers"):
                manager.get("SENTRY_DSN", strict=False)
        finally:
            tmp_path.chmod(0o700)

    @pytest.mark.parametrize(
        ("value", "mode", "message"),
        [
            ("too-open", 0o640, "owner-readable"),
            ("executable", 0o700, "owner-readable"),
            ("\n", 0o600, "must not be empty"),
            (b"\xff\xfe", 0o600, "UTF-8"),
            (b"x" * (64 * 1024 + 1), 0o600, "size limit"),
        ],
    )
    def test_invalid_file_content_or_permissions_fail_closed(
        self, tmp_path, value, mode, message, caplog
    ):
        """Unsafe permissions and malformed values never fall through to env."""
        self._write_secret(tmp_path, "OPENAI_API_KEY", value, mode=mode)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))

        with patch.dict(os.environ, {"OPENAI_API_KEY": "fallback-must-not-win"}, clear=True):
            with pytest.raises(SecretSourceError, match=message) as exc_info:
                manager.get("OPENAI_API_KEY", strict=False)

        assert "fallback-must-not-win" not in str(exc_info.value)
        assert "fallback-must-not-win" not in caplog.text

    def test_symlink_hardlink_and_nonregular_secret_files_are_rejected(self, tmp_path):
        """Only one-link regular files may provide mounted values."""
        outside = tmp_path / "outside"
        outside.write_text("outside-value", encoding="utf-8")
        outside.chmod(0o600)

        symlink_dir = tmp_path / "symlink"
        symlink_dir.mkdir(mode=0o700)
        (symlink_dir / "OPENAI_API_KEY").symlink_to(outside)
        with pytest.raises(SecretSourceError):
            SecretManager(SecretsConfig(secrets_dir=str(symlink_dir))).get(
                "OPENAI_API_KEY", strict=False
            )

        hardlink_dir = tmp_path / "hardlink"
        hardlink_dir.mkdir(mode=0o700)
        os.link(outside, hardlink_dir / "OPENAI_API_KEY")
        with pytest.raises(SecretSourceError, match="single-link"):
            SecretManager(SecretsConfig(secrets_dir=str(hardlink_dir))).get(
                "OPENAI_API_KEY", strict=False
            )

        nonregular_dir = tmp_path / "nonregular"
        nonregular_dir.mkdir(mode=0o700)
        (nonregular_dir / "OPENAI_API_KEY").mkdir(mode=0o700)
        with pytest.raises(SecretSourceError, match="single-link"):
            SecretManager(SecretsConfig(secrets_dir=str(nonregular_dir))).get(
                "OPENAI_API_KEY", strict=False
            )

    def test_invalid_mounted_file_does_not_fallback_to_aws(self, tmp_path):
        """An unsafe primary source fails before any secondary network lookup."""
        self._write_secret(tmp_path, "OPENAI_API_KEY", "unsafe", mode=0o644)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path), use_aws=True))

        with patch.object(manager, "_load_from_aws") as load_from_aws:
            with pytest.raises(SecretSourceError, match="owner-readable"):
                manager.get("OPENAI_API_KEY", strict=False)

        load_from_aws.assert_not_called()

    def test_unmanaged_filenames_are_ignored(self, tmp_path):
        """Directory loading never treats arbitrary filenames as secrets."""
        self._write_secret(tmp_path, "UNMANAGED_SECRET", "must-be-ignored")
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))

        with patch.dict(os.environ, {}, clear=True):
            assert manager.get("UNMANAGED_SECRET", strict=False) is None

    @pytest.mark.parametrize("blank_value", ["", "   "])
    def test_strict_hydration_removes_env_when_managed_cache_value_is_blank(
        self, tmp_path, blank_value
    ):
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        manager._cached_secrets = {"OPENAI_API_KEY": blank_value}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "mounted_file"}
        manager._cache_timestamp = time.time()
        manager._initialized = True
        manager._managed_sources_healthy = True
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_SECRETS_STRICT": "true", "OPENAI_API_KEY": "raw-env-value"},
                clear=True,
            ),
        ):
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {}
            assert "OPENAI_API_KEY" not in os.environ

    def test_strict_hydration_retains_env_after_managed_source_failure(self, tmp_path, caplog):
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path), use_aws=True))
        manager._initialized = True
        manager._managed_sources_healthy = False
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_SECRETS_STRICT": "true", "OPENAI_API_KEY": "hydrated-value"},
                clear=True,
            ),
        ):
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {}
            assert os.environ["OPENAI_API_KEY"] == "hydrated-value"

        access_log = manager.get_access_log()
        assert any(
            entry["source"] == "hydrate_env_retained_source_unhealthy" for entry in access_log
        )
        assert "Retaining previously hydrated critical secret 'OPENAI_API_KEY'" in caplog.text
        assert "hydrated-value" not in caplog.text
        assert all("hydrated-value" not in str(entry) for entry in access_log)

    @pytest.mark.parametrize("overwrite", [False, True])
    def test_strict_hydration_removes_critical_env_fallback(self, tmp_path, caplog, overwrite):
        """Settings hydration cannot reintroduce raw critical env values."""
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with (
            patch("aragora.config.secrets._manager", manager),
            patch.dict(
                os.environ,
                {"ARAGORA_ENVIRONMENT": "production", "JWT_SECRET_KEY": "raw-env-value"},
                clear=True,
            ),
        ):
            assert hydrate_env_from_secrets(["JWT_SECRET_KEY"], overwrite=overwrite) == {}
            assert "JWT_SECRET_KEY" not in os.environ

        assert any(entry["source"] == "hydrate_env_blocked" for entry in manager.get_access_log())
        assert "Removing critical secret 'JWT_SECRET_KEY'" in caplog.text
        assert "raw-env-value" not in caplog.text

    def test_untrusted_intermediate_directory_permissions_are_rejected(self, tmp_path):
        """Every non-sticky writable ancestor is rejected, not only the leaf."""
        parent = tmp_path / "writable-parent"
        parent.mkdir(mode=0o700)
        secret_dir = parent / "secrets"
        secret_dir.mkdir(mode=0o700)
        self._write_secret(secret_dir, "OPENAI_API_KEY", "mounted-value")
        parent.chmod(0o770)
        try:
            manager = SecretManager(SecretsConfig(secrets_dir=str(secret_dir)))
            with pytest.raises(SecretSourceError, match="writable by peers"):
                manager.get("OPENAI_API_KEY", strict=False)
        finally:
            parent.chmod(0o700)

    def test_write_only_secret_file_is_rejected(self, tmp_path):
        """Mounted files must have the owner-read bit, not merely avoid broad modes."""
        self._write_secret(tmp_path, "OPENAI_API_KEY", "mounted-value", mode=0o200)
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        with pytest.raises(SecretSourceError):
            manager.get("OPENAI_API_KEY", strict=False)

    def test_directory_fstat_failure_closes_opened_descriptors(self, tmp_path):
        manager = SecretManager(SecretsConfig(secrets_dir=str(tmp_path)))
        real_open = os.open
        real_close = os.close
        opened: list[int] = []
        closed: list[int] = []

        def tracked_open(*args, **kwargs):
            fd = real_open(*args, **kwargs)
            opened.append(fd)
            return fd

        def tracked_close(fd):
            closed.append(fd)
            real_close(fd)

        with (
            patch("aragora.config.secrets.os.open", side_effect=tracked_open),
            patch("aragora.config.secrets.os.fstat", side_effect=OSError("fstat failed")),
            patch("aragora.config.secrets.os.close", side_effect=tracked_close),
            pytest.raises(SecretSourceError),
        ):
            manager.get("OPENAI_API_KEY", strict=False)

        assert sorted(opened) == sorted(closed)


class TestSecretManagerAWS:
    """Tests for AWS Secrets Manager integration."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reset global manager before and after each test."""
        reset_secret_manager()
        clear_secret_cache()
        yield
        reset_secret_manager()
        clear_secret_cache()

    def test_aws_secrets_cached_on_init(self):
        """AWS secrets are loaded and cached during initialization."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {
            "SecretString": json.dumps({"AWS_SECRET": "aws_value"})
        }

        with patch.object(manager, "_get_aws_client", return_value=mock_client):
            manager._initialize()
            result = manager.get("AWS_SECRET")
            assert result == "aws_value"

    @pytest.mark.parametrize(
        "secret_string",
        [None, json.dumps(["not", "a", "map"]), json.dumps({"KEY": 123})],
    )
    def test_aws_payload_must_be_textual_string_map(self, secret_string):
        manager = SecretManager(SecretsConfig(use_aws=True))
        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": secret_string}
        with patch.object(manager, "_get_aws_client", return_value=mock_client):
            assert manager._load_from_aws() == {}

    def test_aws_cache_takes_precedence_over_env(self):
        """AWS cached secrets take precedence over environment variables."""
        import time

        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {"DUAL_SECRET": "aws_value"}
        manager._cache_timestamp = time.time()  # Set timestamp to prevent cache expiration
        manager._initialized = True

        with patch.dict(os.environ, {"DUAL_SECRET": "env_value"}):
            result = manager.get("DUAL_SECRET")
            assert result == "aws_value"

    def test_refresh_preserves_last_known_aws_cache_on_outage(self):
        manager = SecretManager(SecretsConfig(use_aws=True))
        manager._cached_secrets = {"OPENAI_API_KEY": "last-known-value"}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "aws"}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        client = MagicMock()
        client.get_secret_value.side_effect = OSError("temporary network outage")
        with patch.object(manager, "_get_aws_client", return_value=client):
            manager.refresh()

        assert manager._managed_sources_healthy is False
        assert manager.get("OPENAI_API_KEY", strict=False) == "last-known-value"
        assert manager.presence("OPENAI_API_KEY", strict=False).source == "aws"

    def test_failover_success_replaces_stale_cache_after_transient_primary_error(self):
        manager = SecretManager(SecretsConfig(use_aws=True, aws_regions=["primary", "secondary"]))
        manager._cached_secrets = {"OPENAI_API_KEY": "stale-value"}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "aws"}
        manager._cache_timestamp = time.time()
        manager._initialized = True
        primary = MagicMock()
        primary.get_secret_value.side_effect = OSError("temporary network outage")
        secondary = MagicMock()
        secondary.get_secret_value.return_value = {
            "SecretString": json.dumps({"OPENAI_API_KEY": "fresh-value"})
        }

        with patch.object(
            manager,
            "_get_aws_client",
            side_effect=lambda region: primary if region == "primary" else secondary,
        ):
            manager.refresh()

        assert manager.get("OPENAI_API_KEY", strict=False) == "fresh-value"

    def test_missing_aws_secret_clears_stale_cache(self):
        manager = SecretManager(SecretsConfig(use_aws=True))
        manager._cached_secrets = {"OPENAI_API_KEY": "revoked-value"}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "aws"}
        manager._cache_timestamp = time.time()
        manager._initialized = True
        client = MagicMock()
        client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
            "GetSecretValue",
        )

        with patch.object(manager, "_get_aws_client", return_value=client):
            manager.refresh()

        assert manager.get("OPENAI_API_KEY", strict=False) is None

    @pytest.mark.parametrize("earlier_transient_failure", [False, True])
    @pytest.mark.parametrize(
        "response_kind", ["missing", "invalid-json", "non-text", "non-map", "non-string", "empty"]
    )
    def test_authoritative_refresh_removes_hydrated_credentials(
        self, response_kind, earlier_transient_failure
    ):
        regions = ["primary", "secondary"] if earlier_transient_failure else ["secondary"]
        manager = SecretManager(SecretsConfig(use_aws=True, aws_regions=regions))
        primary, secondary = MagicMock(), MagicMock()
        for client in (primary, secondary):
            client.get_secret_value.return_value = {
                "SecretString": json.dumps({"OPENAI_API_KEY": "revoked-value"})
            }

        with (
            patch.object(
                manager,
                "_get_aws_client",
                side_effect=lambda region: primary if region == "primary" else secondary,
            ),
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_SECRETS_STRICT": "true"}, clear=True),
        ):
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {
                "OPENAI_API_KEY": "revoked-value"
            }
            primary.get_secret_value.side_effect = OSError("temporary network outage")
            if response_kind == "missing":
                secondary.get_secret_value.side_effect = ClientError(
                    {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
                    "GetSecretValue",
                )
            else:
                secondary.get_secret_value.return_value = {
                    "SecretString": {
                        "invalid-json": "not-json",
                        "non-text": None,
                        "non-map": "[]",
                        "non-string": '{"OPENAI_API_KEY": 123}',
                        "empty": "{}",
                    }[response_kind]
                }
            manager.refresh()
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {}
            assert "OPENAI_API_KEY" not in manager._cached_secrets
            assert "OPENAI_API_KEY" not in os.environ

    def test_transient_refresh_retains_hydrated_credentials(self):
        manager = SecretManager(SecretsConfig(use_aws=True))
        client = MagicMock()
        client.get_secret_value.return_value = {
            "SecretString": json.dumps({"OPENAI_API_KEY": "last-known-value"})
        }
        with (
            patch.object(manager, "_get_aws_client", return_value=client),
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_SECRETS_STRICT": "true"}, clear=True),
        ):
            hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True)
            client.get_secret_value.side_effect = OSError("temporary network outage")
            manager.refresh()
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {
                "OPENAI_API_KEY": "last-known-value"
            }
            assert os.environ["OPENAI_API_KEY"] == "last-known-value"

    def test_successful_failover_clears_authoritative_failure(self):
        manager = SecretManager(SecretsConfig(use_aws=True, aws_regions=["primary", "secondary"]))
        primary, secondary = MagicMock(), MagicMock()
        primary.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "missing"}},
            "GetSecretValue",
        )
        secondary.get_secret_value.return_value = {
            "SecretString": json.dumps({"OPENAI_API_KEY": "fresh-value"})
        }
        with (
            patch.object(
                manager,
                "_get_aws_client",
                side_effect=lambda region: primary if region == "primary" else secondary,
            ),
            patch("aragora.config.secrets._manager", manager),
            patch.dict(os.environ, {"ARAGORA_SECRETS_STRICT": "true"}, clear=True),
        ):
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {
                "OPENAI_API_KEY": "fresh-value"
            }
            assert manager._managed_sources_healthy is True
            assert manager._last_aws_load_authoritative_failure is False
            for client in (primary, secondary):
                client.get_secret_value.side_effect = OSError("temporary network outage")
            manager.refresh()
            assert hydrate_env_from_secrets(["OPENAI_API_KEY"], overwrite=True) == {
                "OPENAI_API_KEY": "fresh-value"
            }
            assert manager._managed_sources_healthy is False
            assert manager._last_aws_load_authoritative_failure is False

    def test_successful_empty_aws_refresh_replaces_stale_cache(self):
        manager = SecretManager(SecretsConfig(use_aws=True))
        manager._cached_secrets = {"OPENAI_API_KEY": "stale-value"}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "aws"}
        manager._cache_timestamp = time.time()
        manager._initialized = True
        client = MagicMock()
        client.get_secret_value.return_value = {"SecretString": "{}"}

        with patch.object(manager, "_get_aws_client", return_value=client):
            manager.refresh()

        assert manager.get("OPENAI_API_KEY", strict=False) is None

    def test_blank_managed_value_falls_back_to_env_when_non_strict(self):
        manager = SecretManager(SecretsConfig(use_aws=True))
        manager._cached_secrets = {"OPENAI_API_KEY": ""}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "aws"}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-value"}, clear=True):
            assert manager.get("OPENAI_API_KEY", strict=False) == "env-value"

    def test_fallback_to_env_when_not_in_aws(self):
        """Falls back to environment when secret not in AWS cache."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}  # AWS has no secrets
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(os.environ, {"ENV_ONLY_SECRET": "env_value"}):
            result = manager.get("ENV_ONLY_SECRET")
            assert result == "env_value"

    def test_presence_reports_aws_precedence_without_value(self):
        """Presence checks report AWS source without exposing values."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {"OPENAI_API_KEY": "aws-secret-value"}
        manager._cached_secret_sources = {"OPENAI_API_KEY": "aws"}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(os.environ, {"OPENAI_API_KEY": "env-secret-value"}, clear=True):
            presence = manager.presence("OPENAI_API_KEY")

        assert presence == SecretPresence(
            name="OPENAI_API_KEY",
            source="aws",
            critical=True,
            managed=True,
        )

    def test_presence_reports_unknown_preseeded_cache_provenance(self):
        manager = SecretManager(SecretsConfig(use_aws=True))
        manager._cached_secrets = {"OPENAI_API_KEY": "preseeded-value"}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        presence = manager.presence("OPENAI_API_KEY")

        assert presence.source == "managed_cache"
        assert presence.available is True

    def test_presence_treats_blank_env_as_missing(self):
        """Blank environment values are not usable secret presence."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)
        manager._initialized = True

        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}, clear=True):
            presence = manager.presence("OPENAI_API_KEY", strict=False)

        assert presence.source == "missing"

    def test_is_usable_requires_non_placeholder_length(self):
        """Provider readiness ignores blank and short placeholder values."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)
        manager._initialized = True

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "short"}, clear=True):
            assert manager.is_usable("ANTHROPIC_API_KEY", strict=False) is False

        with patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-ant-test-key-12345"}, clear=True):
            assert manager.is_usable("ANTHROPIC_API_KEY", strict=False) is True

    def test_preseeded_initialized_cache_does_not_refresh_immediately(self):
        """Manually seeded cache state should not trigger an AWS refresh."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}
        manager._initialized = True

        with patch.object(manager, "_load_from_aws") as mock_load:
            with patch.dict(os.environ, {"ENV_ONLY_SECRET": "env_value"}):
                result = manager.get("ENV_ONLY_SECRET")

        assert result == "env_value"
        mock_load.assert_not_called()

    def test_aws_client_lazy_initialization(self):
        """AWS client is lazily initialized only when needed."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        assert manager._aws_clients == {}

        # Force the interactive path so this exercises default-client config plumbing
        # (the non-interactive MFA guard has its own dedicated tests).
        with (
            patch("boto3.client") as mock_boto,
            patch("aragora.config.secrets._has_controlling_tty", return_value=True),
        ):
            mock_boto.return_value = MagicMock()
            client = manager._get_aws_client(manager.config.aws_region)
            assert client is not None
            mock_boto.assert_called_once()
            args, kwargs = mock_boto.call_args
            assert args == ("secretsmanager",)
            assert kwargs["region_name"] == manager.config.aws_region
            assert kwargs["config"].connect_timeout == manager.config.aws_connect_timeout_seconds
            assert kwargs["config"].read_timeout == manager.config.aws_read_timeout_seconds
            assert kwargs["config"].retries["max_attempts"] == manager.config.aws_max_attempts

    def test_aws_client_handles_missing_boto3(self):
        """Gracefully handles missing boto3 library."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        with patch.dict("sys.modules", {"boto3": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'boto3'")):
                client = manager._get_aws_client(manager.config.aws_region)
                assert client is None

    def test_aws_handles_resource_not_found(self):
        """Gracefully handles missing secret in AWS."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        mock_client = MagicMock()
        # Simulate ClientError for ResourceNotFoundException
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "ResourceNotFoundException", "Message": "Secret not found"}},
            "GetSecretValue",
        )

        with patch.object(manager, "_get_aws_client", return_value=mock_client):
            secrets = manager._load_from_aws()
            assert secrets == {}

    def test_aws_handles_access_denied(self):
        """Gracefully handles access denied from AWS."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
            "GetSecretValue",
        )

        with patch.object(manager, "_get_aws_client", return_value=mock_client):
            secrets = manager._load_from_aws()
            assert secrets == {}

    def test_access_denied_does_not_log_secret_values(self, caplog):
        """Denied AWS access must not leak env values in logs."""
        import logging

        caplog.set_level(logging.WARNING)
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.side_effect = ClientError(
            {"Error": {"Code": "AccessDeniedException", "Message": "Access denied"}},
            "GetSecretValue",
        )

        with patch.object(manager, "_get_aws_client", return_value=mock_client):
            with patch.dict(os.environ, {"OPENAI_API_KEY": "do-not-log-this"}, clear=True):
                assert manager._load_from_aws() == {}

        assert "do-not-log-this" not in caplog.text

    def test_aws_handles_invalid_json(self):
        """Gracefully handles invalid JSON from AWS."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)

        mock_client = MagicMock()
        mock_client.get_secret_value.return_value = {"SecretString": "not valid json"}

        with patch.object(manager, "_get_aws_client", return_value=mock_client):
            secrets = manager._load_from_aws()
            assert secrets == {}


class TestSecretManagerHelpers:
    """Tests for helper methods."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reset global manager before and after each test."""
        reset_secret_manager()
        clear_secret_cache()
        yield
        reset_secret_manager()
        clear_secret_cache()

    def test_get_auth_secrets(self):
        """Auth secrets helper returns expected keys."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        env = {
            "JWT_SECRET_KEY": "jwt_secret",
            "JWT_REFRESH_SECRET": "refresh_secret",
            "GOOGLE_OAUTH_CLIENT_ID": "google_id",
            "GOOGLE_OAUTH_CLIENT_SECRET": "google_secret",
        }
        with patch.dict(os.environ, env, clear=True):
            result = manager.get_auth_secrets()
            assert result["JWT_SECRET_KEY"] == "jwt_secret"
            assert result["JWT_REFRESH_SECRET"] == "refresh_secret"
            assert result["GOOGLE_OAUTH_CLIENT_ID"] == "google_id"
            assert result["GOOGLE_OAUTH_CLIENT_SECRET"] == "google_secret"
            assert "GITHUB_OAUTH_CLIENT_ID" in result
            assert "GITHUB_OAUTH_CLIENT_SECRET" in result

    def test_get_billing_secrets(self):
        """Billing secrets helper returns expected keys."""
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)

        env = {
            "STRIPE_SECRET_KEY": "sk_test_123",
            "STRIPE_WEBHOOK_SECRET": "whsec_123",
        }
        with patch.dict(os.environ, env, clear=True):
            result = manager.get_billing_secrets()
            assert result["STRIPE_SECRET_KEY"] == "sk_test_123"
            assert result["STRIPE_WEBHOOK_SECRET"] == "whsec_123"
            assert "STRIPE_PRICE_STARTER" in result
            assert "STRIPE_PRICE_PROFESSIONAL" in result
            assert "STRIPE_PRICE_ENTERPRISE" in result


class TestGlobalFunctions:
    """Tests for module-level functions."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reset global manager before and after each test."""
        reset_secret_manager()
        clear_secret_cache()
        yield
        reset_secret_manager()
        clear_secret_cache()

    def test_get_secret_manager_singleton(self):
        """get_secret_manager returns singleton instance."""
        manager1 = get_secret_manager()
        manager2 = get_secret_manager()
        assert manager1 is manager2

    def test_reset_secret_manager(self):
        """reset_secret_manager clears the singleton."""
        manager1 = get_secret_manager()
        reset_secret_manager()
        manager2 = get_secret_manager()
        assert manager1 is not manager2

    def test_get_secret_function(self):
        """get_secret function works correctly."""
        with patch.dict(os.environ, {"FUNC_SECRET": "func_value"}):
            result = get_secret("FUNC_SECRET")
            assert result == "func_value"

    def test_get_secret_with_default(self):
        """get_secret function returns default when not found."""
        with patch.dict(os.environ, {}, clear=True):
            result = get_secret("MISSING_FUNC_SECRET", "default")
            assert result == "default"

    def test_get_required_secret_function(self):
        """get_required_secret function works correctly."""
        with patch.dict(os.environ, {"REQUIRED_SECRET": "required_value"}):
            result = get_required_secret("REQUIRED_SECRET")
            assert result == "required_value"

    def test_get_required_secret_raises(self):
        """get_required_secret raises when secret missing."""
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                get_required_secret("MISSING_REQUIRED")

    def test_clear_secret_cache(self):
        """clear_secret_cache clears the lru_cache."""
        # Call get_secret to populate cache
        with patch.dict(os.environ, {"CACHED_SECRET": "cached_value"}):
            result1 = get_secret("CACHED_SECRET")
            assert result1 == "cached_value"

        # Clear cache
        clear_secret_cache()

        # Cache should be empty, function should work with new env
        with patch.dict(os.environ, {"CACHED_SECRET": "new_value"}):
            # Note: Due to singleton manager, value may still come from env
            result2 = get_secret("CACHED_SECRET")
            assert result2 == "new_value"


class TestManagedSecrets:
    """Tests for MANAGED_SECRETS constant."""

    def test_managed_secrets_is_frozenset(self):
        """MANAGED_SECRETS is immutable."""
        assert isinstance(MANAGED_SECRETS, frozenset)

    def test_managed_secrets_contains_expected_keys(self):
        """MANAGED_SECRETS contains all expected secret names."""
        expected = [
            "JWT_SECRET_KEY",
            "JWT_REFRESH_SECRET",
            "GOOGLE_OAUTH_CLIENT_ID",
            "GOOGLE_OAUTH_CLIENT_SECRET",
            "GITHUB_OAUTH_CLIENT_ID",
            "GITHUB_OAUTH_CLIENT_SECRET",
            "STRIPE_SECRET_KEY",
            "STRIPE_WEBHOOK_SECRET",
            "DATABASE_URL",
            "SUPABASE_URL",
            "SUPABASE_KEY",
            "REDIS_URL",
            "ANTHROPIC_API_KEY",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "OPENROUTER_API_KEY",
            "SENTRY_DSN",
        ]
        for key in expected:
            assert key in MANAGED_SECRETS, f"Missing managed secret: {key}"

    def test_managed_secrets_count(self):
        """MANAGED_SECRETS contains expected number of secrets."""
        # At least 20 secrets should be managed
        assert len(MANAGED_SECRETS) >= 20


class TestStrictMode:
    """Tests for strict secrets mode (production security)."""

    @pytest.fixture(autouse=True)
    def reset_manager(self):
        """Reset global manager before and after each test."""
        reset_secret_manager()
        clear_secret_cache()
        yield
        reset_secret_manager()
        clear_secret_cache()

    def test_is_strict_mode_disabled_by_default(self):
        """Strict mode is disabled in development by default."""

        with patch.dict(os.environ, {"ARAGORA_ENV": "development"}, clear=True):
            assert is_strict_mode() is False

    def test_is_strict_mode_enabled_in_production(self):
        """Strict mode is enabled in production by default."""

        for env in ["production", "prod", "staging", "stage"]:
            with patch.dict(os.environ, {"ARAGORA_ENV": env}, clear=True):
                assert is_strict_mode() is True, f"Failed for env={env}"

    def test_is_strict_mode_explicit_override(self):
        """Explicit ARAGORA_SECRETS_STRICT overrides default behavior."""

        # Force strict even in development
        with patch.dict(
            os.environ, {"ARAGORA_ENV": "development", "ARAGORA_SECRETS_STRICT": "true"}
        ):
            assert is_strict_mode() is True

        # Disable strict even in production
        with patch.dict(
            os.environ, {"ARAGORA_ENV": "production", "ARAGORA_SECRETS_STRICT": "false"}
        ):
            assert is_strict_mode() is False

    def test_is_critical_secret(self):
        """Critical secrets are correctly identified."""

        # Critical secrets
        assert is_critical_secret("JWT_SECRET_KEY") is True
        assert is_critical_secret("DATABASE_URL") is True
        assert is_critical_secret("STRIPE_SECRET_KEY") is True
        assert is_critical_secret("OPENAI_API_KEY") is True
        assert is_critical_secret("ANTHROPIC_API_KEY") is True
        assert is_critical_secret("OPENROUTER_API_KEY") is True
        assert is_critical_secret("GEMINI_API_KEY") is True
        assert is_critical_secret("GOOGLE_API_KEY") is True
        assert is_critical_secret("XAI_API_KEY") is True
        assert is_critical_secret("GROK_API_KEY") is True
        assert is_critical_secret("MISTRAL_API_KEY") is True
        assert is_critical_secret("DEEPSEEK_API_KEY") is True
        assert is_critical_secret("KIMI_API_KEY") is True

        # Non-critical secrets
        assert is_critical_secret("SENTRY_DSN") is False
        assert is_critical_secret("RANDOM_CONFIG") is False

    def test_strict_mode_raises_for_critical_secret_not_in_aws(self):
        """In strict mode, critical secrets not in AWS raise error."""

        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}  # AWS has no secrets
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "JWT_SECRET_KEY": "env_value"},
            clear=True,
        ):
            with pytest.raises(SecretNotFoundError) as exc_info:
                manager.get("JWT_SECRET_KEY")

            assert "JWT_SECRET_KEY" in str(exc_info.value)
            assert "Secrets Manager" in str(exc_info.value)

    def test_strict_mode_presence_blocks_env_fallback_for_critical_secret(self):
        """Presence check marks env-only critical keys strict-blocked."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "GEMINI_API_KEY": "env-only-gemini"},
            clear=True,
        ):
            presence = manager.presence("GEMINI_API_KEY")

        assert presence.source == "blocked_by_strict_mode"
        assert presence.critical is True
        assert presence.managed is True

    @pytest.mark.parametrize(
        "provider_key",
        [
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "XAI_API_KEY",
            "GROK_API_KEY",
            "MISTRAL_API_KEY",
            "DEEPSEEK_API_KEY",
            "KIMI_API_KEY",
        ],
    )
    def test_strict_mode_raises_for_provider_api_keys_not_in_aws(self, provider_key):
        """Provider API keys must not fall back to env vars in strict mode."""

        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", provider_key: "env_value"},
            clear=True,
        ):
            with pytest.raises(SecretNotFoundError) as exc_info:
                manager.get(provider_key)

            assert provider_key in str(exc_info.value)
            assert "Secrets Manager" in str(exc_info.value)

    def test_strict_mode_allows_non_critical_env_fallback(self):
        """In strict mode, non-critical secrets can still use env fallback."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}  # AWS has no secrets for this test
        manager._cache_timestamp = time.time()
        manager._initialized = True

        # Use a non-critical secret name that won't exist in AWS
        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "TEST_NON_CRITICAL_SECRET": "test-value-123"},
            clear=True,
        ):
            result = manager.get("TEST_NON_CRITICAL_SECRET")
            assert result == "test-value-123"

    def test_strict_mode_allows_aws_critical_secrets(self):
        """In strict mode, critical secrets from AWS are allowed."""
        import time

        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {"JWT_SECRET_KEY": "aws_value"}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(os.environ, {"ARAGORA_ENV": "production"}, clear=True):
            result = manager.get("JWT_SECRET_KEY")
            assert result == "aws_value"

    def test_strict_mode_per_call_override(self):
        """Strict mode can be overridden per-call."""
        config = SecretsConfig(use_aws=True)
        manager = SecretManager(config)
        manager._cached_secrets = {}
        manager._cache_timestamp = time.time()
        manager._initialized = True

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "production", "JWT_SECRET_KEY": "env_value"},
            clear=True,
        ):
            # With strict=False override, env fallback is allowed
            result = manager.get("JWT_SECRET_KEY", strict=False)
            assert result == "env_value"

    def test_non_strict_mode_warns_for_critical_env_secrets(self, caplog):
        """In non-strict mode, critical secrets from env log a warning."""
        import logging

        caplog.set_level(logging.WARNING)

        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)
        manager._initialized = True

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "development", "JWT_SECRET_KEY": "env_value"},
            clear=True,
        ):
            result = manager.get("JWT_SECRET_KEY")
            assert result == "env_value"

        # Should have logged a warning
        assert any("JWT_SECRET_KEY" in record.message for record in caplog.records)
        assert any("environment variable" in record.message for record in caplog.records)

    def test_non_strict_presence_reports_env_for_critical_secret(self, caplog):
        """Non-strict local fallback reports env and does not expose values."""
        import logging

        caplog.set_level(logging.WARNING)
        config = SecretsConfig(use_aws=False)
        manager = SecretManager(config)
        manager._initialized = True

        with patch.dict(
            os.environ,
            {"ARAGORA_ENV": "development", "GROK_API_KEY": "local-grok-value"},
            clear=True,
        ):
            presence = manager.presence("GROK_API_KEY")
            result = manager.get("GROK_API_KEY")

        assert presence.source == "env"
        assert result == "local-grok-value"
        assert "local-grok-value" not in caplog.text
        assert "GROK_API_KEY" in caplog.text

    def test_secret_not_found_error_message(self):
        """SecretNotFoundError has helpful message."""

        error = SecretNotFoundError("TEST_SECRET")
        message = str(error)

        assert "TEST_SECRET" in message
        assert "Secrets Manager" in message
        assert "ARAGORA_SECRETS_STRICT" in message

    def test_critical_secrets_is_frozenset(self):
        """CRITICAL_SECRETS is immutable."""

        assert isinstance(CRITICAL_SECRETS, frozenset)

    def test_critical_secrets_subset_of_managed(self):
        """All critical secrets should be in managed secrets."""

        for secret in CRITICAL_SECRETS:
            assert secret in MANAGED_SECRETS, f"Critical secret {secret} not in MANAGED_SECRETS"

    def test_google_api_key_alias_is_critical_and_managed(self):
        """Gemini's GOOGLE_API_KEY alias follows the same strict path."""
        assert "GOOGLE_API_KEY" in MANAGED_SECRETS
        assert "GOOGLE_API_KEY" in CRITICAL_SECRETS

    def test_api_access_token_is_critical_and_managed(self):
        assert "ARAGORA_API_TOKEN" in MANAGED_SECRETS
        assert "ARAGORA_API_TOKEN" in CRITICAL_SECRETS

    def test_global_presence_helpers(self):
        """Module-level presence helpers report sources without values."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "router-secret"}, clear=True):
            presence = get_secret_presence("OPENROUTER_API_KEY", strict=False)
            report = get_secret_presence_report(("OPENROUTER_API_KEY",), strict=False)

        assert presence.source == "env"
        assert report == [presence]

    def test_global_is_secret_usable_helper(self):
        """Module-level usability helper does not count placeholders."""
        with patch.dict(os.environ, {"OPENROUTER_API_KEY": "short"}, clear=True):
            assert is_secret_usable("OPENROUTER_API_KEY", strict=False) is False


class TestNonInteractiveMfaGuard:
    """The headless-hang fix: a non-interactive process must never block on an AWS
    MFA getpass prompt — it must fail fast and fall back to env/.env secrets."""

    def test_prompt_allowed_only_when_interactive(self):
        assert _mfa_prompt_allowed(isatty=True, env={}) is True
        assert _mfa_prompt_allowed(isatty=False, env={}) is False

    def test_explicit_override_allows_prompt_even_headless(self):
        for val in ("1", "true", "YES"):
            assert (
                _mfa_prompt_allowed(isatty=False, env={"ARAGORA_AWS_ALLOW_MFA_PROMPT": val}) is True
            )

    def test_fail_fast_prompter_raises_instead_of_blocking(self):
        with pytest.raises(RuntimeError, match="no TTY"):
            _fail_fast_mfa_prompter("Enter MFA code: ")

    def test_build_client_uses_guarded_session_when_headless(self):
        """Non-interactive => the assume-role MFA prompter is neutered via a custom
        botocore session, never the default (hang-prone) client."""
        manager = SecretManager(SecretsConfig())
        fake_boto3 = MagicMock()
        with (
            patch("aragora.config.secrets._has_controlling_tty", return_value=False),
            patch.dict(os.environ, {}, clear=True),
        ):
            manager._build_client(fake_boto3, "us-east-1", MagicMock())
        fake_boto3.Session.assert_called_once()  # guarded session path
        fake_boto3.client.assert_not_called()  # never the unguarded default

    def test_build_client_uses_default_when_interactive(self):
        manager = SecretManager(SecretsConfig())
        fake_boto3 = MagicMock()
        with patch("aragora.config.secrets._has_controlling_tty", return_value=True):
            manager._build_client(fake_boto3, "us-east-1", MagicMock())
        fake_boto3.client.assert_called_once()  # normal interactive path
        fake_boto3.Session.assert_not_called()

    def test_real_botocore_prompter_is_failfast_when_headless(self):
        """End-to-end against real botocore: the assume-role provider's prompter is
        replaced with the fail-fast one (so it can't getpass-hang). The guard reaches
        the botocore session via boto3's ``_session`` wrapper."""
        import botocore.session

        manager = SecretManager(SecretsConfig())
        real_botocore_session = botocore.session.get_session()

        class _FakeSession:
            _session = real_botocore_session

            def client(self, **_kw):
                return MagicMock()

        fake_boto3 = MagicMock()
        fake_boto3.Session = _FakeSession
        with (
            patch("aragora.config.secrets._has_controlling_tty", return_value=False),
            patch.dict(os.environ, {}, clear=True),
        ):
            manager._build_client(fake_boto3, "us-east-1", MagicMock())

        # `get_session()` returns a fresh, isolated session per call, so this mutation
        # does not leak into other tests.
        provider = real_botocore_session.get_component("credential_provider").get_provider(
            "assume-role"
        )
        assert provider._prompter is _fail_fast_mfa_prompter

    def test_guard_install_failure_fails_closed_not_back_to_default(self):
        """grok [P2]: if the MFA guard can't be installed in a headless process, we
        must NOT fall back to the unguarded boto3.client() — that would re-enter the
        exact getpass hang. Returns None so the caller uses env/.env secrets."""
        manager = SecretManager(SecretsConfig())
        fake_boto3 = MagicMock()
        fake_boto3.Session.side_effect = RuntimeError("botocore internals changed")
        with (
            patch("aragora.config.secrets._has_controlling_tty", return_value=False),
            patch.dict(os.environ, {}, clear=True),
        ):
            result = manager._build_client(fake_boto3, "us-east-1", MagicMock())
        assert result is None  # fail closed
        fake_boto3.client.assert_not_called()  # never the hang-prone default

    def test_controlling_tty_probe_matches_dev_tty_openability(self):
        """grok [P2]: the gate probes /dev/tty (what getpass uses), not stdin —
        independent of the test runner's own terminal state."""
        with patch("aragora.config.secrets.os.open", side_effect=OSError):
            assert _has_controlling_tty() is False
        with (
            patch("aragora.config.secrets.os.open", return_value=7) as op,
            patch("aragora.config.secrets.os.close") as cl,
        ):
            assert _has_controlling_tty() is True
            op.assert_called_once()
            cl.assert_called_once_with(7)  # fd is closed, not leaked


@pytest.mark.asyncio
@pytest.mark.parametrize("failing_phase", ["refresh", "hydrate"])
async def test_rotation_monitor_survives_custody_failure(failing_phase):
    from aragora.security.aws_key_rotation import RotationMonitor

    rotator = MagicMock()
    rotator.check_secrets_due.return_value = []
    monitor = RotationMonitor(rotator=rotator)
    refresh_error = SecretSourceError("unsafe mount") if failing_phase == "refresh" else None
    hydrate_error = SecretNotFoundError("ARAGORA_API_TOKEN") if failing_phase == "hydrate" else None
    with (
        patch("aragora.config.secrets.refresh_secrets", side_effect=refresh_error),
        patch("aragora.config.secrets.hydrate_env_from_secrets", side_effect=hydrate_error),
    ):
        await monitor._check_and_reload()
