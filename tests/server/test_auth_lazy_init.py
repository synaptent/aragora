"""Lazy-initialization contract for the ``aragora.server.auth.auth_config`` singleton.

The module-level singleton must NOT parse ``AuthSettings`` (``get_settings().auth``)
at import time: with a cold settings cache and an invalid ``ARAGORA_*`` variable,
an import-time parse kills pytest at collection (``found no collectors``, rc=4)
instead of failing inside a test, misattributing env-pollution failures.

These tests pin two things:

1. Deferral (subprocess-based, cold settings cache): importing the module under a
   poisoned env succeeds, the parse happens on FIRST USE, and pytest collection of
   a module that imports ``aragora.server.auth`` no longer dies.
2. Preservation (in-process): the public name ``auth_config`` keeps working for
   from-imports, module attribute access, ``mock.patch`` /
   ``monkeypatch.setattr`` targets, and the module-level helpers
   (``check_auth``, ``generate_shareable_link``, ``resolve_shareable_session``)
   see a patched module attribute exactly as they did when the singleton was
   eagerly constructed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import aragora.server.auth as auth_mod

REPO_ROOT = Path(__file__).resolve().parents[2]

# Violates AuthSettings.token_ttl (ge=60) so the pydantic parse raises, while
# AuthConfig.configure_from_env's own int() parse of the same variable succeeds:
# the failure isolates to the get_settings().auth parse site.
_POISON_VAR = "ARAGORA_TOKEN_TTL"
_POISON_VALUE = "7"

# The historical collection victim: its module-level
# `from aragora.server.auth import ...` makes pytest import aragora.server.auth
# while collecting it.
_VICTIM_FILE = "tests/server/test_security.py"
_VICTIM_NODE = f"{_VICTIM_FILE}::TestConfigureFromEnv::test_configure_from_env_negative_ttl"


def _poisoned_env() -> dict[str, str]:
    """Inherited env minus all ARAGORA_* vars, plus the poison and safe defaults."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("ARAGORA_")}
    env.update(
        {
            # Importing aragora.server without AWS neutralization can hit
            # botocore MFA getpass on this machine class.
            "AWS_CONFIG_FILE": "/dev/null",
            "AWS_SHARED_CREDENTIALS_FILE": "/dev/null",
            "AWS_EC2_METADATA_DISABLED": "true",
            "ARAGORA_ENV": "development",
            "ARAGORA_SECRETS_STRICT": "false",
            _POISON_VAR: _POISON_VALUE,
        }
    )
    return env


def _run_python(code: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


class TestImportDefersSettingsParse:
    """Cold-cache subprocess proofs that the parse moved from import to first use."""

    def test_import_succeeds_under_poisoned_env_and_parse_defers_to_first_use(self):
        code = (
            "import sys\n"
            "import aragora.server.auth as auth_mod\n"
            "assert 'auth_config' not in vars(auth_mod), 'materialized at import'\n"
            "try:\n"
            "    auth_mod.auth_config\n"
            "except Exception:\n"
            "    sys.exit(0)\n"
            "sys.exit(3)\n"
        )
        proc = _run_python(code, _poisoned_env())
        assert proc.returncode == 0, (
            f"expected import to succeed and first use to raise under poisoned env; "
            f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

    def test_first_use_constructs_configured_singleton_under_clean_env(self):
        env = _poisoned_env()
        env[_POISON_VAR] = "3600"
        env["ARAGORA_API_TOKEN"] = "lazy-init-proof-token"
        code = (
            "import aragora.server.auth as auth_mod\n"
            "assert 'auth_config' not in vars(auth_mod), 'materialized at import'\n"
            "from aragora.server.auth import auth_config\n"
            "assert auth_config.enabled, 'configure_from_env not applied on first use'\n"
            "assert auth_config is auth_mod.auth_config\n"
            "assert auth_config is auth_mod.get_auth_config()\n"
        )
        proc = _run_python(code, env)
        assert proc.returncode == 0, (
            f"expected lazy singleton to be configured on first use; "
            f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

    def test_collection_of_auth_importing_module_survives_poisoned_env(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                _VICTIM_FILE,
                "--collect-only",
                "-q",
                "-p",
                "no:randomly",
            ],
            cwd=REPO_ROOT,
            env=_poisoned_env(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        combined = proc.stdout + proc.stderr
        assert proc.returncode == 0, (
            f"collection died under poisoned env (rc={proc.returncode}):\n{combined[-3000:]}"
        )
        assert "error during collection" not in combined, (
            f"collection reported errors under poisoned env:\n{combined[-3000:]}"
        )

    def test_node_id_selection_no_longer_reports_found_no_collectors(self):
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                _VICTIM_NODE,
                "--collect-only",
                "-q",
                "-p",
                "no:randomly",
            ],
            cwd=REPO_ROOT,
            env=_poisoned_env(),
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        combined = proc.stdout + proc.stderr
        assert "found no collectors" not in combined, (
            f"the rc=4 'found no collectors' collection failure is back:\n{combined[-3000:]}"
        )
        assert proc.returncode == 0, (
            f"node-id collection failed under poisoned env (rc={proc.returncode}):\n{combined[-3000:]}"
        )


class TestPublicNamePreserved:
    """In-process guards: importers and patchers keep working against the lazy name."""

    def test_from_import_returns_the_singleton(self):
        from aragora.server.auth import auth_config as first
        from aragora.server.auth import auth_config as second

        assert first is second
        assert isinstance(first, auth_mod.AuthConfig)
        assert first is auth_mod.get_auth_config()

    def test_module_attribute_identity_is_stable(self):
        assert auth_mod.auth_config is auth_mod.auth_config

    def test_unknown_module_attribute_still_raises(self):
        with pytest.raises(AttributeError, match="no attribute"):
            auth_mod.definitely_not_a_real_attribute

    def test_mock_patch_is_seen_by_check_auth_and_restores_identity(self):
        before = auth_mod.auth_config
        stub = mock.Mock()
        stub.enabled = False
        with mock.patch("aragora.server.auth.auth_config", stub):
            assert auth_mod.auth_config is stub
            authenticated, remaining = auth_mod.check_auth({})
            assert authenticated is True
            assert remaining == -1
        assert auth_mod.auth_config is before

    def test_monkeypatch_setattr_is_seen_and_restored(self, monkeypatch):
        before = auth_mod.auth_config
        sentinel = SimpleNamespace(enabled=False)
        monkeypatch.setattr(auth_mod, "auth_config", sentinel)
        authenticated, remaining = auth_mod.check_auth({})
        assert authenticated is True
        assert remaining == -1
        monkeypatch.undo()
        assert auth_mod.auth_config is before

    def test_shareable_link_helpers_use_patched_config(self):
        class _StubConfig:
            def generate_session(self, loop_id, expires_in):
                assert loop_id == "loop-1"
                return "sess-lazy-123"

            def resolve_session(self, session_id):
                assert session_id == "sess-lazy-123"
                return True, "tok", "loop-1"

        with mock.patch("aragora.server.auth.auth_config", _StubConfig()):
            link = auth_mod.generate_shareable_link("http://example.test/d", "loop-1")
            assert link == "http://example.test/d?session=sess-lazy-123"
            assert auth_mod.resolve_shareable_session("sess-lazy-123") == (
                True,
                "tok",
                "loop-1",
            )

    def test_dir_lists_auth_config_before_materialization(self):
        listing = dir(auth_mod)
        assert "auth_config" in listing
        assert "check_auth" in listing
        assert "get_auth_config" in listing


def _alive_cleanup_threads() -> list[threading.Thread]:
    return [t for t in threading.enumerate() if t.name == "auth-cleanup" and t.is_alive()]


class TestFailedConfigurationDoesNotLeak:
    """AuthConfig.__init__ starts the cleanup thread; a raising configure_from_env
    (e.g. production mode without a token) must not leak one thread per retry,
    and must not cache a half-configured singleton."""

    def test_failed_configure_leaves_no_cleanup_thread_cold_process(self):
        # Subprocess: the session autouse fixture suppresses cleanup-thread
        # starts in-process, so the leak is only observable in a cold process.
        env = _poisoned_env()
        env[_POISON_VAR] = "3600"
        env["ARAGORA_ENV"] = "production"  # configure_from_env raises: no token
        code = (
            "import threading, sys\n"
            "import aragora.server.auth as auth_mod\n"
            "for attempt in range(2):\n"
            "    try:\n"
            "        auth_mod.get_auth_config()\n"
            "    except Exception:\n"
            "        pass\n"
            "    else:\n"
            "        sys.exit(3)  # configure unexpectedly succeeded\n"
            "leaked = [t for t in threading.enumerate()\n"
            "          if t.name == 'auth-cleanup' and t.is_alive()]\n"
            "sys.exit(4 if leaked else 0)\n"
        )
        proc = _run_python(code, env)
        assert proc.returncode == 0, (
            f"failed configuration leaked cleanup threads or unexpectedly succeeded; "
            f"rc={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )

    def test_failed_configure_reaps_thread_and_does_not_cache(self, monkeypatch):
        real_configure = auth_mod.AuthConfig.configure_from_env
        monkeypatch.setattr(auth_mod, "_auth_config", None)

        def _boom(self):
            raise auth_mod.AuthenticationError("configure boom")

        monkeypatch.setattr(auth_mod.AuthConfig, "configure_from_env", _boom)
        baseline = len(_alive_cleanup_threads())

        for _ in range(2):
            with pytest.raises(auth_mod.AuthenticationError, match="configure boom"):
                auth_mod.get_auth_config()

        assert len(_alive_cleanup_threads()) == baseline, (
            "failed configuration leaked auth-cleanup threads"
        )

        # Recovery: once the environment is sane, first use succeeds and caches.
        monkeypatch.setattr(auth_mod.AuthConfig, "configure_from_env", real_configure)
        cfg = auth_mod.get_auth_config()
        assert isinstance(cfg, auth_mod.AuthConfig)
        assert auth_mod.get_auth_config() is cfg
        # Reap the recovered instance's thread; teardown restores the session
        # singleton, discarding this instance.
        cfg.stop_cleanup_thread()
